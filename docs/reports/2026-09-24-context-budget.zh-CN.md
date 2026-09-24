# 分区 Context Frame 预算原型

脚本：`benchmarks/benchmark_context_budget.py`  
结果：`benchmarks/results/context-budget.json`

## 实现

新增 `ContextBudget`、`ContextSlice`、`ContextBudgetController` 和 `PackedContext`。默认规划预算为 24 KiB：

```text
pinned 3 KiB | recent 4 KiB | working 6 KiB
evidence 6 KiB | options 3 KiB | trace 2 KiB
```

控制器按 UTF-8 字节数在每个分区独立排序和装载；同一分区内优先级高的 slice 先保留。分区之间不借用预算，Pinned/required slice 放不下时直接报错，普通低优先级 slice 被记录为 dropped。输出可以直接渲染成 prompt sections，但不会自动改变 ContextResidencyManager 的 working set。

## 代理结果

| 分区 | 本次使用字节 |
| --- | ---: |
| pinned | 39 |
| recent | 46 |
| working | 37 |
| evidence | 34 |
| options | 21 |
| trace | 21 |

长历史 working slice 被丢弃，Pinned 超预算请求被拒绝；远端 **137 项测试全部通过**。

结果符合预期：预算控制器能把“谁被换出、哪个区域超限”变成可审计结果。它还没有接入实际 Jev prompt，也没有学习检索效用，因此不能说明 24 KiB 规划一定是最优。

## 后续

下一步把 `PackedContext` 接到一个小型 A/B/C workload，比较全量拼接、固定最近窗口和分区预算三种策略，测 needle recall、答案/工具正确率、P50/P95、dropped blocks 和 context churn。数值仍应允许按 workload 调整。
