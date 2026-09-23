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
