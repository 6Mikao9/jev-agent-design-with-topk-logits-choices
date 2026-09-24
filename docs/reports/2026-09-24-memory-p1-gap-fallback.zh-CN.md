# 记忆 P1：摘要缺口回读原文

脚本：`benchmarks/benchmark_memory_p1_gap.py`  
报告数据：`benchmarks/results/memory-p1-gap-48.json`  
本轮目标是把 P0 的“摘要-only 漏页”变成一个有边界的恢复路径：初始两阶段选择完成后，由任务验证器声明缺少证据标记，索引在扫描预算内检索原文，再使用相同 revision、敏感页和读字节限制读入补充页。

## 结果

同一 48 个 episode 的实际结果如下：

| 指标 | P0 summary-only | P1 gap fallback |
| --- | ---: | ---: |
| page hit rate | 50.0% | 75.0% |
| 原文证据召回 | 50.0% | 75.0% |
| 答案正确率 | 50.0% | 75.0% |
| guard safe rate | 100.0% | 100.0% |
| fallback recovery rate | 0.0% | 25.0% |
| 平均读取字节 | 374.0 B | 498.5 B |

P1 相对基线把三项召回/正确率都提高了 25 个百分点；额外读取约 33.3%，但没有牺牲 stale 安全性。恢复只发生在 12 个 conflict episode，fresh/distractor 不触发，stale 仍不尝试回读。

重点指标定义如下：

- `answer_correct_rate`：恢复是否真正补足答案所需证据；
- `recovery_rate`：多少 episode 触发并成功补页；
- `guard_safe_rate`：stale 选择是否仍被拒绝；
- `mean_read_bytes`：正确率提升付出的额外读取量。

结果比预期好：conflict 全部补回当前页，fresh/distractor 没有额外回读，stale guard 保持 100%。这只说明恢复机制在“证据契约明确”的条件下有效；它不能证明 Jev 自己能发现任意语义遗漏。

## 机制边界

`PagedMemoryIndex.search_content` 只返回稳定 page metadata，原文扫描受 `max_scan_bytes` 限制；扫描按页顺序进行，遇到预算不足会停止，因此报告不把它当作无界全文检索。最终读取仍经过 revision、敏感页和总字节预算检查。marker 是任务/工具定义的证据契约，不是目标 page id，也不是把真实标签喂给 Jev。后续仍需比较混合 lexical/vector 检索、摘要遗漏回原文 span、多针冲突和真实 Jev 闭环。
