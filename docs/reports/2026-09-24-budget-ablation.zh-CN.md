# Round 19：Context 与 Option batch 离线对照

## 范围

脚本：`benchmarks/benchmark_budget_ablation.py`  
结果：`benchmarks/results/budget-ablation.json`

这是一个容量和调用扇出基线，不调用 Jev，也没有模拟 Jev 的语义判断。它只回答：
不同字节预算能保留多少已选 slice，以及同一个 255-entry 目录在不同 decision batch
下需要几次有界调用。

## Context 结果

| profile | budget | packed | dropped | late needle |
|---|---:|---:|---:|---:|
| narrow_24k | 24,576 B | 20,870 B | 43 | 否 |
| wide_48k | 49,152 B | 33,810 B | 1 | 是 |

合成 evidence 区把 `needle=late-fact` 放在靠后位置，并没有给它额外优先级。24 KiB
按分区先丢掉后面的 evidence，48 KiB 能保留该 block。这个结果支持“宽预算值得测”，
但不等于真实 RAG/页表召回率提升；真实检索如果先漏掉 block，增大 prompt 也救不回来。

## Option batch 结果

固定 255 个逻辑候选和 6 个控制项：

| 动作候选/批 | 决策批次数 | 最大线协议项数 | 最后候选所在批 |
|---:|---:|---:|---:|
| 8 | 32 | 14 | 31 |
| 16 | 16 | 22 | 15 |
| 32 | 8 | 38 | 7 |
| 64 | 4 | 70 | 3 |

所有批次都低于 Jev Choice 的 255 上限。更大的批次减少了需要翻页的次数，但可能增加
候选混淆和单次请求的描述字节；本脚本没有能力判断哪一个批次的 Jev 选择质量最好。

## 相对预期

**容量行为符合预期。** 宽预算明显减少了丢弃并恢复了合成末尾 needle，批次增大也
按比例减少调用数。**质量仍未知。** 下一步必须在受控真实 Jev workload 上重复
8/16/32（必要时 64）与 24/48 KiB，记录动作正确率、PAGE/CLARIFY 误选、调用数和
P50/P95，而不能把这个离线结果写成端到端收益。

