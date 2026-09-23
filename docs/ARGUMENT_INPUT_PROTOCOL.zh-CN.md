# 开放工具参数输入协议

状态：原型实现，面向有限选项 Decision Model；真实 Jev 的端到端正确率尚未测量。

## 目的

工具参数采用四段流程：

```text
小模型/历史提案 → Jev 选择或 REFINE/REPROPOSE → 字段与整组校验 → 外部 COMMIT
```

提案只是候选值，不能携带可执行指令，也不会直接调用工具。未知事实必须走 `LOOKUP` 或 `CLARIFY`；系统不把小模型猜测当成事实。

## 每个字段的选择项

在每一轮候选提案中，Jev 可以选择：

| 选项 | 含义 |
| --- | --- |
| `VALUE_i` | 接受第 `i` 个已经通过字段 schema/领域检查的精确值 |
| `REFINE` | 立刻放弃当前字段草案，使用 helper logits 逐步选择片段/token，直到 `END_FIELD` |
| `REPROPOSE` | 丢弃当前候选，刷新一轮小模型、检索器或历史 prior 提案 |
| `LOOKUP` | 当前值依赖环境事实，先查工具或外部状态 |
| `CLARIFY` | 用户意图或范围不明确，要求澄清 |
| `STOP` | 安全停止，不提交工具调用 |

`REFINE` 可以在第一次提案就被主动选择，也可以在候选连续失败后触发。刷新次数、逐 token 步数、Jev 调用数和总时间均有上限；超过上限不循环重试。

逐步填写时，Jev 只从 helper 当前返回的 exact token 候选和控制项中选择。`END_FIELD` 只结束当前字段；它不是整段对话的结束，也不代表工具已经执行。若字段需要结束对话，仍使用独立的 `END_DIALOGUE` 语义并检查完成谓词。

## 多字段并行与依赖

字段声明 `depends_on` 后形成有向无环图。没有依赖的字段可以并行请求提案和选择；依赖字段要等上一层值完整、通过校验并冻结后再开始。每个并行字段必须有独立的 chooser/helper session；特别是可变 KV cache 不能在字段间共享。并行是调度重叠，不等于已经实现 GPU batch。

## 提交边界

所有字段完成后才构造一个不可变 `Candidate`。提交前重新检查：

1. 完整工具 JSON schema 和跨字段约束；
2. state/task revision、工具 schema version 和依赖版本；
3. 权限、证据引用、路径/大小/时间预算；
4. 数值可 JSON 序列化，拒绝 NaN/Infinity。

任一检查失败都不调用 executor。现有 `Agent` 负责最后一次 Jev `COMMIT` 选择和执行，`ArgumentInput` 本身只准备 Candidate。执行失败与候选无效分开记录，网络/提供方错误不会被误记为语义失败并自动重试。

## 当前实现与边界

- `jev_agent.arguments.ArgumentInput`：proposal、`REFINE`、`REPROPOSE`、字段 DAG、并行 wave、全局预算和原子 Candidate。
- `jev_agent.argument_helpers.GreedyFieldProposer`：可选 raw-logits helper 适配；每个字段要求独立 helper session，当前是简单 greedy 示例，不是质量或速度结论。
- `jev_agent.topk.TopKBuilder`：支持可配置 `END_FIELD` 和候选总数上限，控制项也计入 Jev 的有限 option cap。
- `examples/file_command_demo.py`：在项目专用空目录内串联文件搜索、读取、精确替换和受限命令验证；默认 scripted chooser，`--live` 才连接真实 Jev。

这套协议保留了 Jev 的最终选择权，同时允许它主动逐步输入或刷新候选。后续实验要比较：直接接受、主动 `REFINE`、失败后 `REFINE`、`REPROPOSE`，并报告字段正确率、整组成功率、非法参数率、helper/Jev 调用、stale 丢弃、执行副作用和 P50/P95 延迟。
