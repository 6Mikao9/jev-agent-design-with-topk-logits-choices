# 工具参数输入协议基线

脚本：`benchmarks/benchmark_argument_protocol.py`  
报告数据：`benchmarks/results/argument-input-protocol-4-cases.json`

## 设计

四个受控 case：直接接受候选、选择 `REFINE` 用 helper 逐 token 构造、选择 `REPROPOSE` 刷新候选、缺少证据时进入 `LOOKUP`/停止。每个候选先经过字段 schema 和工具 schema 校验，再由外层 `Agent` 单独选择 Candidate 才允许 executor 执行。

## 结果

实际运行结果：

| case | input status | choice/helper calls | commit | tool calls |
| --- | --- | ---: | --- | ---: |
| direct | ready | 1 / 0 | executed | 1 |
| refine | ready | 3 / 2 | executed | 1 |
| repropose | ready | 2 / 0 | executed | 1 |
| missing_evidence | lookup_required | 0 / 0 | not attempted | 0 |

汇总 `ready_rate=75%`、`commit_success_rate=75%`、无证据执行次数为 0。missing_evidence 的两轮 proposal 都被证据要求拒绝，没有 Candidate，也没有工具副作用。

结果符合预期：REFINE 和 REPROPOSE 可以恢复到可提交候选，证据缺失路径不会猜测或执行。该结果只验证协议状态转移与执行闸门，不代表真实 Jev 的选择质量或网络延迟。

## 边界

当前 CLI 仍要求显式工具 JSON；本 benchmark 不把普通自然语言直接解释成 shell 或文件操作。后续可将 scripted chooser 换成真实 Jev，并加入参数依赖 DAG、工具执行失败后的回滚和并行字段 latency。
