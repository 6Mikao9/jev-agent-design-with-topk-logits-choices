# Decision-Preserving Progressive Refinement（决策保持的渐进式细化）

> 研究定位（2026-09-24）：本项目是面向非生成式 Decision Model 的 Jev-native agent runtime。核心问题不是让另一个生成模型接管，而是在候选缺失或粒度不足时，改变 OptionSpace 的覆盖范围或分辨率，使 Jev 始终做最终选择。以下是待验证的系统假设，不是已证实的新颖性声明。

## 1. 形式化对象

在状态 `s_t` 下，开放世界产生逻辑选项空间 `O_t^(0)`。runtime 将其物化为有限 resident space：

`O_t^(0) --R(s_t,·)--> O_t^(1) --Jev(s_t,·)--> a_t --State transition--> s_(t+1)`

`O_t^(0)` 可以包含工具、字段、路径、SQL、JSON、短文本片段及控制动作；`R` 是保持身份、权限、revision 与预算的 refinement operator。典型粒度链为：完整 candidate → field → fragment → token。Jev 在每一级都对当前有限集合做最终选择；helper logits 只提出 refinement proposal，不能替换 Jev 或成为主模型。

## 2. 两个正交轴

- **PAGE/EXPAND：增加覆盖范围。** 在同一粒度上查看更多同级候选：page-in、`EXPAND_K`、检索、`REPROPOSE`。它解决 coverage 不足。
- **REFINE：降低候选粒度。** 将一个粗候选拆成字段、片段或 token 候选，再由 Jev 逐级决定。它解决已有候选太粗、无法表达可行动作。

两轴可组合：先 `EXPAND_K` 找到更多完整工具，再对选中的工具 `REFINE` 参数字段；也可先细化 query，再 `LOOKUP` 扩大结果集。

## 3. Fault 与恢复状态机

覆盖不足产生 **OptionFault**；粒度不足产生 **RefineFault**。两者都必须带稳定 `virtual_option_id`、父候选、来源、`revision`、预算和 stale guard。建议恢复状态：

`DECIDE → EXPAND_K | BACKTRACK | REPROPOSE | LOOKUP | CLARIFY | STOP | FINISH`

所有恢复动作回到有限候选集合，再调用 Jev。执行副作用前必须校验 schema、权限、revision 和状态签名；stale 引用直接丢弃。`BACKTRACK` 回到最近仍有效的粗节点，`REPROPOSE` 重新产生同粒度候选，`LOOKUP` 从虚拟空间取回非 resident 项，`CLARIFY` 将不可判定部分交给用户，`STOP` 保持安全终止，`FINISH` 仅在候选和状态一致时提交。

## 4. 与近邻工作的边界

Top-k helper、fallback、confidence cascade、speculative decoding、FUDGE/GeDi、reward-guided decoding，以及 Pydantic AI 的 Jev fallback 都有近邻或先例，不能声称这些单点机制新颖。待验证的贡献候选是“decision-space virtualization + progressive refinement 的 Jev-native runtime 组合”：主模型不切换，helper 不接管，覆盖和分辨率作为独立 runtime 操作，并由一致性 guard 与恢复状态机连接。

## 5. 实验主线

逻辑空间规模：`10/100/1K/10K/100K`；resident `K=8/16/32`。先故意删除正确 coarse candidate，再比较：`argmax`、`REPROPOSE`、full LLM handoff、helper top1、helper topK+Jev、`+EXPAND_K`、`+BACKTRACK/LOOKUP/CLARIFY`。主要指标：

- `RecoveryRate`：正确 coarse 候选缺失时恢复成功率；
- candidate coverage、总成本、延迟、state errors、side effects；
- 分别报告 helper proposal quality 与 Jev final decision quality。

BFCL coverage 只表示正确候选是否可用，不等于 Jev accuracy。必须报告真实 Jev、proxy/oracle、网络往返和失败恢复的边界。

## 6. 适用范围与实现边界

优先 workload：短字段、SQL、路径、JSON、工具参数、资源名和短澄清；长篇自然语言逐 token 细化只作为高成本实验。当前已有 `OptionSpace`、`PagedMemoryIndex`、`TwoStageMemorySelector`、`FastLogitsHelper`、Agent/orchestrator、trace，以及同步 `VirtualOptionManager` 的稳定 ID、基础 page-in/page-out、LRU、revision/stale、`OptionFault/RefineFault` 和 refine 原型；异步 prefetch、完整 replacement policy、跨空间 resolver 和 scaling benchmark 尚未实现。本文不包含密钥、权重或远端路径。


