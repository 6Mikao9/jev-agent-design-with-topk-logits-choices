# Jev 选项空间、状态机和可展开记忆

本文把新增想法整理成可执行的系统设计和验证队列。Virtual Option Space 的形式化定义、OptionFault、页表和 replacement 边界见 [技术报告](VIRTUAL_OPTION_SPACE_TECHNICAL_REPORT.zh-CN.md)。核心原则是：Jev 每次只看到当前决策需要的一小组稳定选项；工具、记忆、扩散 proposal 和控制动作分开计数，不能把所有候选混成一个无限增长的列表。

## 1. 选项空间划分

每个空间都有自己的候选 ID、预算、来源和拒绝动作。Jev 可以选择空间内的选项，也可以选择 `NONE`、`CLARIFY`、`REVIEW` 或 `STOP`。

| 空间 | 内容 | 默认策略 |
|---|---|---|
| **ToolSpace** | 常用工具、工具扩展页、历史成功命令、参数 schema | 常用工具固定在前；其余工具按页注册，按使用频率和当前任务相关性排序 |
| **MemorySpace** | 页表摘要、相关记忆 block、最近记忆、错误摘要 | 两阶段 Jev 选择；原文只读取明确选中的页 |
| **PredictionSpace** | 扩散模型的完整答案/参数 proposal、多组采样参数 | Jev 选择工具的瞬间异步启动多个预测；结果必须经过 schema/状态校验 |
| **ControlSpace** | `EXPAND_K`、`REPROPOSE`、`LOOKUP`、`CLARIFY`、`REVIEW`、`STOP` | 始终保留少量控制项，避免候选不足时被迫猜测 |
| **TraceSpace** | 当前节点、边、失败记录、版本和来源 | 默认只放摘要；需要诊断时才展开详细 trace |

建议每个空间使用 **2/4/8** 的候选梯度：先给 2 个，无法决定时扩到 4 个，再扩到 8 个；超过 8 个时进入分页或先做摘要筛选。这个数字是上下文预算策略，不是 Jev 的概率假设。

代码中的 `jev_agent.option_space.OptionSpace` 和 `OptionSpaceRegistry` 提供了这层最小抽象：选项 ID 保持稳定，分页不改变顺序，空间之间不能互相混入，预算到 8 后只能进入下一页或控制动作。

## 2. 两阶段页表记忆

### 阶段 A：从摘要页表中找候选

1. 小模型把当前上下文压缩成查询字段、实体、时间约束和冲突提示。
2. BM25/向量/图索引只负责预筛，得到最多 `M_pre` 个页表摘要。
3. Jev 看到摘要和稳定的 `page_id`，输出候选页的有限分布，以及 `NONE/CLARIFY/STOP`。

### 阶段 B：先选读取数量，再选精确页面

1. 只把阶段 A 保留下来的摘要交给 Jev，询问读取数量 `N ∈ {2,4,8}`。
2. Jev 确定 `N` 后，再在同一候选集里选择不超过 `N` 个确切 `page_id`。
3. 工具层按总字节、版本、权限和敏感级别校验后读取原文；任何未选中的页不自动注入上下文。

这样把“多个记忆条目的开放式多选题”拆成数量选择和集合选择两个有限动作。若阶段 A 漏掉关键页，阶段 B 不得伪造补全，应进入 RAG 重召回、`CLARIFY` 或人工复核。

## 3. 工具选择瞬间的预测并行

当 Jev 选中工具或 `FALLBACK_TOPK` 时，调度器可以同时启动：

- 轻量选择器：预测可能的参数字段、默认值和下一步工具，用于预取候选；
- 扩散 proposal：用多组长度、去噪步数、温度或 seed 产生完整参数/答案候选；
- 工具 I/O：只有在权限和 schema 已通过时才启动，不能让预测文本直接触发副作用。

轻量选择器只能预取，不能代替 Jev；上下文 revision、工具 schema 或依赖版本改变时，所有预取结果都标记为 stale 并丢弃。扩散模型输出属于 `PredictionSpace`，不能当作 AR next-token logits；当前小模型实验已经观察到 EOS/重复/乱码退化，因此必须经过结构化校验和拒绝出口。

## 4. 工具历史、默认值和分页

每次工具调用记录：工具版本、参数、哪些字段使用默认值、执行结果摘要、耗时、失败类型和状态节点。下一次出现相同工具和相似节点时：

1. 先展示 schema 默认值和最近成功参数；
2. Jev 或用户只需选择“使用默认/修改字段/查看历史”；
3. 历史命令只作为候选，不直接执行；敏感参数、密钥和跨工作空间路径永不进入摘要。

常用工具放在第一页。工具过多时，ToolSpace 只显示“上一页/下一页/搜索工具/打开扩展页”，扩展页中的工具以同样的 schema、权限和审计规则注册，避免把工具数量硬塞进主上下文。

## 5. 状态机和错误记忆

