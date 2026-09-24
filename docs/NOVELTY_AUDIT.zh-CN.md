# 新颖性与先例审计

**检索日期：2026-09-24。** 本轮检查了 arXiv、ACL、USENIX/SOSP/OSDI/MLSys 相关公开论文，以及 GitHub、Jev 官方文档和社区实现。检索不是对全球未发表工作的证明；以下结论只约束我们能公开、可复核地支持的表述。

## 结论摘要

用户的判断有一部分很可能是对的：我们目前没有找到一个**系统级、可复现、面向受限非生成式决策模型**的 runtime，把逻辑选项空间做成 demand-paged resident set，并同时定义 `PAGE/EXPAND/REFINE/INVALIDATE`、上下文驻留和故障恢复。Jev 社区已有的 agent/memory 项目大多是应用、记忆库或 harness；它们不能自动等同于本项目的统一 runtime。

但“玩具级别”不应写进论文，也不能把“没有找到完全相同系统”写成绝对的“世界首个”。更稳妥的定位是：**据我们检索，这是首个我们发现的、把这些机制统一为一个可替换 DecisionModel runtime 并提供公开原型和受控评测的工作。** 这允许我们主张系统级深度，同时不否认相邻工作的局部先例。

## 主张边界

| 方向 | 已发现的近邻 | 可以主张的精确版本 | 不应主张 |
| --- | --- | --- | --- |
| 决策空间虚拟化 | ToolChain*、AutoTool/分层工具选择、RS-Claw、Pichay demand paging | “据我们检索，尚未发现把 bounded non-generative decision model 的逻辑 option space 作为可分页资源，并统一 resident set、PAGE/REFINE/INVALIDATE 语义的 runtime。” | 首个分页、首个分层工具选择、首个动态 action space |
| Jev 无跨请求缓存假设的上下文管理 | MemGPT/Letta、CMV、RAPTOR/GraphRAG、Pichay、llm-mmu、jev-memory | “提出不依赖跨请求 prefix/KV 命中、面向 DecisionModel 的 context residency 与 fault recovery 组合。” | 首个动态上下文管理器；Jev 一定没有内部 KV cache |
| 动态 token 表与 Jev | AnyJev、Mini-Jev、受限词表解码、RLCD、DynaSpec/SpecVocab | “实现 helper logits → 动态候选表 → Jev 逐 token 选择，并带 EOS/回退/工具协议；在我们的检索范围内未见完全相同的 Jev 集成。” | 首个动态词表、首个 speculative decoding、首个 logits 辅助生成 |
| Jev-native agent | Jev-Mem、jev-memory、JevHarness、REFLEX、Hermes Jev Skills、官方/社区工具选择示例 | “提供公开、可运行、系统级的 Jev-native runtime 原型，并把选项与上下文双重虚拟化、故障恢复和评测放在同一接口中。” | 首个 Jev agent、首个 Jev memory、社区工作是‘玩具’ |

## 推荐论文表述

> To our knowledge, this is the first runtime we found that treats a bounded non-generative decision model's logical option space as a virtualized, demand-paged resource, with explicit resident-set, PAGE/REFINE/INVALIDATE semantics, and cache-agnostic context residency. We instantiate the runtime with Jev, while keeping the DecisionModel backend replaceable.

中文可写为：

> 据我们检索，这是首个我们发现的、将有界非生成式决策模型的逻辑选项空间作为可虚拟化、按需分页资源处理的 runtime，并明确给出 resident set、PAGE/REFINE/INVALIDATE 语义以及不依赖跨请求缓存命中的上下文驻留机制。我们用 Jev 实例化该 runtime，但不把 Jev 写死为系统定义。

“首个”必须限定为检索范围、日期和组合对象；摘要、标题和结论中不要写成未经限定的全球首创。对于动态 token 表，使用“我们未找到完全相同的 Jev 集成”比“首个动态词表”更可复核。对于 Jev-native agent，系统级范围和公开实验深度可以作为区分维度，但不要贬低先例。

## 关键近邻与链接

- [AnyJev](https://github.com/nokia-applied-research/AnyJev)、[Mini-Jev](https://github.com/r-ms/mini-jev)：把语言模型包装为 Jev-style typed decision 的实现；不是本项目的双空间 runtime。
- [Jev-Mem](https://github.com/libingzheren/Jev-Mem)、[jev-memory](https://github.com/NicolasMontone/jev-memory)、[JevHarness](https://github.com/TianyuCodings/JevHarness)：说明 Jev agent、memory、harness 已有先例，也说明我们需要用系统边界区分贡献。
- [REFLEX with Jev](https://arxiv.org/abs/2609.26532)、[Hermes Jev Skills](https://github.com/kerpopule/hermes-jev-skills)：更直接地证明“Jev 作为 agent 决策层/技能路由器”已经有人做；它们没有在我们检索到的材料中采用本项目的双空间 demand paging 与 `PAGE/REFINE/INVALIDATE` 语义。
- [Pichay: demand paging for LLM context windows](https://arxiv.org/abs/2603.09023)、[CMV](https://arxiv.org/abs/2602.22402)：上下文虚拟化/分页的相邻系统工作。
- [ToolChain*](https://arxiv.org/abs/2310.13227)：层次工具选择的相邻工作。
- [AIOS](https://github.com/agiresearch/AIOS)：agent OS、调度和 context switch 的系统启发；不是本项目的 bounded decision option virtualization。

## 这对顶会定位意味着什么

工作量和证据仍决定主张能否站住。最有价值的不是再添加“第一”字样，而是证明组合确实必要：

1. 无虚拟化、固定 resident、检索 top-k、分层候选和完整 handoff 的对照；
2. `PAGE`（横向覆盖）与 `REFINE`（纵向粒度）以及 revision/invalidation 的消融；
3. 无 oracle locator 的 20--100 步 decision-dense workload；
4. 真实 Jev 的 missing detection、page localization、recovery success 和端到端 success 分开报告；
5. 公开配置、失败样例、延迟长尾、成本和可复现脚本。

当前原型可以诚实地称为“系统级、可运行的 Jev-native runtime prototype”；只有上述实验补齐后，才适合把“first system we found”升级为论文主结论。
