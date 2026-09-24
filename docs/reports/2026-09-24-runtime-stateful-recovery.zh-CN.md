# `Runtime.step()` 状态依赖恢复闭环

## 目的

把前一轮的离线矛盾/invalidation 基线接入统一 `DecisionRuntime.step()`，检查 PAGE、工具执行、任务 revision、过期读数、源事实刷新和后续依赖动作能否在同一有界循环中完成。

这是 scripted `OracleDecisionModel` 的机制实验，不是 Jev 准确率实验。

## 配置

- 24 次 `Runtime.step()` 调用
- 初始 quota=3、used=0、version=1
- 第 1 步选择 `PAGE:tools`
- `mutate1` 将 quota 改为 1，递增任务 revision
- 第 5 步注入一次格式合法但过期的 `read`
- 检测矛盾后失效依赖记录、重新读取源事实，并让后续 `mutate2`/`reserve` 依赖新 revision
- reserve 执行两次，最后停止
- resident 上限 8 个 option，context working 上限 3，外部副作用只来自受控 reserve

## 结果

| 指标 | 结果 |
|---|---:|
| page_recoveries | 1 |
| commits | 2 |
| contradictions | 1 |
| invalidations | 1 |
| recovery_successes | 1 |
| post_refresh_correct | true |
| resident_peak / bound | 4 / 8 |
| external_side_effects | 2 |
| 完整远端测试 | 154/154 通过 |

机器可读结果：`benchmarks/results/runtime-stateful-recovery.json`。

## 判断

相对预期：**比上一版直接接入的失败尝试好**。现在 PAGE→执行→revision 变化→矛盾检测→刷新→后续动作完整通过；任务 revision 与 option revision 已分开校验，重复 PAGE 受任务隔离的预算约束，shadow prefetch 不会污染 resident。

结果仍不能外推为真实 Jev 的选择质量：决策 backend 是 scripted oracle，且 24 步后半段是显式 STOP 填充，真实模型的定位、歧义、延迟和 cost 尚未测量。

## 曾经的失败与修复

旧控制脚本把 `needs_repair` 优先级写成无条件 `PAGE:recovery`，导致 24 步 0 次提交；修复为有界、状态化动作序列后再接入 runtime。另发现 runtime 曾把 `TaskState.revision` 错当成 `VirtualOption.revision`，任务更新后会误报 stale；本轮已拆开两个 revision 命名空间并加入回归测试。

## 下一步

把相同 workload 替换为真实 Jev DecisionModel，增加 wrong/empty/stale/correct page 四状态、无 oracle locator 的目录检索、多针冲突证据和 P50/P95/cost；随后再做 20–100 步真实状态依赖轨迹。
