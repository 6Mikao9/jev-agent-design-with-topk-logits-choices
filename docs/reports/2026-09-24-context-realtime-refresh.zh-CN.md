# 实时上下文替换基线

脚本：`benchmarks/benchmark_context_realtime.py`  
报告数据：`benchmarks/results/context-realtime-refresh-4-events.json`

## 设计

用 `deploy → rollback → audit → deploy(revision=2)` 四个事件驱动同一个逻辑上下文。固定一个 pinned 安全约束和最多两个非 pinned working blocks。比较：启动后不刷新（static）、每个事件刷新（refresh）、带一步最小驻留和迟滞的刷新（refresh_hysteresis）。刷新通过 `ContextResidencyManager.refresh()` 显式应用 block revision 更新，再重建 resident set。

## 结果

实际运行结果如下：

| 模式 | 阶段命中率 | cold faults | working 替换次数 | 最大非 pinned resident |
| --- | ---: | ---: | ---: | ---: |
| static | 25% | 3 | 0 | 1 |
| refresh | 100% | 0 | 3 | 1 |
| refresh_hysteresis | 100% | 0 | 3 | 1 |

三种模式都处理了 1 次 revision 更新；refresh 两种策略在每个阶段都加载正确 block，且没有超过上限。结果比预期好：显式实时刷新完全消除了本合成轨迹的 cold fault；迟滞在这条短轨迹上没有额外减少替换次数，不能据此宣称它能解决长期 thrashing。这里的“实时”指 runtime 在每次事件时重组当前上下文，不对 Jev 后端是否复用跨请求 cache 做推断。

## 边界

这是上下文驻留与 revision guard 的控制实验，不是 Jev 质量或网络延迟实验。后续需要把事件流接到真实工具轨迹，加入 context fault、异步摘要和 memory page 回读成本。
