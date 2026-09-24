# Evidence-gated file agent：受控闭环

脚本：`benchmarks/benchmark_grounded_live.py`  
报告数据：`benchmarks/results/grounded-file-agent-replay.json`

## 这轮修复的证据边界

上一轮串联 workload 的 100% 是 scripted chooser 接受固定参数、executor 只追加内存列表，且每一步没有真正依赖前一步结果。本轮加入 `GroundedArgumentAgent`：

1. 先刷新并校验当前 context block；
2. 进行两阶段 page-table 读取；
3. verifier 检查 entity、revision 和 approval-service provenance，缺失时才启动有界 raw fallback；
4. 在参数 Candidate 生成后，调用工具前重新读取 evidence、重新检查 revision/context；
5. 只有外层 Jev/chooser 选择 Candidate 才执行实际 workspace `file.write`。

## Replay 结果

三个环境事件：Atlas version 1 `canary`、version 2 `stable`、缺少 version 3。前两个事件实际写入隔离临时 workspace，第三个必须阻止写入。

| 事件 | 结果 | 是否写文件 |
| --- | --- | ---: |
| version 1 | executed，正确 | 是 |
| version 2 | executed，正确 | 是 |
| version 3 缺证据 | evidence_blocked | 否 |

汇总：current file correctness 2/2，missing evidence writes 0，三事件 scorer 全部正确；replay 共有 10 次 scripted decision calls。结果比上一轮的 tautological 串联更有意义，但仍不是 Jev 质量结果。

## 真实 Jev 对照

同一脚本支持 `--live --key-stdin`。本轮实际运行数据在 `benchmarks/results/grounded-file-agent-live.json`：

| 指标 | 结果 |
| --- | ---: |
| 事件完成 | 3/3 |
| 当前证据版本正确写入 | 2/2 |
| 缺失证据误写入 | 0 |
| Jev 选择调用 | 10 |
| Jev 累计报告耗时 | 6,452.65 ms |
| backend | `jev-1.13.0` |

每个事件的状态为 `executed / executed / evidence_blocked`；单次选择耗时约 602–698 ms，具体 token 用量和概率保存在远端 JSON。这个结果比 replay 预期好：真实 Jev 没有破坏 evidence gate，并在有限枚举任务中完成了两个有效提交；样本只有 3 个事件，不能推出真实 Jev 的一般正确率或延迟分布。Live 输出只保留 choice、概率、模型、token 用量、耗时和安全错误类型；凭据不进入 JSON。真实 Jev 如果超时、拒绝或返回无效选择，报告会保留失败事件，不会改写为 replay 成功。该实验不要求 GPU，也不把 backend cache 行为解释成 runtime 事实。

## 限制

候选值是有限枚举，尚未覆盖真实自然语言参数、参数 `REFINE` token 构造或外部工具失败重试。证据 marker 是环境 verifier 契约，不能当作 Jev 自己发现了语义缺口。
