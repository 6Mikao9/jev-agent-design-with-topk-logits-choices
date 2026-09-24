
## 收敛后的研究定位（2026-09-24）

本项目是面向非生成式 Decision Model 的 Jev-native agent runtime：`Open world → Virtual Option Space → Resident Option Space → Jev decision → State transition`。`PAGE/EXPAND` 增加候选覆盖，`REFINE` 降低候选粒度（完整 candidate → field → fragment → token）；Jev 始终做最终选择，helper logits 只是 refinement proposal。单点机制都有近邻；我们的候选贡献是把 decision-space virtualization、decision-preserving refinement、context residency 和 fault recovery 统一成可替换 DecisionModel runtime。新颖性范围与不可过度主张的先例见 [新颖性审计](docs/NOVELTY_AUDIT.zh-CN.md)。

实验主线使用逻辑空间 10/100/1K/10K/100K、resident K=8/16/32，在删除正确 coarse candidate 后比较 argmax、repropose、full LLM handoff、helper top1、helper topK+Jev、`+EXPAND_K`、`+BACKTRACK/LOOKUP/CLARIFY`，报告 RecoveryRate、coverage、cost、latency、state errors、side effects。BFCL coverage 仅表示 candidate availability，不等于 Jev accuracy。适用 workload 优先短字段、SQL、路径、JSON、工具参数；长篇自然语言仅作高成本实验。

详见 [Decision-Preserving Progressive Refinement](docs/DECISION_PRESERVING_REFINEMENT.zh-CN.md)。当前实现含可替换 DecisionModel 边界、OptionSpace、PagedMemoryIndex、TwoStageMemorySelector、FastLogitsHelper、Agent/orchestrator、trace、VirtualOptionManager 原型，以及 ContextResidencyManager 的 pinned/working/cold、utility aging、hysteresis 和 minimum-residency 基线；异步 prefetch、学习型 replacement、跨空间 resolver、ContextFault 与两种空间的统一调度仍待实现。

# Jev 原生 Agent 系统设计

**Jev 自然语言对话原型：外部 logits、Top-k token 选择与 Agent 工具调用**

English working title: **A Jev-Native Agent System: Tool Use, Hierarchical Memory, and Natural Interaction for Decision Models**

版本：`v0.6-prototype` · 初稿日期：2026-09-23 · 状态：原型已实现，项目进行中

作者：**匿名作者**

本项目探索如何围绕 Jev 的结构化决策接口构建完整 agent 系统。系统利用现有工具定义和执行器，由辅助小模型或扩散模型先提出完整参数或片段，Jev 选择合适的提案；当提案均不适用时，Jev 可显式选择 Top-k 回退。辅助生成模型根据当前参数前缀输出 logits，取概率最高的 k 个 token 组成动态 token 表；Jev 从这张表中选择下一 token，拼接到前缀后继续下一轮。这使回退路径在控制流程上类似大模型的下一 token 采样，同时保留 Jev 对每一步选项的决策权。系统按决策影响管理多层记忆，并根据依赖关系在任务变化后局部重规划，支持自然语言任务、澄清和修正。

项目已包含可运行原型和 Jev Choice 接口：外部生成模型提供下一 token logits，选择器从 Top-k 动态 token 表中选择并继续生成。**当前保存的完整对话和速度实验使用 `local_top1_proxy`（取 helper 的最高分 token），没有使用真实 Jev 逐 token 决策。**真实 Jev 仅完成了一次工具候选接口测试；真实 Jev 长回答的质量和速度仍待评测。外部模型可替换，Qwen3.5-0.8B 是当前 helper 实现之一。

研究范围是 Jev 与外部 logits Top-k 动态候选协作的自然语言生成方案。已有有界检索记录保留在设计文档中；本次代码发布记录具体实现和实验边界，不据此声称已验证“首个真实 Jev 流畅对话系统”。

## 与固定词表生成的区别

固定词表方案把字符、词或短语预先放入选项，再让 Jev 重复选择。它适合验证“Jev 能否连续选择”，但可能受到词表覆盖、未登录词、分词边界、组合效率和上下文连贯性的限制；词表没有覆盖的表达只能近似拼接，输出是否自然也依赖词表设计。

