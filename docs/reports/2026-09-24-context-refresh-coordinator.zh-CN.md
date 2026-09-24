# 按需上下文刷新协调器：协议基线

脚本：`benchmarks/benchmark_context_refresh_coordinator.py`  
结果：`benchmarks/results/context-refresh-coordinator.json`

## 本轮实现

新增 `ContextRefreshCoordinator`，把上下文刷新拆成四个阶段：

1. 触发门控：每次请求递增逻辑步，使用 cooldown 和阶段预算抑制重复刷新；
2. 目录候选：从 `ContextResidencyManager.candidates()` 取得不超过 `M` 个候选；
3. 并发验证：对候选 block 并发调用 verifier，校验 `block_id` 和 `[0,1]` 分数；
4. 原子提交：检查全局 epoch 与所有 block revision 未变化后，调用 `commit_selected()` 换入不超过 `K` 个 working block。

旧 epoch、旧 revision、异常 verifier 和超过预算的结果不会进入 resident set。verifier 可以由 Jev 适配器、回放选择器或 deterministic test double 实现；本轮没有调用网络 Jev。

## 代理结果

配置：6 个阶段事件，`M=2`，`K=1`，每个 verifier 人为等待 2 ms，使用确定性目标判断。

| 指标 | 结果 |
| --- | ---: |
| 提交刷新 | 6/6 |
| 目标 block 命中 | 6/6 |
| verifier 调用 | 10 |
| 平均单次协调耗时 | 约 2.58 ms |
| storm guard | 5 次请求中 4 次 suppressed |
| stale guard | `stale_epoch`，旧结果未换入 |
| resident 上限 | 1 个非 pinned block |

结果比协议正确性预期好：并发验证、冷却抑制和 epoch 拒绝都通过了；但这不是 Jev 语义准确率，也不能推导真实网络延迟。代理 benchmark 的 verifier 已知目标，不能证明目录召回或 Jev confidence 校准。

## 与原实现的区别

原实现是调用方显式 `refresh()` 的词法/utility 重建，记忆 selector 是 Jev 排序后选择 `TOP_N` 前缀。新协调器增加逐 block verifier 和原子提交，但暂时仍使用单级词法目录；`parent_id` 尚未实现多级遍历，`raw_content_ref` 也没有在 context block 刷新时自动加载正文。

## 结论与下一步

该协议值得保留为可关闭的 P2 实验，不应默认让 Jev 自由触发。下一步比较 `M=2/4/8`、`K=1/2/4` 和 cooldown，加入 `NO_EVIDENCE` 与 evidence reference，再用少量真实 Jev 测目录 recall、verifier F1、无效刷新率、调用数和 P50/P95。0.8B 摘要只作为异步候选，原文证据、revision 和 RAG 预筛仍由 runtime 保留。