- **节点**：任务状态摘要、依赖版本、当前记忆页集合和已确认字段的稳定签名。
- **边**：Jev 选择的工具、参数校验、恢复动作和工具返回的状态变更。
- **错误记录**：错误边、候选排名、schema 版本、环境摘要和可回放输入。
- **异步总结**：小模型在主链路之外把错误压缩成短摘要，键为 `(node_signature, tool_name, schema_version, error_class)`；摘要带来源 trace、revision 和失效时间。
- **下次访问**：进入同一节点或调用同一工具时，错误摘要作为可选 MemorySpace 候选；只有安全性规则才可以强制阻断，普通错误应允许 `REPROPOSE` 或 `REVIEW`。

当一段子图在固定版本和多次回放中稳定成功，可以编译成“自动决策边”：满足 guard、schema、依赖版本和覆盖阈值时跳过 Jev/小模型；发生 drift、未知输入或失败时立即回退到原始模型决策，并保留编译前后的对照 trace。自动图不是永久规则，必须有版本、撤销和人工复核入口。

`jev_agent.state_machine.DecisionTraceGraph` 已提供最小实现：可以从 trace 生成
Mermaid `stateDiagram-v2`，统计成功/失败边，并只编译达到观察次数和成功率阈值的
边。`ErrorSummaryQueue` 将错误交给异步摘要器，按节点、工具、schema 版本和错误类
型聚合；它不会自动改变主链路的选择。

## 6. 分区上下文布局

```text
任务核心区：目标、约束、当前状态、版本
相关记忆区：阶段 B 明确读取的 memory blocks
最近记忆区：最近几轮的短摘要，超预算即淘汰
工具扩展区：常用工具 + 分页/搜索/默认值入口
预测区：扩散 proposal、轻量预判、来源和校验状态
错误/轨迹区：当前节点的失败摘要和可回放链接
```

每个区域都有独立字节和候选上限；区域之间不能因为某个模型输出很长就互相吞噬。这里不把 Jev 的“缓存命中率”作为目标指标：Jev 选择没有 KV cache 命中率语义，重点是候选质量、上下文污染、读取精度和决策延迟。helper 的 KV cache 仍可用于降低模型 forward 成本，但应单独计量。

## 7. 可展开记忆算法选择

“任意展开”优先采用已有方法的可解释组合，而不是把页表当作简单 LRU：

- **RAPTOR** 用递归摘要树组织叶节点和高层摘要，适合从摘要一路展开到原文；见 [论文](https://arxiv.org/abs/2401.18059)。
- **GraphRAG** 用实体关系和社区层级摘要处理跨片段关系与全局问题；见 [官方文档](https://microsoft.github.io/graphrag/)。
- **MemGPT** 将有限上下文视为虚拟内存，通过分层搬运和控制流中断管理更大的外部记忆；见 [论文](https://arxiv.org/abs/2310.08560)。

本项目的折中方案是“页表 + 关系边 + 递归摘要 + 两阶段 Jev 选择”：先用轻量索引召回，Jev 决定展开宽度，工具层负责版本和字节上限。当前 `PagedMemoryIndex` 只是确定性关键词预筛和显式读取的第一版，不复制上述项目代码，也不声称已经复现它们的效果。

## 8. 88 轮执行与验证队列

自动任务每 15 分钟推进一轮；每轮从未完成项继续，不重复已完成实验。队列按以下顺序循环：

1. 2/4/8 选项预算和上下文区域的消融；
2. 两阶段记忆与单阶段 RAG 的召回漏失、精度和成本；
3. 工具选择瞬间的轻量预判、扩散 proposal、工具 I/O overlap 与 stale 丢弃；
4. 工具历史、默认值、分页和权限审计；
5. 错误边异步摘要、节点/工具记忆和重复错误率；
6. 状态机回放、自动决策图编译、drift 检测和回退；
7. BFCL/ToolSandbox 风格隔离任务以及 Jev/helper/proposal 三路对照；
8. 汇总论文级指标、失败案例、许可证和可复现实验配置。

每项都要同时记录质量、延迟、调用次数、上下文字节、错误副作用和是否使用真实 Jev。没有真实 Jev 的运行只能标为 proxy/oracle，不能写成系统能力证明。

## 定位收敛（2026-09-24）

状态机的主线是 `Open world → Virtual Option Space → Resident Option Space → Jev decision → State transition`。`PAGE/EXPAND` 增加同粒度覆盖，`REFINE` 降低粒度；覆盖不足记为 OptionFault，粒度不足记为 RefineFault，恢复动作统一为 `EXPAND_K/BACKTRACK/REPROPOSE/LOOKUP/CLARIFY/STOP/FINISH`。helper logits 只是 proposal。相关单点已有 prior art，研究贡献候选是 Jev-native runtime 的组合，仍待实验验证。

实验应使用逻辑空间 10/100/1K/10K/100K、resident K=8/16/32，并报告 RecoveryRate、coverage、cost、latency、state errors、side effects；BFCL coverage 不等于 Jev accuracy。VirtualOptionManager、正式 fault 类型与真实 paging/replacement 的基础原型正在实现；异步 prefetch、完整 replacement policy 与 scaling benchmark 尚未实现。

