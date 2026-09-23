# Jev 原生 Agent 系统设计

**面向选择型模型的工具调用、分层记忆与自然交互**

English working title: **A Jev-Native Agent System: Tool Use, Hierarchical Memory, and Natural Interaction for Decision Models**

版本：`v0.4-design` · 初稿日期：2026-09-23 · 状态：项目进行中，设计与原型实现同步推进

作者：**刘云韬**

本项目探索如何围绕 Jev 的结构化决策接口构建完整 agent 系统。系统利用现有工具定义和执行器，由辅助小模型或扩散模型先提出完整参数或片段，Jev 选择合适的提案；当提案均不适用时，Jev 可显式选择 Top-k 回退。辅助生成模型根据当前参数前缀输出 logits，取概率最高的 k 个 token 组成动态 token 表；Jev 从这张表中选择下一 token，拼接到前缀后继续下一轮。这使回退路径在控制流程上类似大模型的下一 token 采样，同时保留 Jev 对每一步选项的决策权。系统按决策影响管理多层记忆，并根据依赖关系在任务变化后局部重规划，支持自然语言任务、澄清和修正。

项目已进入进行中阶段，当前同步推进协议设计、原型实现和基线评估。性能结果和实验结论尚未完成；文档中的运行流程、数据结构和案例仍有可能随实现反馈调整。

## 阅读入口

- [完整技术设计（中文）](docs/DESIGN.zh-CN.md)：包含投机候选与 Top-k 回退、按决策影响管理多层记忆（I1）、依据依赖局部重规划（I3），以及其余原始设想。
- [Full technical design (English)](docs/DESIGN.en.md)：英文版设计与相关工作边界。
- [独立研究问题：候选覆盖诊断（I2）](docs/CANDIDATE_COVERAGE.zh-CN.md)：区分选项难以判断、选项缺失和信息不足，讨论恢复动作如何触发。
- [Independent question: candidate coverage diagnosis (I2)](docs/CANDIDATE_COVERAGE.en.md)：英文版候选覆盖诊断。
- [备选研究路线](docs/OPTIONAL_IDEAS.zh-CN.md)：记录 I1—I6 的采纳状态；I4、I5、I6 保留为备选方案。
- [Optional research directions](docs/OPTIONAL_IDEAS.en.md)：英文版研究路线和状态。
- [GitHub 发布说明](docs/PUBLISHING.zh-CN.md)：如何公开这个文档包并保留清晰的版本记录。

## 核心设想

1. **复用现有工具生态**：读取工具 schema 和注册表，把决策结果交给已有执行器，逐步减少手写候选与接入代码。
2. **投机候选与 Top-k 回退**：优先选择完整参数或片段；Jev 可拒绝全部草案，进入由辅助生成模型 logits 产生动态 token 表、再由 Jev 逐步选择下一 token 的构造路径。
3. **可替换的候选生成器**：同时容纳自回归小模型与扩散模型，在任务、工具或业务状态变化后刷新选项。
4. **按决策影响管理多层记忆**：优先召回影响当前约束、参数来源和候选可行性的记录，冷藏未选分支。
5. **依据依赖局部重规划**：任务与环境变化后，让受影响的参数和候选失效，复用仍有效的证据，并重新判断召回的分支。
6. **自然交互**：用户输入自由文本，系统构造候选、提出必要澄清，并依据执行记录组织回复。
7. **端到端成本目标**：以任务成功率、每个成功任务成本和延迟评估系统，包括前面未采用的提案、回退构造、辅助生成、检索与重试。

## 与已有工作的关系

已有框架与社区项目已覆盖部分相关能力，例如 [Pydantic AI 的 Jev 集成](https://pydantic.dev/docs/ai/models/typesafe/)、[jev-browser](https://github.com/jkudish/jev-browser) 的浏览器决策及辅助文本生成、[ChatJev](https://github.com/erik-dunteman/ChatJev) 和 [jevchat](https://github.com/kyle-pena-nlp/jevchat) 的词表或 token 列表逐步选择、[jev-memory](https://github.com/NicolasMontone/jev-memory) 的记忆管理。因此，本设计不以“第一个 Jev agent”或“首次让 Jev 逐步选择文本”为贡献声明。本版本提出的较窄问题是：外部生成模型根据当前前缀提供 logits Top-k，Jev 保持选择权，并在粗粒度参数草案被拒绝后按需进入这条回退路径。我们在 2026-09-23 的有界检索中没有找到完全相同的公开 Jev 实现；这不等于证明全球首创，仍需扩大文献与代码检索并通过实验确认价值。详细比较见完整文档。

## 文档状态与署名

- 本方案是独立研究设计，与 TypeSafe 官方没有隶属关系。
- 作者：刘云韬；初稿日期不代表已经公开发布。
- 后续版本应记录新增机制、实现范围、结果和已知限制。
- 资料核对截至 2026-09-23；模型接口和社区实现可能继续变化。
- 项目状态：进行中；后续提交将记录接口实现、实验配置、结果和已知限制。
