# 实时上下文与记忆 paging 计划

> 状态：研究计划（2026-09-24）。本文只提出下一阶段可回放的实验，不把方案写成已实现能力。

## 1. 当前边界

仓库已有 `PagedMemoryIndex`、`TwoStageMemorySelector` 和 `ContextResidencyManager`。前者维护稳定 `page_id`、summary/content、revision、依赖版本、敏感标记和有界读取；`select_pages` 目前是确定性的词法预筛，`read_selected` 在读前统一检查 revision、权限和字节预算。后者保留 pinned/working/cold block，使用类型 aging、hysteresis、minimum residency 和可替换 working set。选择器目前先对页摘要做一次 Jev 排序，再选择 `TOP_N` 前缀，读取失败会报告 stale、预算或权限错误。

这些机制尚不足以证明混合检索、事件触发、摘要回溯、冲突校验或 learned replacement 的收益。运行时可以替换上下文，因此不把跨请求 prefix/KV reuse 当作前提；这不等于断言 Jev 服务内部没有 cache，也不把 Jev 返回的选择概率称为 calibrated probability。

评估必须分开三件事：

1. **paging 命中率**：目标页是否进入 resident/读取集合；
2. **needle evidence recall**：金标准证据是否被读取且可定位；
3. **任务答案正确率**：最终回答或工具参数是否正确。

