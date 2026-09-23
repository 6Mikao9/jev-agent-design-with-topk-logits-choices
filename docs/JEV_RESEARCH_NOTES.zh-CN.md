# JEV 研究笔记（中文）

本文汇总近期讨论，区分“当前仓库已有的边界实现”和仍待验证的研究假设。页表接口与候选分区的背景分别见 [JEV_MEMORY_PAGING.zh-CN.md](JEV_MEMORY_PAGING.zh-CN.md) 与 [OPTION_SPACES_STATE_MACHINE.zh-CN.md](OPTION_SPACES_STATE_MACHINE.zh-CN.md)。

## 两阶段 Jev 记忆

记忆读取先由关键词/BM25/向量等轻量索引预筛页摘要，再由 Jev 对摘要排序；第二次 Jev 选择读取数量 `N`，目前规划为 `N ∈ {2,4,8}`，并受候选数、页数、单页字节数、总字节数和请求大小硬上限约束。实现中的 `TwoStageMemorySelector` 已覆盖确定性预筛、分布校验、`NONE/CLARIFY/STOP`、revision/stale 校验和有界读取；这不等于已经验证 Jev 相比 RAG 的质量收益，也不声称已实现向量检索或真正的递归压缩。

## 选项空间与工具交互

候选分为 ToolSpace、MemorySpace、PredictionSpace 和 ControlSpace（诊断时可展开 TraceSpace）。每个空间独立计数，建议按 2/4/8 梯度扩展；超过上限进入翻页、搜索或控制动作，而不是把候选混成无限列表。工具第一页放常用工具、schema 默认值和最近成功参数；“使用默认/修改字段/查看历史/上一页/下一页/搜索工具”都是显式动作。历史参数只作候选，权限、schema 和审计仍在执行前检查，敏感参数、密钥及远端路径不进入摘要。

## 预测并行与状态机

工具被选中后，可以并行预取轻量参数预测、多个扩散 proposal，以及不产生副作用的工具 I/O 准备。预测结果必须经过 schema、权限、状态和 revision 校验；上下文或依赖变化时标记 stale。扩散 proposal 是待验证的 PredictionSpace 方案，不能写成已实现的 next-token 算法。

状态机以稳定节点签名、工具/参数边、版本和错误类组织回放。错误摘要在主链路外异步聚合，作为可选记忆候选；`DecisionTraceGraph` 与 `ErrorSummaryQueue` 已提供最小原型。自动编译决策边仍需足够回放、成功率阈值、drift 检测和人工复核，不能视为永久规则。

## 上下文分区与执行队列

上下文分为任务核心、明确读取的相关记忆、最近记忆、工具扩展、预测和错误/轨迹区，各区有独立字节和候选预算。88 轮执行队列依次覆盖 2/4/8 消融、两阶段记忆、并行预取与 stale 丢弃、工具默认值/分页、错误摘要、状态机回放、隔离 benchmark 和结果汇总。每轮记录质量、延迟、调用次数、上下文字节、错误副作用及是否使用真实 Jev；proxy/oracle 结果不能标成真实 Jev 能力。

Jev 不需要优化 KV cache 命中率；缓存可降低 helper forward 成本，但不应限制记忆读取策略。因此可以更激进地读取候选页，前提是仍遵守页数、字节、权限和版本上限，并单独报告 helper 计算成本。

## 超远捞针实验与评测消融

把 RAG 预筛、层级页表摘要和两阶段 Jev 组合起来做 needle-in-a-haystack 实验，验证深层/旧页中的单条关键事实能否在长噪声中被找回。这是待验证假设，不是当前实现结论。至少比较：全量上下文、单阶段 RAG、固定 top-K RAG、层级页表但无 Jev 精选、两阶段 Jev 页表；必要时增加仅关键词和仅 LRU 基线。

固定针的位置（开头/中部/末尾/多针）、噪声长度、实体冲突、页层级和随机种子，测量 `recall@M`、最终读取 `precision@K`、关键事实覆盖率、位置分桶召回率、噪声长度曲线、澄清/错误率、端到端及分阶段延迟、读取字节和调用预算。另测低频旧事实、摘要合并后的可追溯性、不同候选顺序下的稳定性，以及超过 8 候选时分页的边界。缓存命中率仅可作为辅助成本指标，不能作为系统目标或收益证明。

## 失败边界

需要明确记录：关键页未进入粗选池、摘要遗漏冲突、概率分布不校准、stale/revision 变化、权限拒绝、请求或读取预算耗尽、扩散乱码/重复、工具 schema 漂移，以及真实 Jev 与 proxy 的差异。任何未完成的实验都应标记为设计或待验证，不能把文档中的目标、伪代码或局部测试扩写成端到端结果。

## 定位收敛与实验主线（2026-09-24）

将项目表述为面向非生成式 Decision Model 的 Jev-native agent runtime：`Open world → Virtual Option Space → Resident Option Space → Jev decision → State transition`。PAGE/EXPAND 改变 coverage，REFINE 改变 resolution；helper logits 仅提出候选，Jev 保留最终控制权。Top-k helper、fallback、confidence cascade、speculative decoding、FUDGE/GeDi、reward-guided decoding、Pydantic AI Jev fallback 均有先例，不能单独 claim 新颖。

主实验：逻辑空间 10/100/1K/10K/100K，resident K=8/16/32；删除正确 coarse candidate 后比较 argmax、repropose、full LLM handoff、helper top1、helper topK+Jev、+EXPAND_K、+BACKTRACK/LOOKUP/CLARIFY。记录 RecoveryRate、coverage、cost、latency、state errors、side effects；BFCL coverage 只代表 candidate availability。当前实现边界仍是既有 OptionSpace、PagedMemoryIndex、TwoStageMemorySelector、FastLogitsHelper、Agent/orchestrator、trace；VirtualOptionManager、OptionFault/RefineFault 与基础 page-in/out/revision/refine 原型已实现并有机制基线；异步 prefetch、完整 replacement policy、统一 fault loop 与真实 Jev scaling 仍待实现。


## 统一运行时定位（DecisionModel 与双重虚拟化）

系统抽象为可替换的 `DecisionModel: D(s,O) -> P(O)` backend；Jev 是当前原型 backend，未来可替换 Mock/Oracle 或其他 typed decision backend。Open World 通过 Virtual Option Space 管理 resident options，通过 Virtual Context Space 管理 resident context blocks，随后驱动 Decision Model 与 state transition。PAGE/EXPAND 扩大候选覆盖，REFINE 降低候选粒度，ContextFault 触发二阶段 context paging，REVISION/INVALIDATE 保持一致性。

Context 分为 Pinned、Working、Cold 三层。Context block 元数据包括 `block_id/summary/raw_ref/revision/dependencies/last_access/access_count/utility/type/size/pinned`。按类型 aging：Pinned 不老化，任务状态慢老化，观察与 transient retrieval 快老化；utility aging 根据实际决策用途更新。采用 hysteresis、minimum residency、working-set history 与 phase-aware anti-thrashing。memory/RAG 在此是 context residency policy，而非普通“给模型找资料”。runtime 不依赖跨请求 prefix/KV reuse，允许 aggressive context mutation；这不等于声称 Jev backend 完全没有 KV cache。贡献边界是 Virtual Option + Context virtualization、decision-preserving refinement、fault/recovery/consistency 的组合，不声称各组件单点新颖。

