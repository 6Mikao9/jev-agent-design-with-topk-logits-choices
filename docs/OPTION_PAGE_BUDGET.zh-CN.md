# Option Space 页与 Jev 调用预算

状态：设计约束已落地为 `jev_agent.option_budget.OptionPageBudget`（2026-09-24）。

## 先给结论

Jev Choice 的 **255 是 API 的硬上限**，适合用作逻辑目录页（catalog page）的
对齐上限；它不应被解释成每次都把 255 个相互竞争的动作送给 Jev。当前设计分开
三个数量：

| 层 | 默认值 | 含义 |
|---|---:|---|
| 逻辑目录页 | ≤255 | 稳定 ID、摘要和定位信息组成的虚拟页；可以与 API 上限对齐 |
| 单次决策动作 | 16 | 默认送入 Jev 的实际动作候选数；实验可比较 8/16/32 |
| 控制项预留 | 6 | `PAGE`、`REFINE`、`CLARIFY`、`REVIEW`、`STOP`、`NONE` 等出口 |

因此默认一次 Choice 最多放 `16 + 6 = 22` 项。协议允许的动作上限是
`255 - 6 = 249`，但只有在专门的高基数实验中才使用它。控制项也占用 Choice
的 255 个名额，不能把它们当作“免费按钮”。

官方 API 文档目前写明 Choice 最多 255 个选项；Jev 1.13 的上下文预算是每个请求
最多 64k tokens，`state` 加最长单个问题最多 32k tokens。我们的默认 24 KiB
分区 Context Frame 是保守的工程预算；`ContextBudget.jev_wide()` 新增 48 KiB
字节的宽配置用于实验。本地 Qwen 服务的 2048-token 限制仍只是本地推理配置，不是
把 Jev 的官方上限改成 2k，也不打算把请求推到 32k。

## Option Space 在哪里

Option Space 位于 **Open World 与 Decision Frame 之间**。目录和非驻留候选在外部
Virtual Option Space，经过检索、`PAGE/EXPAND` 或 `REFINE` 后，只有当前一轮需要的
候选进入 Resident Option Space；Shadow Option Space 只存无副作用的异步预取。

```text
Open World
   │
   ├─ Virtual catalog: Tool / Memory / File / Plan / Prediction pages
   │       └─ catalog page ≤ 255 logical entries
   │
   ├─ directory selection (small model / RAG / Jev summary choice)
   │       └─ choose page or PAGE/SEARCH/REFINE control
   │
   └─ Resident Option Space for this call
           ├─ 8/16/32 action candidates (default 16)
           └─ reserved controls: PAGE, REFINE, CLARIFY, REVIEW, STOP, NONE
                         │
                    Jev Choice
                         │
                    state transition
```

这意味着“页”有两个语义：目录页为存储与寻址单位，决策批次为模型可见单位。一个
255-entry 目录页通常会被拆成若干个 16/32-entry decision batches，不能因为它
属于同一目录页就一次性全部驻留。`VirtualOptionManager.max_resident` 仍是当前
工作集上限；默认 8 是机制原型的 resident 上限，不是 API 的 255 限制。

## 页内对象与空间隔离

每个逻辑 option 至少带有：

```text
stable option_id
page_id / parent_id
kind: tool | memory | file | plan | prediction | control
description / payload_ref
schema_version / permission_tag
revision / expires_at
materialization_cost / source
```

ToolSpace、MemorySpace、FileSpace、PlanSpace、PredictionSpace 和 ControlSpace 保持
独立页表与配额。控制项不与可执行工具混成一个语义空间；`COMMIT` 只有在候选已
通过 schema、权限、revision 和 evidence guard 后才出现。父级目录页放摘要和范围，
叶页放可提交 option；`parent_id` 为多级目录预留接口，但当前 manager 仍是同步、
单级遍历原型，不能写成已经完成多级自动寻址。

## 每次系统调用怎样切分

`OptionPageBudget` 实现以下确定性规则：

1. `catalog_pages()` 按最多 255 个逻辑条目切目录页，保留输入顺序和稳定 ID；
2. `decision_calls()` 为每个批次重复控制项，默认每批 16 个动作候选；
3. 实际总数必须满足 `len(actions) + len(controls) ≤ 255`，控制项默认最多 6 个；
4. 候选不足时仍保留 `PAGE/CLARIFY/STOP`，禁止用一个错误工具候选填空；
5. 候选描述还受字节预算限制，先按 bytes 估算可装载量，再在 8/16/32 上做实验；
6. Jev 选中 `PAGE` 后只 materialize 下一批，选中 `REFINE` 后建立子页，旧父选项
   在同一轮不可再次提交。

推荐的第一轮消融是 `decision_target ∈ {8,16,32,64}`，目录页固定 255，报告
候选命中、控制项误选、恢复率、输入 bytes、Jev latency 和调用次数。若 64 或 255
在特定任务上质量更好，也只能作为 workload-specific 设置，不能默认全局采用。

## 与 AIOS 的关系

AIOS 的公开 README 把 agent runtime 分成 kernel 与 SDK，并由 kernel 管理 LLM、
memory、storage、tool 等资源，同时处理 scheduling 和 context switch。这启发我们
把 Option Space 当作一种受 runtime 调度的资源层，而不是把工具列表直接拼进 prompt。
AIOS 并没有给出 255-entry Jev page 的结论；本项目的 255 对齐、控制项预留和
8/16/32 decision batch 是针对 Jev Choice 接口的工程假设，必须通过消融验证。

参考：[TypeSafe API reference](https://docs.typesafe.ai/api)、
[TypeSafe models](https://docs.typesafe.ai/models)、
[AIOS README](https://github.com/agiresearch/AIOS)。
