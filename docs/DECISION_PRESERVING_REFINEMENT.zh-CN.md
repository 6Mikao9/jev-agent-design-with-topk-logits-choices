# Decision-Preserving Progressive Refinement（决策保持的渐进式细化）

> 研究定位（2026-09-24）：本项目是面向非生成式 Decision Model 的 Jev-native agent runtime。核心问题不是让另一个生成模型接管，而是在候选缺失或粒度不足时，改变 OptionSpace 的覆盖范围或分辨率，使 Jev 始终做最终选择。以下是待验证的系统假设，不是已证实的新颖性声明。

## 1. 形式化对象

在状态 `s_t` 下，开放世界产生逻辑选项空间 `O_t^(0)`。runtime 将其物化为有限 resident space：

`O_t^(0) --R(s_t,·)--> O_t^(1) --Jev(s_t,·)--> a_t --State transition--> s_(t+1)`

`O_t^(0)` 可以包含工具、字段、路径、SQL、JSON、短文本片段及控制动作；`R` 是保持身份、权限、revision 与预算的 refinement operator。典型粒度链为：完整 candidate → field → fragment → token。Jev 在每一级都对当前有限集合做最终选择；helper logits 只提出 refinement proposal，不能替换 Jev 或成为主模型。

### 1.1 REFINE 的正式定义

对当前粗粒度选项 `o` 和状态 `s`，定义：

`Refine(o, s) -> O'`

其中 `O'` 是由 `o` 的语义、schema、依赖和当前状态共同构造出的更细粒度 `OptionSpace`，而不是一个单独的 token 或答案。`O'` 可以包含字段值、参数组合、路径片段或下一层控制动作；它必须保留 `parent_id=o.id`、输入 `revision`、依赖签名和预算边界。只有在 `O'` 通过 schema、权限和状态一致性检查后，runtime 才把它 materialize 为 resident options 并再次调用 Decision Model。

PAGE/EXPAND 与 REFINE 是两个正交方向：PAGE/EXPAND 在同一粒度上横向扩大覆盖范围，令候选集合包含更多同级选项；REFINE 沿父子关系纵向增加表达分辨率，令一个粗选项展开成可执行的细粒度空间。前者回答“还缺哪些候选”，后者回答“这个候选还不够具体”。二者都受 resident、字节、调用次数和风险预算约束。

## 2. 两个正交轴

- **PAGE/EXPAND：增加覆盖范围。** 在同一粒度上查看更多同级候选：page-in、`EXPAND_K`、检索、`REPROPOSE`。它解决 coverage 不足。
- **REFINE：降低候选粒度。** 将一个粗候选拆成字段、片段或 token 候选，再由 Jev 逐级决定。它解决已有候选太粗、无法表达可行动作。

两轴可组合：先 `EXPAND_K` 找到更多完整工具，再对选中的工具 `REFINE` 参数字段；也可先细化 query，再 `LOOKUP` 扩大结果集。

## 3. Fault 与恢复状态机

覆盖不足产生 **OptionFault**；粒度不足产生 **RefineFault**。两者都必须带稳定 `virtual_option_id`、父候选、来源、`revision`、预算和 stale guard。建议恢复状态：

`DECIDE → EXPAND_K | BACKTRACK | REPROPOSE | LOOKUP | CLARIFY | STOP | FINISH`

所有恢复动作回到有限候选集合，再调用 Jev。执行副作用前必须校验 schema、权限、revision 和状态签名；stale 引用直接丢弃。`BACKTRACK` 回到最近仍有效的粗节点，`REPROPOSE` 重新产生同粒度候选，`LOOKUP` 从虚拟空间取回非 resident 项，`CLARIFY` 将不可判定部分交给用户，`STOP` 保持安全终止，`FINISH` 仅在候选和状态一致时提交。

### 3.1 父子、版本与预算语义

`Refine(o,s)` 产生的每个子选项都带有 `parent_id`、`page_id`、`revision` 和依赖集合。父选项可以暂时保留作回退标记，但在子空间成功 materialize 后不得与其子选项同时作为可提交动作，避免重复选择粗节点；父节点失效或状态签名改变时，其后代一并标记 stale。新的 revision 只允许替换同一逻辑对象的旧版本，不能静默改变稳定 ID 的含义。

