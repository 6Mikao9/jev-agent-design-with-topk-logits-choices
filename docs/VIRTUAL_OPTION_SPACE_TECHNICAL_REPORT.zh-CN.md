# Virtual Option Space 技术报告

> 状态：研究设计与原型边界（2026-09-24）。仓库已有一个同步、有限的 `VirtualOptionManager` 原型，支持稳定 ID、基础 page-in/page-out、LRU、revision/stale 和 refine；自动异步 prefetch、学习型 replacement 和完整 fault loop 仍未实现。

## 摘要与范围

Jev 是有限选项决策接口，而开放世界 agent 的逻辑候选可以远大于一次调用可承受的上下文、schema 和延迟预算。Virtual Option Space（虚拟选项空间）把逻辑候选与当前可见候选分开：选项可以 resident、non-resident 或 invalid，并在决策轮次之间保持稳定身份。Jev 只在有限 resident set 上决策；当它选择 `NEXT_PAGE`、`EXPAND` 或显式缺失出口时，runtime 进入 OptionFault，解析并 materialize 下一页，再继续一次有界决策。

这是一种可验证的系统组合候选。虚拟内存、working set、LRU、RAG、层级路由、工具调用等都有先例；本报告的贡献候选是把它们组合成面向有限选项决策器的运行时接口，并以页表、版本 guard、异构空间和可回放实验验证收益。

## 1. 形式化定义

在时间 `t`，令：

- `V_t`：逻辑虚拟选项全集，可由注册表、检索器、工具输出、环境观察或用户输入动态产生；
- `R_t ⊆ V_t`：当前 resident option 集合，满足 `|R_t| ≤ K`、字节和权限预算；
- `M_t : V_t → {resident, non_resident, invalid}`：页表状态映射；
- `J(s_t,R_t)`：Jev 在状态摘要 `s_t` 与 resident 候选上的分布；
- `a_t ∈ R_t ∪ C`：选项或控制动作，`C` 至少包含 `NONE/CLARIFY/REVIEW/STOP` 和分页动作。

正常决策为 `a_t = argmax J(s_t,R_t)`。当动作是分页控制项，runtime 执行 `R_{t+1}=PageIn(V_t, selector, K)`；当候选已失效或权限不满足时，动作转为拒绝、澄清或复核。系统目标是允许 `|V_t| ≫ K`，同时保持有限上下文、可追溯身份和有界副作用。

## 2. Runtime 状态机与 OptionFault

建议状态：`Observe → Index → Resident → Decide → Execute`，另有 `OptionFault`、`Validate`、`Evict`、`Prefetch`、`Stale`、`Review` 和 `Stop`。`OptionFault` 不是工具失败，而是当前 resident set 不足以完成决策的可恢复控制流：

1. 记录 `node_signature`、候选分布、触发原因和页表 revision；
2. 检查 fault 类型（`NEXT_PAGE`、`SEARCH`、`EXPAND_K`、缺失候选、stale）；
3. 验证权限、schema、来源和预算；
4. 计算 page-in 候选并 materialize；必要时 page-out；
5. 递增 revision，重新生成有界 `R_{t+1}`；
6. 再次调用 Jev，最多达到 fault/round 上限，超限进入 `CLARIFY/REVIEW/STOP`。

任何副作用工具必须在 `Validate` 完成后执行；fault 循环不可隐式无限重试。

## 3. Page table、stable virtual ID 与 revision

每个虚拟选项至少包含：

```text
virtual_option_id, kind, locator, schema_version, source,
state, page_id, permission_tag, revision, expires_at, cost
```

`virtual_option_id` 是稳定逻辑身份（例：`tool://repo/search`、`memory://block/42`），不等于当前显示文本。选项可经历 non-resident → resident → evicted → resident，ID 不变。页表记录 `page_id`、摘要、物理定位、生成器、权限和当前 revision；执行时通过 ID 解析最新对象，并拒绝 revision 不匹配的引用。动态页和检索结果必须设置 TTL 或父查询 revision；源删除、schema 改变、权限变化、任务状态变化都会标记 `invalid/stale`。

当前代码已有 `VirtualOptionManager` 的有限实现，以及页表预算、稳定 ID 和 revision/stale 校验；它还不是持久化 page table 服务，也没有异步调度或跨空间 resolver。

## 4. Working set、replacement 与页大小

