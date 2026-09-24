# A/B/C 串联 workload

脚本：`benchmarks/benchmark_serial_workload.py`  
报告数据：`benchmarks/results/serial-a-b-c-workload-4-steps.json`

## 轨迹

四步顺序为 `deploy(rev1) → rollback(conflict) → audit(rev1) → deploy(rev2)`。每一步先刷新实时上下文，再做两阶段记忆选择；rollback 额外要求同时读到历史冲突页和当前页，触发有界原文 fallback；最后构造并显式提交一个经过 schema 校验的工具参数 Candidate。

## 结果

实际运行结果：

| 指标 | 结果 |
| --- | ---: |
| steps | 4 |
| context hit rate | 100% |
| memory correctness | 100% |
| argument ready | 100% |
| tool commit | 100% |
| tool calls | 4 |
| resident bound | 通过 |

rollback 只在冲突场景触发原文 fallback；最后一次 deploy 使用同一个稳定 page ID 的 revision=2 更新。早期试跑若为每次 deploy 生成新 page ID，会错误地重新选中旧页；改为稳定 ID 后恢复正确。这正是 revision/identity 设计需要覆盖的 failure mode。该结果只能说明四个 runtime primitive 在受控串联轨迹中没有断链，不能外推真实 Jev 的语义正确率。

## 边界

所有 chooser 都是 deterministic scripted backend；没有网络延迟、工具异常或真实 Jev 分布。下一步应将同一轨迹替换为真实 Jev，并记录每次 PAGE/REFINE/LOOKUP/CLARIFY 的决策与恢复成本。