三者不能互相替代。长上下文研究显示，相关信息在中间位置时模型利用率可能下降，而首尾位置更有利（Lost in the Middle）。因此单报 page hit 或 token/字节节省会误导结论。[Liu et al., TACL 2024](https://aclweb.org/anthology/2024.tacl-1.9.pdf)

## 2. 方案候选

### A. 混合检索与 rank fusion

**输入**：query、页摘要/标签、稀疏词法排名、可选向量排名、时间/依赖/phase 特征。**输出**：稳定 `page_id` 的融合排序和证据类型标签。首版用 Reciprocal Rank Fusion（RRF）作为可解释基线，不能把各分数直接当概率；RRF 是组合多个排序的经典方法。[Cormack, Clarke & Büttcher, SIGIR 2009](https://doi.org/10.1145/1571941.1572114)

**触发与预算**：词法召回不足、query 含实体别名或跨语言词时触发第二路；每路最多 32 页，融合后最多 16 页，向量/索引读取有独立毫秒和字节预算。

**风险**：相关页排名提高但冲突页被压掉；不同索引的 page ID 或 revision 不一致；融合参数未经校准导致过度自信。

**测法**：固定页集和 query，比较词法、向量、RRF；报告 page hit、needle recall、MRR/nDCG、读取字节、fault 次数、最终答案正确率和 P50/P95。按 `summary-only`、`summary+tags`、`summary+raw` 分层。

### B. 摘要遗漏时回原文

**输入**：已选 summary、query、摘要中的实体/约束、摘要置信或覆盖字段。**输出**：同一 `page_id` 的原文片段或邻页，带 `summary_gap` 和证据 span。

**触发与预算**：摘要未覆盖 query 关键实体、存在否定/日期/数值冲突、答案需要原句核验时触发；每页最多一次回原文，最多 8 KB，仍不足则进入 `CLARIFY/REVIEW`。

**风险**：回读扩大上下文并触发“lost in the middle”；摘要本身被错误当成事实；重复回读造成 page churn。

**测法**：构造摘要删掉日期、否定、条件、例外四类 needle；对照 summary-only、无条件 raw、gap-triggered raw。标注摘要召回、raw evidence recall、答案/工具参数正确率、额外 bytes 和回读率。

### C. 事件触发的实时 context

**输入**：事件流（用户修正、工具结果、文件变更、权限/schema 更新）、当前 dependency versions、phase。**输出**：受影响 block/page 的 invalidate、refresh 或 priority bump 事件；不相关 block 保持 residency。

**触发与预算**：仅在事件 dependency 与 block/page 依赖相交时触发；单事件最多刷新 N 个块、一次 working-set 重建，事件合并窗口固定为 100 ms（实验可设 0/100/500 ms）。

**风险**：事件丢失或乱序；过度失效造成抖动；旧事实未被淘汰；事件时间戳造成非确定 replay。

**测法**：回放同一事件序列，比较全量重建、事件局部刷新、固定 TTL。报告 stale read、refresh bytes、page churn、fault latency、旧事实使用率和最终正确率；检查 revision guard 阻止过期执行。

### D. 反证与旧事实 vs 当前事实

**输入**：当前候选证据、历史页、依赖版本、时间窗口、互相冲突的实体/约束。**输出**：成对或成组 evidence bundle：`current`、`historical`、`contradiction`、`unresolved`，并要求读取原文定位。

**触发与预算**：检测否定词、数值/日期不一致、同一实体多版本或用户明确“现在/之前”时触发；最多保留 2 个当前候选和 2 个旧事实候选，冲突页优先于相似但无反证的页。

**风险**：把旧事实当当前事实；把真正更新误判冲突；为追求完整而超过上下文预算。

**测法**：构造 current-only、historical-only、true-conflict、ambiguous 四组；比较不带反证、只取最新、双证据校验。指标为 current-fact accuracy、冲突识别 F1、澄清率、错误工具调用率和读取成本。

### E. 决策相关最小上下文

**输入**：任务约束、候选工具/计划、已选页摘要和 dependency graph。**输出**：满足决策所需的最小 block 集（pinned 约束 + 当前候选证据 + 必要导航），其余块留在 cold。

**触发与预算**：每次 Jev 决策前重算；硬上限 `max_working`、bytes、页数，使用 hysteresis 避免边界抖动。runtime 可自由替换上下文，不需要复用跨请求 prefix。

**风险**：最小化过早丢掉反证或后续步骤所需背景；resident 命中率上升但 needle 漏失；阶段切换导致 thrashing。

**测法**：与全量上下文、固定最近 K、当前 `ContextResidencyManager` 对照；控制同一摘要和检索器。报告 working bytes、needle evidence recall、position-stratified recall（首/中/尾）、fault、答案正确率和切换次数。

### F. 双上下文校验

**输入**：`decision_context`（短、结构化、可供 Jev 选择）与 `evidence_context`（原文 span、来源、revision、反证）。**输出**：校验结果 `supported/unsupported/conflict/stale`；unsupported/conflict 只能触发回读、澄清或停止，不能直接执行工具。

**触发与预算**：每个高风险工具调用、摘要命中但缺原文、revision 变化时触发；每次最多 2 个 evidence bundle，原文预算 16 KB。

**风险**：双上下文不一致；校验模型把相似句误判支持；增加一次决策延迟；不能把 Jev 概率当校准置信度。

**测法**：屏蔽/交换 evidence span，使用已标注支持/反驳/无关三类；报告 unsupported execution、conflict recall、stale rejection、答案正确率、额外调用和延迟。

## 3. 分阶段消融路线

### 阶段 P0：确定性记忆基线（下一轮优先）

冻结 page 内容、summary、revision、query、seed 和 `max_working/max_pages/max_bytes`。运行当前 lexical `PagedMemoryIndex + TwoStageMemorySelector + ContextResidencyManager`，加入 needle 位置（首/中/尾）、摘要遗漏和 stale/revision 四类合成样本。只使用 proxy/oracle 选择器时单列结果，不声称 Jev 质量。

**必须输出**：page hit、needle evidence recall、答案正确率三列；fault、read bytes、P50/P95、context churn、stale rejection；每个 trace 保存 query、candidate IDs、selected IDs、revision 和 evidence spans。

### 阶段 P1：一次只加入一个机制

顺序为：A（RRF）→ B（摘要回原文）→ E（最小上下文）→ D（反证）→ F（双上下文）→ C（事件触发）。每个机制与 P0 共享相同页集、答案金标准、预算和随机种子；额外成本必须单列。任何机制若提高 page hit 但降低 needle recall 或答案正确率，不得标记为成功。

### 阶段 P2：组合与压力测试

测试 `A+B`、`A+E`、`B+D+F`、`C+E` 四个组合，加入长序列事件、phase change、权限拒绝、schema drift、重复 stale 和中间位置 needle。使用 bootstrap 置信区间或至少报告每个 episode 的配对差异；不要把少量真实 Jev 调用与 proxy 混合平均。

### 阶段 P3：实时工作负载与 paging 交互

在 20–100 步固定事件轨迹上比较全量重建、事件局部刷新、固定 TTL；再测 working-set K=4/8/16、页大小 2/4/8、summary/raw 比例。若上下文可任意替换，报告每步重建成本和实际 page-in stall，而不是假设 prefix reuse 带来的收益。

## 4. 指标与判定

- **Paging hit**：目标 `page_id` 被 materialize/read；仅衡量索引命中。
- **Needle evidence recall**：金标准证据 span 被读取，并可由 trace 定位；摘要命中但未读取原文不计 full recall。
- **Answer correctness**：独立 deterministic checker、工具结果或人工盲评；不能用 Jev confidence 代替。
- **成本**：request/read bytes、page-in IO、决策调用数、wall-clock P50/P95、context churn、stale/permission rejection、错误副作用。
- **位置鲁棒性**：按 needle 在 resident 输入中的首/中/尾分桶，报告最差分桶与均值；参考 Lost in the Middle 的位置控制实验。
- **上下文可替换性**：记录每步构建完整 context 的成本；不声明服务端没有 KV cache，也不把无 cache 作为实验事实。

建议下一次具体实验：固定 12 页、每页 1 个 summary + 8 KB raw，构造 48 episodes（4 needle 位置 × 3 摘要遗漏 × 4 状态），比较 P0、A、B、E、B+F；`max_pages=2/4`、`max_read_bytes=8/16 KB`，seed=7/19，先跑 proxy/oracle，再选 8–12 个 episode 复核真实 Jev。成功门槛：needle recall 与答案正确率不下降，P95 page stall 或 read bytes 至少一项改善；否则保留为诊断结果。

## 5. 引用与边界

- Cormack, Clarke, Buettcher. “Reciprocal Rank Fusion outperforms Condorcet and Individual Rank Learning Methods”, SIGIR 2009. [DOI](https://doi.org/10.1145/1571941.1572114)
- Jiang et al. “Active Retrieval Augmented Generation”, EMNLP 2023. [ACL Anthology](https://aclanthology.org/2023.emnlp-main.495/)。FLARE 展示了在生成过程中主动预测后续内容并按需要检索的设计；本文只借鉴事件/阶段触发的测量方式，不声称相同机制。
- Liu et al. “Lost in the Middle: How Language Models Use Long Contexts”, TACL 2024. [PDF](https://aclweb.org/anthology/2024.tacl-1.9.pdf)。
- Sarthi et al. “RAPTOR: Recursive Abstractive Processing for Tree-Organized Retrieval”, ICLR 2024. [论文页面](https://proceedings.iclr.cc/paper_files/paper/2024/hash/8a2acd174940dbca361a6398a4f9df91-Abstract-Conference.html)。递归摘要树支持多层抽象检索；本文仅将其作为摘要/原文层级的相关先例，不把摘要质量当证据召回。

上述来源用于支持相关研究事实；方案、阈值、数据集和结果均为本仓库待验证计划。