每次 PAGE/EXPAND 或 REFINE 都消耗显式预算：resident slots、page bytes、Decision Model calls、refinement depth 和 side-effect risk。预算耗尽时必须返回 `RefineFault`/`OptionFault`、`CLARIFY` 或 `STOP`，不能通过无限递归扩展逃逸。当前代码实现是同步原型，已覆盖基础父子页、revision/stale 和 resident 上限；完整的统一 fault loop、异步 materialization 与学习型预算策略仍属于后续工作。

## 4. 与近邻工作的边界

Top-k helper、fallback、confidence cascade、speculative decoding、FUDGE/GeDi、reward-guided decoding，以及 Pydantic AI 的 Jev fallback 都有近邻或先例，不能声称这些单点机制新颖。待验证的贡献候选是“decision-space virtualization + progressive refinement 的 Jev-native runtime 组合”：主模型不切换，helper 不接管，覆盖和分辨率作为独立 runtime 操作，并由一致性 guard 与恢复状态机连接。

## 5. 实验主线

逻辑空间规模：`10/100/1K/10K/100K`；resident `K=8/16/32`。先故意删除正确 coarse candidate，再比较：`argmax`、`REPROPOSE`、full LLM handoff、helper top1、helper topK+Jev、`+EXPAND_K`、`+BACKTRACK/LOOKUP/CLARIFY`。主要指标：

- `RecoveryRate`：正确 coarse 候选缺失时恢复成功率；
- `refine_success`：在 coarse option 已选中但粒度不足时，`Refine(o,s)` 是否构造出包含正确细粒度决策的 `O'`；
- `parent_child_consistency`：子选项的父 ID、revision、依赖和状态签名是否可追溯且一致；
- `budget_bound`：恢复过程中 resident、深度、调用和字节上限是否始终未被突破；
- candidate coverage、总成本、延迟、state errors、side effects；
- 分别报告 helper proposal quality 与 Jev final decision quality。

BFCL coverage 只表示正确候选是否可用，不等于 Jev accuracy。必须报告真实 Jev、proxy/oracle、网络往返和失败恢复的边界。

## 6. 适用范围与实现边界

优先 workload：短字段、SQL、路径、JSON、工具参数、资源名和短澄清；长篇自然语言逐 token 细化只作为高成本实验。当前已有 `OptionSpace`、`PagedMemoryIndex`、`TwoStageMemorySelector`、`FastLogitsHelper`、Agent/orchestrator、trace，以及同步 `VirtualOptionManager` 的稳定 ID、基础 page-in/page-out、LRU、revision/stale、`OptionFault/RefineFault` 和 refine 原型；异步 prefetch、完整 replacement policy、跨空间 resolver 和真实 backend scaling 尚未实现；同步 VirtualOptionManager 已有机制基线。本文不包含密钥、权重或远端路径。



## 统一运行时定位（DecisionModel 与双重虚拟化）

系统抽象为可替换的 `DecisionModel: D(s,O) -> P(O)` backend；Jev 是当前原型 backend，未来可替换 Mock/Oracle 或其他 typed decision backend。Open World 通过 Virtual Option Space 管理 resident options，通过 Virtual Context Space 管理 resident context blocks，随后驱动 Decision Model 与 state transition。PAGE/EXPAND 扩大候选覆盖，REFINE 降低候选粒度，ContextFault 触发二阶段 context paging，REVISION/INVALIDATE 保持一致性。

Context 分为 Pinned、Working、Cold 三层。Context block 元数据包括 `block_id/summary/raw_ref/revision/dependencies/last_access/access_count/utility/type/size/pinned`。按类型 aging：Pinned 不老化，任务状态慢老化，观察与 transient retrieval 快老化；utility aging 根据实际决策用途更新。采用 hysteresis、minimum residency、working-set history 与 phase-aware anti-thrashing。memory/RAG 在此是 context residency policy，而非普通“给模型找资料”。runtime 不依赖跨请求 prefix/KV reuse，允许 aggressive context mutation；这不等于声称 Jev backend 完全没有 KV cache。贡献边界是 Virtual Option + Context virtualization、decision-preserving refinement、fault/recovery/consistency 的组合，不声称各组件单点新颖。