本项目让外部生成模型根据已经选中的文本前缀动态计算 logits，并把概率最高的 token 组成当前轮 token 表。Jev 选择一个 token 后，系统把它加入前缀，再计算下一轮 token 表。这样候选来自语言模型的上下文分布，可以组合预先没有枚举的词、缩写和句子结构，目标是让 Jev 参与每一步决策，同时保留正常自然语言对话能力。流畅度、成本和错误率仍需用公开代码和统一基线实测。

## 阅读入口

- [完整技术设计（中文）](docs/DESIGN.zh-CN.md)：包含投机候选与 Top-k 回退、按决策影响管理多层记忆（I1）、依据依赖局部重规划（I3），以及其余原始设想。
- [开放工具参数输入协议](docs/ARGUMENT_INPUT_PROTOCOL.zh-CN.md)：小模型提案、Jev 主动 `REFINE`/`REPROPOSE`、多字段并行和最终校验边界。
- [实时交互 Agent](docs/REALTIME_CLI.zh-CN.md)：`python -m jev_agent.cli` 启动的 workspace 内 REPL，支持 scripted 或真实 Jev chooser。
- [Full technical design (English)](docs/DESIGN.en.md)：英文版设计与相关工作边界。
- [独立研究问题：候选覆盖诊断（I2）](docs/CANDIDATE_COVERAGE.zh-CN.md)：区分选项难以判断、选项缺失和信息不足，讨论恢复动作如何触发。
- [Independent question: candidate coverage diagnosis (I2)](docs/CANDIDATE_COVERAGE.en.md)：英文版候选覆盖诊断。
- [备选研究路线](docs/OPTIONAL_IDEAS.zh-CN.md)：记录 I1—I6 的采纳状态；I4、I5、I6 保留为备选方案。
- [Optional research directions](docs/OPTIONAL_IDEAS.en.md)：英文版研究路线和状态。
- [GitHub 发布说明](docs/PUBLISHING.zh-CN.md)：如何公开这个文档包并保留清晰的版本记录。
- [面向 Jev 的分层页表记忆](docs/JEV_MEMORY_PAGING.zh-CN.md)：两阶段页表选择、摘要、LRU/RAG 组合与评测计划。
- [0.8B raw logits 与 KV cache](docs/FAST_LOGITS.zh-CN.md)：无 softmax、单 token cache decode 和实测基准。
- [Jev 本地工具目录](docs/TOOL_CATALOG.zh-CN.md)：安全文件/JSON/shell、人工复核和 MCP 形状适配。
- [框架、benchmark 与扩散方向资料](docs/RESEARCH_CATALOG.zh-CN.md)：官方来源、许可证边界和隔离评测建议。
- [选项空间、状态机与可展开记忆](docs/OPTION_SPACES_STATE_MACHINE.zh-CN.md)：工具/记忆/预测分区、错误记忆和 88 轮验证队列。
- [Virtual Option Space 技术报告](docs/VIRTUAL_OPTION_SPACE_TECHNICAL_REPORT.zh-CN.md)：resident/non-resident 选项、OptionFault、页表、working set、prefetch、异构空间与实验矩阵。
- [Option Space 页与调用预算](docs/OPTION_PAGE_BUDGET.zh-CN.md)：255-entry 目录页、控制项预留、8/16/32 decision batch、Jev 上下文上限与 AIOS 启发。
- 新颖性边界已在内部审计：公开定位只主张受限 DecisionModel 的选项空间虚拟化组合，不把 Jev agent、动态词表或上下文管理器写成绝对首创。
- [Context/Option budget 离线对照](docs/reports/2026-09-24-budget-ablation.zh-CN.md)：24/48 KiB 分区与 8/16/32/64 批次的容量基线。
- [JEV 研究笔记](docs/JEV_RESEARCH_NOTES.zh-CN.md)：两阶段记忆、并行预测、超远捞针评测与失败边界。

## 核心设想

