# 真实 Jev 48-case 分页矩阵与执行前校验（seed=31）

## 目的

把上一轮的 8-case 新 seed 复核扩大到完整 12 页 × 4 状态矩阵，并比较错误页上直接提交工具与执行前 `ACCEPT/PAGE` 校验。目录页 ID 对 Jev 不透明，gold page/tool 只由 runner 在终止后评分。

## 配置

- 12 页、24 个工具，随机目录顺序 seed=31
- 每页 `empty / wrong_page / stale / correct_resident`，共 48 case
- 每次最多 8 个接口选项，resident 工具上限 2
- 外部工具副作用为 0；`ACCEPT/PAGE` 只是模拟执行前的 scope verifier
- 结果文件（均在远端 `benchmarks/results/`，未进入 Git）：
  - `jev-bounded-paging-seed31-round5.json`：无 verifier
  - `jev-bounded-paging-seed31-verify-round5.json`：带 verifier

## 结果对照

| 指标 | 直接提交 | `ACCEPT/PAGE` 校验 |
|---|---:|---:|
| 成功 | 42/48 (87.5%) | 45/48 (93.75%) |
| empty | 11/12 | 12/12 |
| wrong_page | 8/12 | 10/12 |
| stale | 11/12 | 12/12 |
| correct_resident | 12/12 | 11/12 |
| 首页定位（非驻留） | 30/36 | 32/36 |
| missing detection | 8/12 | 11/12 |
| candidate rejection | 0 | 5 |
| Jev 调用 | 111 | 202 |
| request P50 | 622.8 ms | 637.4 ms |
| case P50 / P95 | 1,291.6 / 2,548.9 ms | 2,484.4 / 7,041.3 ms |
| resident 峰值 | 2/2 | 2/2 |

## 失败分析

直接提交路径的主要失败是 wrong page 上的合法工具被立即当作答案，说明没有执行前 scope 检查时无法区分“语法合法”和“任务正确”。加入 verifier 后剩余三例为：

1. `web-wrong_page`：Jev 直接 `CLARIFY`，属于过度拒答；
2. `recent-wrong_page`：发现当前页缺能力后反复 `NEXT`，目录窗口策略没有找到目标页；
3. `scheduler-correct_resident`：正确候选被 verifier 误拒，随后多次换窗口并耗尽预算。

## 判断

相对预期：质量**更好**，但成本**更差**。执行前校验使总成功率提高 6.25 个百分点、wrong-page 恢复提高 2/12，验证了 recovery gate 的价值；代价是调用数增加 82%，case P95 增至 7.04 秒。verifier 不能直接照搬成每一步都调用 Jev，应加入高置信 fast path、目录窗口去重/终止条件、并行候选校验和有界重试。

这仍是受控分页协议：没有真实文件/数据库副作用，也没有参数 REFINE 或 20–100 步状态依赖。结果不能解释为通用 agent 成功率。

## 下一步

把 verifier 失败分成 `wrong_candidate` 与 `false_reject`，加入明确的 `CLARIFY` 负例；实现目录窗口 visited set 和 page-localization budget，再比较串行校验、并行校验与 helper 预筛的 P50/P95/cost。
