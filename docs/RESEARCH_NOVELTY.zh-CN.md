# 新颖性审计：Jev 选项、分页记忆与状态机组合

> 审计日期：2026-09-24。本文是基于公开论文、官方文档和本仓库代码的检索记录，不构成专利或绝对新颖性意见。

## 检索结论

在检索范围内，未发现把“logits-only/有限选项的 Jev 决策器 + 两阶段摘要页表选择 + 超远 needle 检索 + 分区/翻页选项空间 + 带版本 guard 的错误状态机 + 并行 proposal”作为一个端到端系统公开描述的资料。这个“目前未发现完全相同的端到端组合”只是检索结果，不能宣称绝对首创；需要扩大数据库、专利和非英文资料检索，并以实验证据确认贡献。

检索中也未找到明确名为 Jev/JEv 的公开论文或标准 logits-only choice model；因此 Jev 的模型定义、概率校准和与通用分类器/函数调用模型的差异仍属本项目待验证主张。

## 公开技术对照

|资料（年份，链接）|已公开内容|与本仓库关系/边界|
|---|---|---|
|MemGPT: Towards LLMs as Operating Systems (2023/24) [[arXiv]](https://arxiv.org/abs/2310.08560)|把上下文视作虚拟内存，分层搬运、外部存储和中断控制。|覆盖 memory paging、控制流和长记忆；没有 Jev 概率排序、2 阶段页表选择或本仓库的选项空间隔离。|
|RAPTOR (2024) [[arXiv]](https://arxiv.org/abs/2401.18059)|递归嵌入、聚类、摘要形成多层树，查询时在不同抽象层检索。|覆盖摘要树/层级展开；本项目的“摘要页表→Jev 选数量→Jev 选 page_id”是不同接口，尚未证明优于 RAPTOR。|
|Microsoft GraphRAG (2024，持续更新) [[官方文档]](https://microsoft.github.io/graphrag/)|抽取实体关系、社区层级和多级摘要，支持 local/global 查询。|覆盖图和社区摘要；本仓库只实现确定性关键词预筛，关系边/图索引仍是设计项。|
|Needle-in-a-Haystack / RULER 系列（2023–25）[[RULER 线索]](https://openreview.net/pdf/6e476e748ca6dd590edc6d7b9f3ecc59e47dac70.pdf)|按上下文长度、位置、多针/多查询测长上下文检索。|支持本项目的超远捞针协议；Jev 作为有限候选决策器及页表漏失指标尚未被这些基准覆盖。|
|Toolformer (2023) [[arXiv]](https://arxiv.org/abs/2302.04761)|学习何时调用 API、选择工具和参数，并整合结果。|覆盖工具选择与参数生成；本项目强调独立 ToolSpace、显式分页、控制项、权限/schema/revision guard。|
|Letta 文档（2024–26）[[官方文档]](https://docs.letta.com/)|状态化 agent、长期记忆、可搜索历史和分页 API。|覆盖产品级状态记忆/分页；未见 Jev logits 排序、固定 2/4/8 候选梯度或错误边编译组合。|
|Speculative Diffusion Decoding (2024) [[arXiv]](https://arxiv.org/abs/2408.05636)|用离散扩散并行生成 draft 并验证，加速自回归解码。|覆盖并行 proposal 的一般先例；本项目 proposal 是工具选择瞬间的可拒绝候选，不能宣称新扩散算法。|
|DART (2026) [[arXiv]](https://arxiv.org/abs/2601.19278)|单次前向预测多个未来位置并构造 draft tree。|说明并行 logits/proposal 已是活跃方向；本项目应引用并比较，而非把并行本身当贡献。|

## 分层判断

|类别|本仓库对应内容|判断|
|---|---|---|
|已有技术|RAG/BM25/向量预筛、摘要树/社区摘要、外部记忆 paging、工具调用、speculative/diffusion draft、状态机/trace。|不能单独作为新颖性贡献。|
|已有技术的组合|页表摘要 + 层级展开；RAG 召回 + agent 选择；工具分页 + schema 校验；错误摘要 + 状态回放。|工程组合有价值，但需清晰基线和消融，避免把组件清单写成算法首创。|
|我们的具体设计|两阶段：摘要页表先由 Jev 排序，再选 `N∈{2,4,8}`，再选 page_id；Jev 无 KV 命中目标下的激进超远捞针；Tool/Memory/Prediction/Control/Trace 分区及翻页控制项；错误摘要键含 node/tool/schema/error 与 revision；guard 通过后才编译自动边。|最可能形成系统论文贡献的组合接口；目前只有原型与设计，尚无端到端结果。|
|尚未验证假设|Jev 概率比检索分数更适合最终选择；两阶段能降低读取字节且不损失关键事实；超远旧页召回有优势；2/4/8 和分页降低错误；错误边编译在 drift 下安全回退；并行 proposal 带来净延迟收益。|必须用真实 Jev、固定数据和回放实验验证。|

## 论文贡献候选与优先级

1. **P0：两阶段摘要页表 + Jev 概率排序/Top-N。** 与单阶段 RAG、固定 top-K、仅层级检索比较；报告 `recall@M`、`precision@K`、关键事实覆盖率、读取字节、分阶段/端到端延迟、校准误差和候选顺序稳定性。
2. **P0：无 KV 命中目标的超远捞针。** 做位置（头/中/尾）、噪声长度、多针、冲突实体、旧事实和摘要合并消融；报告粗选漏失率和噪声长度曲线。不要把 helper KV cache 成本指标写成 Jev 命中率。
3. **P1：选项空间分区/翻页/控制项。** 消融混合无限候选、无 `NONE/CLARIFY/STOP`、无分页、不同 2/4/8 梯度；测错误副作用、澄清率、调用次数和上下文污染。
4. **P1：状态机错误摘要与版本 guard。** 对比无错误记忆、无 schema/revision guard；注入 schema 漂移、依赖失效和 drift，测重复错误率、错误边误触发率、回退成功率。
5. **P2：并行 proposal。** 与串行预取及无 proposal 比较净 wall-clock、接受率、stale 丢弃率和副作用隔离；引用 SpecDiff/DART，贡献点应放在调度/验证而非扩散模型本身。

所有实验需固定页内容、摘要模型、候选 ID、随机种子和版本；proxy/oracle 结果必须单列，不能写成真实 Jev 能力。建议增加 BFCL/ToolSandbox 风格工具任务和公开 NIAH/RULER 任务，并发布可复现实验配置、失败案例及消融脚本。

## 仓库实现核对

已核对 `jev_agent.option_space`、`paged_memory`、`state_machine` 及三份设计文档：实现提供稳定 ID、分页/预算、revision-stale 校验、确定性关键词预筛、`DecisionTraceGraph` 和 `ErrorSummaryQueue` 的最小原型；未实现向量 RAG、递归摘要、真实 Jev、扩散 proposal 的端到端调度，也没有性能/质量结论。本文没有修改代码。

## 未能确认的点

- 未检索到可核验的 Jev/JEv 原始论文或公开 logits-only choice model 定义。
- 未能证明不存在同样组合的专利、闭源系统、非英文论文或近期未索引预印本。
- 未能从公开资料确认“Jev 无 KV 命中”是否已有同义术语；该表述应作为本项目操作性定义。
- 目前没有真实 Jev 运行、超远捞针结果或并行 proposal 净收益，因此所有性能命题仍是待验证。
