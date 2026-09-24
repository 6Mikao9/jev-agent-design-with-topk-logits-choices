# `Runtime.step()` 执行结果验证与依赖失效

## 目的

补上“工具回调正常返回就算成功”的边界。一个结果可以格式合法、调用本身没有抛异常，但仍然携带旧 revision 或与当前任务状态矛盾；runtime 必须保留原始结果、标记拒绝、推进依赖 revision 并定向失效 memory/context。

## 实现

新增 `ExecutionVerdict` 回调协议：

- `accepted`：是否允许把本步记为执行成功；
- `reason`：拒绝原因；
- `changed_dependencies`：被结果证明发生变化的依赖 ID；
- `observation`：写入任务观察的短证据。

`DecisionRuntime.step()` 在工具执行后依次做：

1. 验证返回值类型；
2. 对变化依赖调用 `TaskState.revise()`；
3. 用 `MemoryBank.invalidate_changed()` 失效旧事实；
4. 用 `ContextResidencyManager.invalidate_dependencies()` 移除 stale 驻留块；
5. 拒绝时返回 `execution_rejected`，不自动重试，也不记为 `executed`；
6. 记录 trace 边和原始 `tool_result`。

`TaskState.revision` 与 option/page revision 仍是不同命名空间。当前协议尚未包含不确定副作用的 `unknown/needs_reconciliation` receipt，后续需要单独加入幂等对账路径。

## 受控结果

新增 runtime 集成测试注入一个合法但过期的 quota 读数：

- 第一次 `read`：返回 `execution_rejected`；
- quota 依赖 revision 从 1 变为 2；
- `quota-old` memory 被失效；
- quota context block 被移出 resident，稳定约束保留；
- 下一次 Jev 决策看到不一致观察后选择 `refresh` 并成功执行；
- 没有自动重放被拒绝的 `read`。

远端完整测试：**157/157 通过**。

## 判断

相对预期：**符合预期，补上了安全边界**。这不是 Jev 质量提升数字，而是把错误工具结果从“成功执行”改成可审计的 recovery 输入，减少了上下文和 memory 被错误事实污染的风险。

## 下一步

把 `ExecutionVerdict` 扩展成带 `applied/rejected/unknown`、前后 environment version、effects 和幂等键的 `ExecutionReceipt`；对真实文件/命令工具加入无副作用校验和显式对账，禁止 unknown 自动重试。
