# 真实 Jev 上下文刷新价值 smoke

脚本：`benchmarks/benchmark_context_refresh_live.py`  
结果：`benchmarks/results/context-refresh-live.json`

## 测试边界

本轮把 `JevContextVerifier` 接到真实 TypeSafe Jev，运行 5 个受控 case。页面使用不透明 ID（`b17`、`b42` 等）；gold 映射只存在于评估器，不进入 query、block summary、选项或 verifier。每个 case 使用 `M=4`、`K=1`，最多并发 4 个 verifier 请求。

这不是通用 Jev 准确率测试。它只回答一个窄问题：当目标上下文不在 resident set、但已被目录召回时，Jev verifier 能否帮助协调器换入正确 block。

## 结果

| case | 初始 resident 命中 | 目录召回 | 刷新后命中 | 状态 | 目标是否被选中 |
| --- | ---: | ---: | ---: | --- | ---: |
| current deploy 缺失 | 否 | 是 | 是 | committed | 是 |
| rollback 缺失 | 否 | 是 | 是 | committed | 是 |
| audit evidence 缺失 | 否 | 是 | 否 | no_supported_block | 否 |
| current deploy 已驻留 | 是 | 是 | 是 | no_gain | 是 |
| Atlas plan 歧义、无 gold | 否 | 不适用 | 否 | no_supported_block | 否 |

汇总：gold case 的初始命中为 **1/4**，刷新后命中 **3/4**；其中 3 个真正缺失 case 从 0/3 恢复到 **2/3**。目录召回为 **4/4**，因此本轮没有把目录漏召回混入 Jev verifier 错误。无 gold 歧义 case 没有发生误刷新。

每个 case 都至少有一个 `NO_EVIDENCE` verifier 结果；这说明该选项能被真实 Jev 使用，但当前没有人工标注每个 block 的可判定性，不能把 `NO_EVIDENCE` 直接算对或算错。

## 延迟与成本

- 20 次真实 Jev verifier 调用；总报告耗时约 13.20 秒；
- 单次 Jev 调用 P50 **663.8 ms**、P95 **703.2 ms**，范围 599.1–729.0 ms；
- 每个 case 的并发墙钟约 0.67–0.73 秒；
- 本轮没有发生 401 以外的 transport error。第一次候选 key 返回 401，换用 `api.txt` 中的下一条候选后完成测试；凭据没有写入报告或 Git。

相对预期：**机制价值有正向信号，但还不够形成结论。** 在目录已经找对页面的前提下，真实 Jev 把 3 个缺失 case 中的 2 个恢复成功；一个 audit case 选择了 `NO_EVIDENCE`，这既可能是合理保守，也可能是摘要表达不足。调用成本符合当前 Jev 单次约 0.6–0.7 秒的量级，`M=4` 的并发没有变成 4 倍串行延迟，但总调用费用仍是 20 次。

## 失败原因与限制

1. `audit evidence` 的 gold block 已进入目录，但 Jev 没有选出支持 block；需要把“摘要不足”和“确实不相关”分开标注，并加入原文 evidence verifier。
2. 当前实验只测了单层 lexical directory；不能说明多级页表或向量 RAG 的召回能力。
3. context block 的 `raw_content_ref` 尚未自动加载正文；本轮测的是摘要级刷新，不是原文证据正确性。
4. 20 次调用太少，不能估计一般正确率或 confidence calibration。
5. 第一个 key 的 401 结果属于凭据状态，不计入语义指标。

下一步应加入 paired block 顺序、同实体错误 revision、摘要删掉关键证据、明确不可判定样本，并分别报告 directory recall、verifier F1、最终 evidence recall 和 false refresh。上下文空间的完整分区图另行补入 README，不与本次语义 smoke 混在一起。