定义最近有用候选的 working set：

`W_t = {o | access(o,t-h:t) 或 semantic_relevance(o,s_t) ≥ θ}`。

一个实用 resident 目标是 `R_t = W_t ∪ task_specific ∪ navigation`，受 `K`、字节、权限和每类空间配额约束。候选优先级可写为：

`score(o)=α·p_jev(o)+β·recency(o)+γ·frequency(o)+δ·relevance(o)-λ·materialization_cost(o)`。

实验比较：页级 LRU、LFU、LRU-K、按语义相似度的 semantic replacement、固定保留导航项，以及混合分数。报告 page fault rate、命中后决策质量、上下文字节、延迟、page-in 成本和错误副作用。页大小比较小页（2/4/8 个选项）、按 schema 聚簇页、按任务阶段聚簇页；不能只报告缓存命中率。

## 5. Prefetch 与概率阈值

Jev 分布中若 `P(NEXT_PAGE|s_t)>τ_page`，可异步准备下一页；若某页 `P(page_i|s_t)>τ_i` 或序列模型给出高置信后继，也可预取。`τ` 应在验证集校准，并通过成本约束选择：

`prefetch` 仅在 `p·benefit - (1-p)·cost > 0` 时启用。预取对象必须是无副作用的索引、摘要或只读句柄；真正工具执行仍需下一轮明确选择和完整 guard。任何上下文、schema、权限或依赖 revision 变化都会使预取标 stale 并丢弃。实验需比较无预取、固定下一页、阈值预取和 top-2 预取的净 wall-clock、接受率、stale 丢弃率、额外 IO 与 fault rate。

## 6. 异构 Virtual Option Space

同一 runtime 可维护独立配额和 schema 的空间：

|空间|选项示例|特殊 guard|
|---|---|---|
|ToolSpace|工具、参数模板、扩展页|权限、schema、幂等性、审计|
|MemorySpace|页表摘要、原文 block、错误摘要|来源、敏感级别、revision、字节上限|
|FileSpace|文件、目录、搜索结果|工作区根、路径规范化、存在性、mtime|
|EntitySpace|实体、关系、社区摘要|来源置信、冲突和删除状态|
|PlanSpace|子任务、恢复边、编译边|依赖、状态版本、回滚|
|PredictionSpace|参数/答案 proposal|schema、拒绝出口、stale|
|ControlSpace|`NEXT_PAGE`、`SEARCH`、`CLARIFY`、`STOP`|始终保留、不可产生副作用|

空间之间不能因候选数量混合而突破各自预算。当前仓库已有 Tool/Memory/Prediction/Control 的有限分区、PagedMemoryIndex、TwoStageMemorySelector 和 state trace；File/Entity/Plan 的统一虚拟化仍是研究项。

## 7. 与相邻技术的差别和边界

- **Hierarchical classification/routing**：通常先选静态类别再选叶节点；Virtual Option Space 允许动态生成页、跨轮 residency、replacement、prefetch、invalidation 和异构控制项，不要求树结构。若实现只有固定树和两次分类，应称 hierarchical routing，不应改名为 virtualization。
- **RAG/摘要树**：负责召回或压缩证据；本机制还定义可寻址 option、有限 resident 集、fault 控制流和执行前 guard。若只有 top-k 检索，没有 resident 状态或 page fault，属于 RAG。
- **OS virtual memory**：借鉴虚拟地址、页表、fault、working set 和 replacement 的语义，但选项不是字节地址，page-in 可由检索/生成器动态产生，错误代价是错误工具调用和上下文污染；不能直接套用 OS 的命中率或一致性假设。
- **工具路由/函数调用**：选择工具和参数是 Virtual ToolSpace 的一种 workload；分页、稳定 ID、跨轮缓存和显式 fault 才是额外运行时层。

