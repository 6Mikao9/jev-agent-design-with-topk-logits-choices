# 记忆 P2：多针冲突与页面顺序敏感性

脚本：`benchmarks/benchmark_memory_p2_multineedle.py`  
报告数据：`benchmarks/results/memory-p2-multineedle-order-9.json`

## 设计

每个 episode 有两个必须同时读取的当前证据页（`needle-a`、`needle-b`）、两个历史冲突页和两个高词法重合 decoy。查询只描述 Atlas 部署核对和冲突比较，不包含 needle 名称；needle 只作为 verifier 的证据契约。固定三种原文插入顺序：目标在前、目标在后、seed=17 随机。对照策略是 summary-only、content-only fallback 和 weighted-RRF hybrid fallback。原文扫描预算固定为 1,000 B，页数上限为 2。

`joint_recall` 要求两个当前证据页都被读到；只读到一个针只算 0.5 的 `needle_recall`，不能被当成答案成功。`marker_precision` 只统计 fallback 新增页中带 primary evidence marker 的比例。

## 结果

实际运行得到 9 行明细和按策略/顺序分桶的汇总：

| 策略 | prefilter candidate recall | needle recall | joint recall | answer correctness | 平均读取 |
| --- | ---: | ---: | ---: | ---: | ---: |
| summary-only | 100% | 0% | 0% | 0% | 584 B |
| content fallback | 100% | 66.7% | 66.7% | 66.7% | 972 B |
| hybrid fallback | 100% | 66.7% | 66.7% | 66.7% | 1,166.7 B |

content 与 hybrid 在 target-first、random 顺序均达到 100% 联合召回，在 target-last 均为 0%；因此顺序敏感性真实存在，且本矩阵中 hybrid 没有改善它，反而读取更多。summary-only 的候选召回虽为 100%，但 TOP-2 前缀没有选中两针，说明 prefilter recall 和 selector-prefix recall 必须分开报告。

预期：目标在前时 fallback 可以联合召回，目标在后时受到有界扫描顺序影响；summary-only 在历史冲突和 decoy 占据 TOP-2 时不能稳定联合召回。结果符合且部分更差于理想预期：hybrid 没有缓解 target-last，平均读取量更高。现在若回读页没有满足全部证据 marker，会返回 `contract_unsatisfied`，不会把“读到了某些页”报告成 recovered。无论顺序如何，实验不允许绕过 page revision、敏感页或读取预算。

## 边界

这是检索/预算控制实验，不是 Jev 语义质量结果。证据 marker 是 verifier 提供的任务契约，不是隐藏目标 page id；未来真实 workload 需要把它替换为工具 schema、状态不变量或冲突检测器。`search_content` 到达扫描预算会停止，因此顺序敏感性是需要测量的系统属性，而不是被隐藏的实现细节。
