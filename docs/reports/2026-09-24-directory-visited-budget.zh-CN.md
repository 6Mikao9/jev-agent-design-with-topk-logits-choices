# 目录窗口 visited set 与预算

## 目的

修复真实 Jev 矩阵中 `NEXT` 在目录窗口之间循环的问题。此前一个错误页或 verifier false reject 会重复浏览同一组窗口，直到耗尽总调用预算；这让失败原因混在“定位失败”和“控制流没有终止”里。

## 实现

`benchmarks/benchmark_jev_bounded_paging.py` 现在为每个 episode 维护 `visited_windows`：

- 每个窗口最多访问一次；
- `NEXT` 指向已访问窗口时记录 `directory_exhausted` 并终止；
- trace 返回 `directory_windows_visited / directory_window_count`；
- summary 单独统计 `directory_exhausted`。

这只是控制流安全边界，不把“浏览完目录”当作成功。

## 离线回归

8 个 benchmark 单测通过；远端完整测试 **154/154** 通过。`NEXT` 重复三次的脚本现在以 `directory_exhausted` 终止，并且访问窗口数等于窗口总数。

## 真实 Jev 小矩阵

在 seed=31、`wrong_page` 12-case、`ACCEPT/PAGE` verifier 下复跑：

| 指标 | 结果 |
|---|---:|
| 成功 | 9/12 (75%) |
| 首页定位 | 10/12 |
| missing detection | 11/12 |
| candidate rejection | 3 |
| directory_exhausted | 2 |
| Jev 调用 | 58 |
| request P50 | 639.8 ms |
| case P50 / P95 | 3,297.7 / 4,528.9 ms |
| resident 峰值 | 2/2 |

机器结果：`benchmarks/results/jev-bounded-paging-seed31-wrongpage-round6.json`（结果文件留在远端/本地 ignored 目录，不进 Git）。

## 判断

相对预期：**终止性更好，正确率没有证明提升**。2 个 case 现在明确报告目录穷尽；这比反复 NEXT 到全局预算耗尽更可诊断。9/12 不能与上一轮 10/12 做严格 paired 比较，因为 Jev 返回有随机性，且这是只含 wrong-page 的子集；下一步需要引入目录排序、visited 页面摘要和更明确的无法定位终态，再在同一 prompt/请求顺序下比较。

## 下一步

把 `NEXT` 改成带 remaining-window count 的状态，增加 query-aware page ranking 和 page-localization budget；将 `directory_exhausted` 映射为明确的 `CLARIFY` 或安全 `STOP`，并单独统计 false reject 与 locator miss。