相关先例包括 [MemGPT](https://arxiv.org/abs/2310.08560)、[RAPTOR](https://arxiv.org/abs/2401.18059)、[GraphRAG](https://microsoft.github.io/graphrag/)、[Toolformer](https://arxiv.org/abs/2302.04761) 和 [Letta 文档](https://docs.letta.com/)。贡献应表述为可验证的系统组合，不作绝对首创声明。

## 8. 安全、权限、schema 与 stale guard

所有 page-in、prefetch 和 resolve 都执行：工作区/租户边界、最小权限、敏感字段脱敏、schema 版本匹配、来源与 TTL、路径规范化、资源/字节/调用次数预算。`virtual_option_id` 不能携带密钥或未经授权的远端路径。执行前重新解析 ID 并比较 revision；失败进入 `REVIEW` 或 `CLARIFY`，不得用旧 proposal 强行执行。日志记录候选排名、fault 原因、guard 结果和拒绝理由，但不写入密钥、模型权重或敏感原文。

## 9. 实现路线与当前边界

**P0 原型**：把现有 `OptionSpace`、`OptionSpaceRegistry`、`PagedMemoryIndex`、`TwoStageMemorySelector` 和 `DecisionTraceGraph` 接到统一 `VirtualOptionManager` 接口；当前已实现稳定 ID、页表 revision、显式 `OptionFault`/`RefineFault`、同步 page-in/page-out、LRU 和基础 refine，尚未接入完整 fault loop。

**P1 机制**：实现 LRU/LFU/semantic replacement、按空间配额、页级指标、概率校准与阈值 prefetch；加入动态文件/实体页和失效通知。

### 9.1 Speculative Option-Space Transitions（研究计划）

这是 Virtual Option Space 的性能优化，而不是新的决策语义。runtime 可以在等待 Jev 返回时，用小模型、历史转移频率、局部性和当前阶段预测下一步可能的 `PAGE` 或 `REFINE`，把只读索引、摘要、schema 和候选草案放入独立的 **Speculation Space**。当前可提交的 `Resident Space` 不得看到这些草案；只有 Jev 明确提交了对应的父级转移，并通过 state/schema/permission/revision guard 后，草案才能 promote。猜错、状态变化或权限变化时直接丢弃，不能造成工具副作用。

统一记法为 `τ:(O_t,s_t)→(O_{t+1},s_{t+1})`。预测器只 materialize `\hat τ_1…\hat τ_B`，命中条件是 Jev 的真实转移属于预测集合。Jev 的返回不能单独视为验证结果；promote 前仍要重新检查状态、schema、权限和 revision。`PAGE` 预取通常比 `REFINE` 子树便宜，应先只做 top-1/top-2 PAGE；radix/trie 只有在工具名、字段名或路径确实共享前缀时才使用，平坦页不强行树化。首版只允许 depth=1；多分支、深度大于 1 和 learned governor 都要在单页预取有正收益后再做。

预取是否值得由净收益决定，而不是由概率阈值单独决定：

`EV(b)=P(hit)×saved_latency−speculation_cost`。

预算至少限制 speculative nodes、只读字节、helper/IO 调用和并发任务；取消、资源争用、淘汰和 stale 丢弃也要计入成本。候选分数不能未经校准就线性相加 `P_small`、上次 Jev 分布和局部性；首版先做单一排序基线，之后在验证集校准融合。首轮评估比较关闭、top-1、top-2 和固定下一页，报告 `PrefetchHitRate`、`UsefulPrefetchRatio`、page stall、`hidden_latency=min(准备耗时,Jev等待窗口)`、浪费比、额外 IO、stale 丢弃率和任务成功率。不能把“命中预取”直接写成端到端加速，也不能把该机制表述为首次 speculative execution；相关工作已有 token、检索和工具预取先例，本项目只验证它在 PAGE/REFINE 虚拟决策空间中的调度与一致性。

**P2 评测**：接入真实 Jev 与 proxy/oracle 对照，提供回放、权限拒绝、schema drift、stale、重复 fault 和工具副作用隔离。

当前代码已有 OptionSpace 的有限页、PagedMemoryIndex、TwoStageMemorySelector、state trace 和 `VirtualOptionManager` 基础原型；异步 prefetch、Speculative Space、学习型 replacement、异构统一 resolver、持久化页表和完整 scaling benchmark 仍待实现。文档中的目标、伪代码和设计不能写成已完成能力。

## 10. 可运行实验矩阵与消融

固定任务、页内容、摘要器、候选 ID、随机种子、模型和预算；每格至少重复多次并报告均值/置信区间。

|因素|对照|指标|
|---|---|---|
|resident K|4/8/16/32|任务成功率、fault rate、延迟、上下文字节|
|replacement|LRU、LFU、semantic、混合|命中、page-in 成本、阶段切换损失|
|prefetch|关闭、固定下一页、阈值、top-2|净 wall-clock、接受率、stale 丢弃|
|页布局|按类型、按阶段、随机|关键候选召回、fault 次数|
|决策接口|Jev、proxy、oracle|质量、校准、调用成本|
|guard|完整、去 revision、去权限、去 schema|错误副作用、过期执行率|
|基线|全量候选、hierarchical routing、单阶段 RAG、固定 top-k|质量-成本曲线|

任务覆盖工具目录、长记忆 needle、动态文件、实体冲突和计划恢复。必须记录候选粗选漏失、`NONE/CLARIFY/STOP` 率、读取 precision/recall、重复错误率、stale 丢弃率、权限拒绝率、side-effect attempt、端到端与分阶段延迟。无真实 Jev 的结果单列为 proxy/oracle。

## 11. 失败模式

关键选项未进入粗选页；摘要遗漏矛盾；概率未校准导致错误 prefetch；page churn 或 working-set phase change；页表 revision 漂移；权限/schema 拒绝；预算耗尽或 fault 循环；动态结果消失；工具副作用在 guard 前启动；稳定 ID 复用导致错误解析；真实 Jev 与 proxy 行为差异。每类失败都应保留可回放 trace、输入版本和恢复动作。

## 12. 论文贡献候选

1. 面向有限选项决策器的稳定 ID、resident/non-resident 与 OptionFault 接口，并证明在 `|V|≫K` 时仍可完成任务。
2. working-set 与 replacement/prefetch 策略的系统比较，明确语义局部性是否优于 LRU/LFU。
3. 异构 Tool/Memory/File/Entity/Plan/Prediction/Control 空间的统一 guard、revision 和审计协议。
4. 在真实 Jev、proxy、oracle 和 hierarchical/RAG 基线上的可复现实验矩阵。

这些是待验证贡献候选；只有完成公开配置、消融和失败分析后，才应写入论文结论。

## 当前项目定位（收敛版，2026-09-24）

本报告应与 [Decision-Preserving Progressive Refinement](DECISION_PRESERVING_REFINEMENT.zh-CN.md) 一起阅读：项目面向非生成式 Decision Model 的 Jev-native runtime。Virtual Option Space 负责覆盖范围，progressive refinement 负责候选分辨率；Jev 始终做最终选择。Top-k helper、fallback、confidence cascade、speculative decoding、FUDGE/GeDi、reward-guided decoding 与 Pydantic AI Jev fallback 均有近邻，不能作为单点新颖性。本文的贡献候选只是两轴 runtime 组合及其一致性/恢复实验，仍待验证。

当前代码已实现 OptionSpace、PagedMemoryIndex、TwoStageMemorySelector、FastLogitsHelper、Agent/orchestrator、trace，以及同步 `VirtualOptionManager` 的基础 page-in/page-out、LRU、revision/stale、OptionFault/RefineFault 和 refine；异步 prefetch、完整 replacement、跨空间 resolver 和 scaling benchmark 尚未实现。


## 统一运行时定位（DecisionModel 与双重虚拟化）

系统抽象为可替换的 `DecisionModel: D(s,O) -> P(O)` backend；Jev 是当前原型 backend，未来可替换 Mock/Oracle 或其他 typed decision backend。Open World 通过 Virtual Option Space 管理 resident options，通过 Virtual Context Space 管理 resident context blocks，随后驱动 Decision Model 与 state transition。PAGE/EXPAND 扩大候选覆盖，REFINE 降低候选粒度，ContextFault 触发二阶段 context paging，REVISION/INVALIDATE 保持一致性。

Context 分为 Pinned、Working、Cold 三层。Context block 元数据包括 `block_id/summary/raw_ref/revision/dependencies/last_access/access_count/utility/type/size/pinned`。按类型 aging：Pinned 不老化，任务状态慢老化，观察与 transient retrieval 快老化；utility aging 根据实际决策用途更新。采用 hysteresis、minimum residency、working-set history 与 phase-aware anti-thrashing。memory/RAG 在此是 context residency policy，而非普通“给模型找资料”。runtime 不依赖跨请求 prefix/KV reuse，允许 aggressive context mutation；这不等于声称 Jev backend 完全没有 KV cache。贡献边界是 Virtual Option + Context virtualization、decision-preserving refinement、fault/recovery/consistency 的组合，不声称各组件单点新颖。