1. **复用现有工具生态**：读取工具 schema 和注册表，把决策结果交给已有执行器，逐步减少手写候选与接入代码。
2. **投机候选与 Top-k 回退**：优先选择完整参数或片段；Jev 可拒绝全部草案，进入由辅助生成模型 logits 产生动态 token 表、再由 Jev 逐步选择下一 token 的构造路径。
3. **可替换的候选生成器**：同时容纳自回归小模型与扩散模型，在任务、工具或业务状态变化后刷新选项。
4. **按决策影响管理多层记忆**：优先召回影响当前约束、参数来源和候选可行性的记录，冷藏未选分支。
5. **依据依赖局部重规划**：任务与环境变化后，让受影响的参数和候选失效，复用仍有效的证据，并重新判断召回的分支。
6. **自然交互**：用户输入自由文本，系统构造候选、提出必要澄清，并依据执行记录组织回复。
7. **端到端成本目标**：以任务成功率、每个成功任务成本和延迟评估系统，包括前面未采用的提案、回退构造、辅助生成、检索与重试。

## 与已有工作的关系

已有框架与社区项目已覆盖部分相关能力，例如 [Pydantic AI 的 Jev 集成](https://pydantic.dev/docs/ai/models/typesafe/)、[jev-browser](https://github.com/jkudish/jev-browser) 的浏览器决策及辅助文本生成、[ChatJev](https://github.com/erik-dunteman/ChatJev)、[jevchat](https://github.com/kyle-pena-nlp/jevchat) 和 [jev-bot](https://github.com/nssmd/jev-bot) 的不同形式逐步文本输出、[jev-memory](https://github.com/NicolasMontone/jev-memory) 的记忆管理。因此，本项目不以“第一个 Jev agent”或“首次让 Jev 逐步选择文本”为贡献声明。本版本记录的较窄原型差异是：外部生成模型根据当前前缀提供 logits Top-k 动态 token 表，再由 Jev 逐步选择并生成连贯自然语言。我们在 2026-09-23 的有界检索中没有找到完全相同的公开实现；这不等于证明全球首创，仍需公开代码、配置和基线结果。

## 文档状态与署名

- 本方案是独立研究设计，与 TypeSafe 官方没有隶属关系。
- 本仓库不公开作者身份；初稿日期不代表已经公开发布。
- 后续版本应记录新增机制、实现范围、结果和已知限制。
- 资料核对截至 2026-09-23；模型接口和社区实现可能继续变化。
- 项目状态：进行中；后续提交将记录接口实现、实验配置、结果和已知限制。

## 可运行原型

[原始回答示例](benchmarks/examples/dialogue-proxy.md)保留输入和逐字输出，明确标注代理来源，包含小模型在冲突题中把“想要”改成“必须”的失败细节。

当前仓库已经包含第一版 Python 原型：

- `jev_agent/`：工具候选、schema 校验、依赖感知记忆、页表记忆第一版、Jev Choice 适配器和 Top-k token 回退。
- `benchmarks/`：合成控制流、BFCL 候选覆盖、Qwen3.5/Qwen3.8 同上下文比较、`END_DIALOGUE` 对话 trace 和速度拆分。
- `tests/`：控制流、工具目录、KV cache 和并发候选的边界测试。
- `pyproject.toml`：核心包及可选 Transformers/Torch 依赖。

运行基础测试：

```powershell
python -m unittest discover -s tests -v
```

实现与首轮结果见[原型实现与实测](docs/IMPLEMENTATION_RESULTS.zh-CN.md)。已知 Jev 缺陷对应的 state engineering、人工复核出口、确定性工具路由和 helper 优化见[JEV 限制与护栏](docs/JEV_LIMITATIONS_AND_GUARDRAILS.md)。

`benchmarks/results/` 用于本地完整结果；可公开的小体量回答样例位于 `benchmarks/examples/`。模型权重与运行时密钥不进入 Git。



## 统一运行时定位（DecisionModel 与双重虚拟化）

系统抽象为可替换的 `DecisionModel: D(s,O) -> P(O)` backend；Jev 是当前原型 backend，未来可替换 Mock/Oracle 或其他 typed decision backend。Open World 通过 Virtual Option Space 管理 resident options，通过 Virtual Context Space 管理 resident context blocks，随后驱动 Decision Model 与 state transition。PAGE/EXPAND 扩大候选覆盖，REFINE 降低候选粒度，ContextFault 触发二阶段 context paging，REVISION/INVALIDATE 保持一致性。

Context 分为 Pinned、Working、Cold 三层。Context block 元数据包括 `block_id/summary/raw_ref/revision/dependencies/last_access/access_count/utility/type/size/pinned`。按类型 aging：Pinned 不老化，任务状态慢老化，观察与 transient retrieval 快老化；utility aging 根据实际决策用途更新。采用 hysteresis、minimum residency、working-set history 与 phase-aware anti-thrashing。memory/RAG 在此是 context residency policy，而非普通“给模型找资料”。runtime 不依赖跨请求 prefix/KV reuse，允许 aggressive context mutation；这不等于声称 Jev backend 完全没有 KV cache。贡献边界是 Virtual Option + Context virtualization、decision-preserving refinement、fault/recovery/consistency 的组合，不声称各组件单点新颖。
## Context Space 与 Option Space 的位置模型

下面这张图描述当前 runtime 的空间边界。它区分了“存在哪里”和“本次 Jev 请求看见什么”；冷数据仍可寻址，但不会因为存在于索引中就自动进入当前请求。

```text
Open World / 新事件
        │
        ├── 用户约束、权限、预算、task revision
        │       └── Control + Pinned Context（默认保留，不参与淘汰）
        │
        ├── 最新观察、工具结果、当前阶段状态
        │       └── Working Context（受 max_working、aging、hysteresis 管理）
        │
        ├── 被淘汰的旧 block、未选分支、历史轨迹
        │       └── Cold Context / Raw Evidence（保留 page_id，可按需回读）
        │
        ├── 工具、参数、预测 token 的逻辑全集
        │       ├── Virtual Option Space：非 resident 页/候选目录
        │       ├── Resident Option Space：本次 Jev 可见的工具/候选
        │       └── Shadow Option Space：异步预取，验证后才 promote
        │
        └── 执行 trace、错误摘要、旧 revision、冲突证据
                └── Trace / Evidence Space（默认不自动注入，需检索与校验）

                  ┌────────────── 当前 Decision Frame ──────────────┐
                  │ Pinned constraints │ Recent state │ Working blocks │
                  │ Selected evidence │ Resident options │ Controls   │
                  │ PAGE / REFINE / CLARIFY / STOP / COMMIT         │
                  └──────────────────────┬─────────────────────────┘
                                         │
                                  DecisionModel / Jev
                                         │
                                  State transition
```

### 放入和移出的规则

| 对象 | 新对象进入哪里 | 失去当前优先级后 | 再次需要时 |
| --- | --- | --- | --- |
| 用户明确约束、权限、任务不变量 | `Pinned Context`（由调用方显式标记） | 不自动淘汰；revision 改变时旧版本失效 | 读取当前 revision |
| 最新事件、工具结果、阶段状态 | 先注册到 context index，再由 `refresh/rebuild` 进入 `Working` | 留在 index，移出 working 后成为 `Cold` | lexical/utility/phase 或 refresh coordinator 重新换入 |
| 历史对话、未选分支、原始证据 | `Cold Context` 或 `PagedMemoryIndex` | 永久保留其稳定 ID，可能被标为 stale | 先目录召回，再有界原文读取和 revision 校验 |
| 工具/参数候选 | 进入 virtual page/catalog | 不在 resident page 中，不能直接提交 | `PAGE/EXPAND` 或候选检索后 materialize |
| 异步候选页 | `Shadow Option Space` | 过期、失败或 revision 不匹配时丢弃 | 重新 prefetch；只有显式 promote 才进入 resident |
| 错误摘要与执行 trace | 外部 trace/evidence store | 默认不污染当前上下文 | 作为受控证据候选读取，不能直接当事实 |

当前代码已经实现 `Pinned/Working/Cold`、稳定 ID、revision/stale guard、页表有界读取、受限 `ContextMaterializer`、`ContextEvidenceFallback`、分区 `ContextBudgetController` 和 option shadow buffer；多级目录、自动 trace 摘要和统一跨空间调度仍是后续工作。`ContextRefreshCoordinator` 是可关闭的实验策略，不改变这张边界图：它只负责从目录候选中验证并提交少量 working blocks。

### Working → Cold 的当前规则与预算

当前实现没有“过了固定时间就自动变旧”的 TTL。一次 `refresh/rebuild(query)` 会按下面的分数重新计算候选：

```text
score(block) = lexical_overlap(query, summary)
             + utility_score × exp(-aging_rate × steps_since_last_useful)
             + phase_bonus
```

现有 working block 会继续作为候选；`minimum_residency_steps` 可以暂时保护它，`hysteresis` 要求新候选明显胜过当前最差 block 才替换。被替换的 block 不会删除，只是从 `_working` 移出并出现在 `cold()`；它仍可通过稳定 ID、目录检索或 raw evidence fallback 找回。Pinned block 不参与 working 上限，revision 变化的旧 block 则被移出并标记 stale。新 block 先进入 index，只有一次 refresh/rebuild 选中后才进入 Working；当前调用方没有把所有新事件自动放入 Working。

当前是分散的局部上限，不是统一的 Context Space budget controller：

| 区域/组件 | 当前默认硬上限 | 超出时的行为 |
| --- | ---: | --- |
| Working Context | 8 个非 pinned block（`max_working`） | 按 score、aging、hysteresis 替换，落入 Cold |
| Context 正文 materialization | 每 block 16 KiB | 拒绝读取 |
| Memory page 粗选 | 16 个候选页 | 其余不送 Jev |
| Memory page 读取 | 8 页、单页 8 KiB、总计 32 KiB | 有界读取失败 |
| Grounded evidence | 4 页、单页 8 KiB、总计 16 KiB | 阻止工具提交 |
| Jev memory 请求 | 24 KiB request body；读取数量 2/4/8 | 报告 `context_budget_exceeded` |
| Refresh verifier | 最多 4 个 block 并发，默认每 phase 2 次、cooldown 1 步 | suppress 或停止刷新 |
| Shadow Option page | 2 页、最多 32 个 option | 过期或超限时丢弃 |

`GroundedArgumentAgent` 还有 24 KiB 的最终 state 上限；目前 context block 主要注入摘要，materializer 正文由 evidence fallback 单独读取，因此不能把这个数字误解为“所有 Context Space 已经有 24 KiB 的统一分区预算”。

如果现在要冻结一版可实验的 Context Frame，保留 24 KiB 作为窄基线，并使用
`ContextBudget.jev_wide()` 做 48 KiB 的宽配置对照。两者都是 UTF-8 字节预算，不是
token 上限；宽配置仍刻意远低于 Jev 的 32k-token `state + longest question` 约束。
下面是窄基线的规划预算：

| 分区 | 建议预算 | 溢出动作 |
| --- | ---: | --- |
| Pinned constraints | 3 KiB | 报告冲突或要求压缩，绝不静默淘汰 |
| Recent events | 4 KiB | 只保留最近事件，旧事件转 Cold |
| Working blocks | 6 KiB | 按 utility/phase 替换 |
| Selected raw evidence | 6 KiB | 减少页数或进入 `CLARIFY/REVIEW` |
| Resident tool/options | 3 KiB | `PAGE/EXPAND`，不把所有工具塞入请求 |
| Error/trace hints | 2 KiB | 外置存储，按需召回 |
| **合计（不含 system prompt）** | **24 KiB** | 各区独立记账，禁止互相静默侵占 |

这套规划的目的，是让每次实验都能回答“哪一块占满了、谁被换出、换出后能否找回”。最终数值要用 page hit、needle recall、任务正确率、P50/P95 和上下文 churn 共同调节，不能只按 token 节省判断。

### 参数先验

`jev_agent.parameter_prior.ParameterPrior` 可根据历史成功调用生成参数候选，并保留来源、置信度和 revision。它不会替代 Jev 决策，且带有过期校验。
