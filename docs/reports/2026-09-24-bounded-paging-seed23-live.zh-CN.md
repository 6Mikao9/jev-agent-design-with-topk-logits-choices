# 无 oracle locator 的真实 Jev 分页复核（seed=23）

## 目的

在新的随机目录顺序上复核真实 Jev 是否能从不透明页 ID 的目录窗口定位页面，并在 `empty / wrong_page / stale / correct_resident` 四种初始状态下完成页内工具选择。gold page/tool 只由 runner 在终止后评分，未放入 Jev prompt。

## 配置

- 逻辑目录：12 页、24 个工具
- 目录 ID：随机顺序生成的 `pXX`，模型只看到当前窗口摘要
- 选择上限：每次 8 个选项（含 NEXT、CLARIFY、STOP 等控制项）
- resident 工具上限：2
- 每个初始页状态各取 2 个 case，共 8 个 case
- Jev 调用：16 次；外部工具副作用：0
- 结果文件：`benchmarks/results/jev-bounded-paging-seed23-key2.json`

## 结果

| 指标 | 结果 |
|---|---:|
| 完成 / 成功 | 8 / 8 |
| success rate | 100% |
| 初始非驻留 case | 6 |
| 首页定位 | 6 / 6 |
| wrong page 恢复 | 2 / 2 |
| stale block | 2 |
| candidate rejection | 0 |
| resident 峰值 / 上限 | 2 / 2 |
| choice surface 峰值 | 8 |
| request P50 | 623.9 ms |
| case P50 / P95 | 1,216.9 / 1,990.5 ms |
| input / output tokens | 7,775 / 1,238 |

## 判断

相对预期：**好于最低预期**。在新 seed 和不透明页面 ID 下，四种状态都完成了目录定位、stale 阻断和页内选择；resident 上限没有突破。它支持“真实 Jev 可以运行这条无 oracle locator 协议”的判断。

这仍不是大规模质量结论：只有 8 个 case，覆盖了 2 个页面主题；没有真实工具副作用，也没有多跳参数 REFINE。此前首个一次性凭据尝试在第一调用发生 transport error，未计入质量统计；换用下一条凭据后完成本报告，凭据本身没有写入结果或 Git。

## 下一步

扩大到完整 12 页 × 4 状态矩阵，加入相似主题和否定 decoy；把页内选择接入真实执行校验，再测 missing detection、page localization、recovery success 和 end-to-end success 的分项指标及 P50/P95/cost。
