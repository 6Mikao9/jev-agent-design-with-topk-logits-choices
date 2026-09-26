# `ExecutionReceipt`：不确定副作用的对账边界

## 目的

工具调用抛出异常或返回不确定结果时，runtime 不能把它当作失败后自动重试。远端服务可能已经执行了副作用，重复写入、重复删除或重复提交都会扩大错误。Round 9 将执行协议收敛为可审计的 `ExecutionReceipt`。

## 协议

`ExecutionReceipt.status` 只有三种值：

- `applied`：工具确认已经应用；可携带结果、幂等键和环境版本；
- `rejected`：工具确认没有应用；返回 `execution_rejected`，不自动重试；
- `unknown`：无法确认副作用是否发生；返回 `needs_reconciliation`，runtime 保存 receipt 并冻结该任务的再次执行。

`DecisionRuntime.pending_execution(task_id)` 可以读取待对账 receipt。调用方需要从外部系统确认结果，先把观察写入 `TaskState`（从而推进 revision），再调用 `acknowledge_reconciliation()`。这个确认接口不会重放原操作，也不接受另一个 `unknown` receipt。

旧的回调仍可返回任意值，兼容路径会继续按旧的 `ExecutionVerdict` 验证；新工具应显式返回 `ExecutionReceipt`。执行器抛出的异常被保守地转换为 `unknown`，只记录异常类型，避免把私有错误文本写入 trace。

## 验证

新增测试覆盖：

1. `unknown` 第一次返回后，后续 `step()` 仍返回 `needs_reconciliation`，执行器调用次数保持 1；
2. 幂等键不匹配或任务 revision 尚未推进时，确认会被拒绝；
3. 外部 revision 更新并确认后，pending 状态清除；
4. 执行器抛出 `TimeoutError` 时不自动重试。

远端同步后完整测试为 **159/159 通过**，运行时间约 0.29 秒。本轮新增的两项
对账测试和现有 runtime、工具、benchmark 测试均通过。

## 判断

相对预期：**符合预期并补强了安全边界**。这项改动没有声称提升 Jev 决策准确率；它减少了不确定工具副作用导致的重复执行，并为后续真实文件/命令工具提供对账接口。
