# 24 步状态依赖恢复 workload

## 目的

验证一个有隐藏可变状态、合法但过期的工具读数、依赖版本失效和源事实刷新路径的最小长轨迹。该实验用于 C（context/memory residency）与串联 workload 的离线基线，不声称已经完成真实 Jev 闭环。

## 配置

- 步数：24
- 隐藏状态：`quota / used / version`
- 第 6 步修改 quota，递增 revision
- 第 8 步注入一个格式合法但数值过期的 `read_quota`
- 发现矛盾后调用 `MemoryBank.invalidate_changed`，再从环境源事实刷新
- 第 20 步再次修改 quota；后续继续读取并在超额 reserve 时安全阻断
- 外部副作用：0
- resident 上限：3 个 context block

## 结果

| 指标 | 结果 |
|---|---:|
| contradictions_detected | 1 |
| invalidated_records | 3 |
| recovery_successes | 2 |
| memory_records | 4 |
| resident_bound | 3 |
| external_side_effects | 0 |
| 完整测试套件 | 148/148 通过 |

机器可读结果：`benchmarks/results/stateful-recovery-workload.json`。

## 判断

相对预期：**更好，且符合预期的安全边界**。过期读数被识别、历史记录被失效、源事实刷新成功，且没有越过 resident 上限或产生副作用。这证明了 revision/invalidation 的机制基线。

但它仍然是确定性的 Python 控制器：没有让 Jev 选择 PAGE/REFINE/CLARIFY，也没有把重建内容作为后续真实决策的必要输入。因此不能把 1/1 矛盾恢复解释成 Jev 的准确率，也不能替代无 oracle locator 的检索实验。

## 失败尝试与原因

本轮早先尝试直接接入 `DecisionRuntime`。控制模型在 `needs_repair` 时总是优先选择 `PAGE:recovery`，导致重复分页、0 次提交，24 步后 `state_dependent_success=false`。这暴露出恢复动作优先级与终态/重试预算没有统一，失败原型已删除，后续应在 runtime 中加入有界 recovery state、动作冷却和 `PAGE → REFINE/COMMIT` 转移约束后再重接。

## 下一步

将此 workload 接入统一 `Runtime.step()`，先使用 scripted backend 验证状态转移，再替换真实 Jev；同时加入多针/冲突证据和 20–100 步轨迹，分别报告 missing detection、page localization、recovery success 与 end-to-end success。
