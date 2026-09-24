# PAGE 异步 materialization 基线

脚本：benchmarks/benchmark_async_materialization.py  
报告数据：benchmarks/results/async-page-materialization.json

## 实现

SpeculationBuffer.prefetch_async() 先复制 page snapshot，再在 bounded thread pool 中准备 shadow pages；完成的 future 只有经过 await_materialization() 才进入 shadow buffer，始终不会自动写入 VirtualOptionManager 的 resident set。promote() 继续检查 state revision 和 page revision。

## 结果

实际测量两个页面各 35 ms 的本地 materialization：

| 指标 | 结果 |
| --- | ---: |
| 顺序准备 | 70.385 ms |
| 异步调度返回 | 0.922 ms |
| 异步总耗时（含 20 ms 等待窗口） | 36.248 ms |
| promoted option | `files:0` |
| stale promotion | `StaleVirtualOption` 拒绝 |

异步总耗时接近单页准备时间而非两页相加，结果比预期好；页面仍在 shadow buffer 中，只有显式 promote 才进入 resident。前一次试跑暴露了同步路径的变量回归，修正后远端 121 项测试全部通过。

结果只说明异步 shadow materialization 的并发与一致性边界。它不是 Jev/API 端到端加速，也没有模拟 GPU/IO 争用；下一步才是把真实 Jev PAGE 决策、等待窗口和这一层 buffer 接起来。
