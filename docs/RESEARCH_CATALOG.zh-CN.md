# Agent 框架、评测基准与并行文本生成：官方资料目录

资料核对日期：2026-09-23。此目录用于 Jev 原生 agent 原型的设计取舍，不是对任何项目的代码审计或法律意见。链接优先指向项目官方文档、作者仓库或论文。软件许可证不自动覆盖数据集、网站镜像、模型权重、依赖项、商标或托管服务；复用前应按实际固定的 tag/commit 和每个子组件分别核对。

## 结论摘要

- **协议互操作**：将 MCP 视为外部工具/资源的传输和发现协议；Jev 的选择、候选、拒绝、恢复和执行语义应留在自己的中立接口层。协议本身不是 agent 策略，也不提供沙箱保证。
- **值得吸收的工程原语**：LangGraph 的可检查状态、持久化/恢复和人工中断；Pydantic AI 的类型化工具 schema、依赖注入、输入校验。作为设计参考或可选适配，不必让 Jev 运行时绑定某一框架。
- **近期最贴近的评测**：ToolSandbox 用本地可变世界状态、对话、工具隐式依赖和有序里程碑衡量真实工具行为；BFCL 用于测函数选择、参数和调用格式。两者互补，不能把模型排行榜分数直接当作 Jev 系统分数。
- **浏览器基准**：BrowserGym 提供统一环境；WebArena 提供可复现的多站点任务。运行负担、浏览器攻击面和各子基准数据/站点许可使它们适合独立、容器化的扩展评测，不应混入轻量单元评测。
- **文本生成路线**：AR speculative decoding 的目标是保持目标模型分布而并行验证草稿；这与 Jev 每步做选择的目标不同。扩散语言模型以多个位置并行去噪，适合产生完整参数、片段或多位置备选，但不能直接当作标准 next-token logits 源。必须分别报告模型质量、生成延迟、JeV 决策数和端到端成功率。

## 框架和协议

| 项目 | 官方来源与范围 | 许可证/适用范围 | 隔离评测判断 | 对 Jev 的适配建议 / 不应照搬 |
|---|---|---|---|---|
| **MCP (Model Context Protocol)** | [协议规范](https://modelcontextprotocol.io/specification/2025-06-18)、[官方文档](https://modelcontextprotocol.io/docs/concepts/tools)、[官方 Python SDK](https://github.com/modelcontextprotocol/python-sdk)。规范定义 host/client/server 角色、工具、资源、提示和传输；SDK 可运行 stdio、Streamable HTTP 等客户端/服务端。MCP 规范持续演进，SDK 仓库明确记录 2026 规范及版本迁移。 | 规范仓库的规范/代码授权经历 MIT 到 Apache-2.0 的迁移，历史贡献可能仍是 MIT；非规范文档为 CC-BY-4.0。Python SDK 当前为 MIT。应以固定版本文件头为准。MCP 是互操作规范，不含具体执行政策、工具可信度或隔离环境。 | **协议适配可隔离**：连本机 mock MCP server，禁网、禁秘密、限进程/时长；只对本地 schema 和响应做回放。真实第三方 server 属不可信外部代码，不能因 MCP 合规而视为安全。 | 把 Jev 的工具注册表映射为 MCP `tools/list` 与 `tools/call` 的薄适配器；保留 Jev 专有的候选拒绝/重选/恢复语义。不要将 MCP tool 描述原样当可信指令；做名称来源、参数 schema、超时、结果大小和权限校验。不要把某个协议 revision 写死到核心对象模型。 |
| **LangGraph** | [官方仓库](https://github.com/langchain-ai/langgraph)、[持久化文档](https://docs.langchain.com/oss/python/langgraph/persistence)、[HITL 文档](https://docs.langchain.com/oss/python/langgraph/interrupts)。定位为低层、有状态的长运行工作流/agent 编排，强调 checkpoint、恢复和人工中断。 | 仓库 MIT。核心开源包与 LangSmith/LangGraph 部署等配套产品不是同一许可边界；逐项核对。 | 可通过小型确定性图和内存/本地文件 checkpoint 隔离评测；评测“恢复后状态相同”较容易。若接托管平台或远程存储，则不是离线隔离。 | 借鉴显式状态快照、暂停原因和恢复输入；Jev 的工具调用/候选状态应保留可序列化、可重放。不要直接移植其整套图运行时、消息 reducer 或产品部署抽象，避免项目变成 LangGraph 的包装层。 |
| **Pydantic AI** | [官方概览](https://pydantic.dev/docs/ai/overview/)、[工具文档](https://github.com/pydantic/pydantic-ai/blob/main/docs/tools.md)、[依赖注入文档](https://pydantic.dev/docs/ai/core-concepts/dependencies/)。Python typed agent SDK：工具函数签名生成 schema；依赖通过 RunContext 注入；可验证结构化结果，也支持 MCP toolset。 | 仓库 MIT。文档覆盖的 provider、网关和 observability 产品可能有各自服务条款；provider API/模型权重亦独立。 | 很适合以 fake model、纯函数工具和注入的临时数据库搭建本地测试；真实 provider 调用不再是隔离评测。 | 采用“执行时依赖显式注入 + schema 类型约束 + validation failure 可观测”作为 Jev adapter 的设计参考；模拟 Jev / helper 时可以共享同一执行器。避免把 Pydantic 类型系统误认为安全边界，也不要把校验失败后无限重试、将模型生成当事实等默认行为直接复制。 |

## 工具使用与交互评测

| 项目 | 官方来源与评测范围 | 许可证与可比性 | 隔离评测判断 | 对 Jev 的适配建议 / 不应照搬 |
|---|---|---|---|---|
| **BFCL (Berkeley Function-Calling Leaderboard)** | [官方 leaderboard](https://gorilla.cs.berkeley.edu/leaderboard)、[作者仓库 Gorilla](https://github.com/ShishirPatil/gorilla)、[BFCL 论文](https://openreview.net/forum?id=2GmDdhBdDk)。版本从 AST/函数参数匹配扩展到多轮、多步及 agentic 评测；包括格式、函数选择、执行正确性等不同切面。 | Gorilla 仓库 Apache-2.0；BFCL 的任务、数据、API 内容与 leaderboard 规则应根据所用版本/条目单独核对。排行榜会更新，版本之间不可默认直接比较。 | **适合离线候选/调用评测**：固定样本、工具定义和 evaluator 后，在本地 mock 函数执行；含 live API 的子集单独标记并禁入严格离线分数。 | 用于量化 Jev 是否选到有效工具/参数、helper 候选覆盖率、Top-k 中金标准是否存在；区分“候选没有正确答案”和“Jev 选错答案”。不要把 BFCL 单轮/AST 正确率外推成会话完成率、可靠性或自然交互质量。 |
| **τ-bench / τ²-bench（当前仓库也在发展为 τ³）** | [官方仓库与变更记录](https://github.com/sierra-research/tau2-bench)、[τ² 论文](https://arxiv.org/abs/2506.07982)、[τ-bench 论文](https://arxiv.org/abs/2406.12045)。以 user-agent-tool 的多轮交互和领域规则衡量任务完成；τ²强调双控制环境（agent 与用户侧状态/策略）。当前仓库继续加入知识和语音域。 | 仓库 MIT；benchmark 任务/域/版本随 release 变化。官方仓库已记录 1.0.1 对 banking_knowledge 修题、旧分不可比的例子；必须 pin 版本、领域和 grader。 | 传统 retail/airline/banking mock domain 可隔离；模型用户模拟器及检索/语音实时 provider 会引入随机性、网络和费用，须作为独立运行模式。 | 适用于评估 Jev 在政策约束、用户偏好、多轮澄清、数据库最终状态上的表现。优先固定模拟用户和域状态，分别记录 pass^k / 任务状态与每轮成本。不要混用“历史 τ-bench”“τ²”或当前分支而不写明版本；避免只用最终文本 judge。 |
| **ToolSandbox** | [Apple 作者实现](https://github.com/apple-aiml-research/ToolSandbox)、[论文](https://arxiv.org/abs/2408.04682)、[Apple 研究说明](https://machinelearning.apple.com/research/toolsandbox-stateful-conversational-llm-benchmark)。本地状态数据库 + 多角色对话；工具有隐式依赖，任务可要求澄清/拒绝；通过状态快照及有序 milestone DAG 评估任意轨迹。仓库有限提交历史，属于随论文发布的研究实现。 | Apple 软件自有许可（非 MIT/Apache）；保留通知及 Apple 商标限制，子组件见 ACKNOWLEDGEMENTS。复用代码前阅读许可和子依赖。论文/benchmark 数据条款另行确认。 | **高度适合作为隔离评测范式**：工具能只操作其内存状态；agent 可用 fake/local 模型；关掉 RapidAPI/外部模型用户模拟，避免其原始示例使用 host Python console 的风险。 | 优先吸收状态快照、逐步 milestone、必要信息缺失、工具可见性、扰动工具描述等评测设计，重写少量贴近 Jev 的 toy domain；评估提案失败/澄清/执行后状态。不要照搬其 Apple license 下的代码、其特定移动设备情景或 host 上执行策略；项目 README 明确当前执行环境不是 OS sandbox。 |
| **BrowserGym + WebArena** | [BrowserGym 官方仓库](https://github.com/ServiceNow/BrowserGym)、[BrowserGym 论文](https://arxiv.org/abs/2412.05467)、[WebArena 官方仓库](https://github.com/web-arena-x/webarena)、[WebArena 论文](https://arxiv.org/abs/2307.13854)。BrowserGym 统一 Gymnasium 风格 observation/action 接口并封装 MiniWoB、WebArena、VisualWebArena、WorkArena 等；WebArena 在自托管的商店、论坛、代码协作和 CMS 站点评估长程任务。 | BrowserGym Apache-2.0。WebArena canonical repo Apache-2.0；各站点镜像、内容和配套 benchmark 的数据/商标许可需分别核对。 | **可隔离但成本较高**：BrowserGym + Playwright + 浏览器 + 自托管 WebArena，限定容器网络/文件/时长。浏览任务浏览器本身可被恶意网页诱导；禁公网，快照初始化，服务仅绑定本机。 | 如果 Jev 的目标确实包含 browser action，先用 BrowserGym 单独做外层 benchmark，观察候选选择/恢复对 task success 的影响；早期优先 MiniWoB 或少量固定 WebArena。不要将 DOM/text action 与截图 click 混为同一能力指标，也不要跨基准直接比较分数。没有浏览器需求时不应把它加进核心运行时。 |

### 建议的 Jev 评测分层

1. **离线 schema/候选层**：BFCL 子集或自建固定工具集；报告正确候选覆盖率、候选 rank、参数验证率、拒绝/澄清能力。helper、Jev、规则基线使用完全相同的可见工具及预算。
2. **受控交互层**：ToolSandbox 风格的本地状态世界；正确性由状态快照/里程碑决定，不用语言模型裁判作为唯一判据。报告任务成功、错误副作用、调用数、恢复数、延迟及成本。
3. **跨框架/协议层**：本地 MCP server 与 native tool adapter 服务相同的工具，逐项比对协议转换是否改写了 schema、候选排序、拒绝信息或结果语义。
4. **浏览器扩展层**：BrowserGym 环境作为独立可选 profile，容器化运行并 pin benchmark/镜像/任务集。将此结果与纯 tool-call 结果分开。

所有评测中，工具和环境都应有独立的 wall-clock 超时、调用额度、输出大小上限、临时工作目录和拒绝网络策略；每条轨迹写出固定的模型标识、helper 版本、seed、提示词、协议版本和任务版本。区分 proxy/helper 分数与真实 Jev 决策分数；代理策略只能作为基线，不能代替 Jev 结果。

## 扩散 / 并行文本生成与 speculative decoding

| 方向 | 官方来源与核心思路 | 许可证/范围 | 对 Jev 有用的交汇点 | 限制及不能复制的推论 |
|---|---|---|---|---|
| **Masked discrete diffusion LM（MDLM）** | [MDLM 论文](https://arxiv.org/abs/2406.07524)、[作者代码](https://github.com/kuleshov-group/mdlm)。对被 mask 的多个位置进行迭代修复；论文提出 SUBS 参数化，并讨论固定长度及半自回归生成。 | 论文按 arXiv 条款；代码仓库需读 LICENSE 与具体 checkpoint 卡。checkpoint、训练数据许可独立。 | 多位置 proposal 与自回归 Top-k 候选互补：可提出一整段工具参数、候选回复或待完善 span，Jev 再对离散分支/字段作选择；要缓存每轮候选及 mask/迭代状态。 | 同一次 forward 的多位置预测并不等于可直接复用 AR 的“给定 prefix 的下一个 token logits”；双向上下文、mask schedule、置信度和长度生成机制不同。不要把 parallel tokens 当无损加速或称为 Jev 已控制生成。 |
| **LLaDA 系列** | [作者论文](https://arxiv.org/abs/2502.09992)、[官方 PyTorch 仓库](https://github.com/ML-GSAI/LLaDA)。通过 masked diffusion 预训练/指令微调，展示非自回归、双向语境与并行去噪文本生成方向。 | 仓库明确：LLaDA-8B-Base/Instruct 权重 MIT；iLLaDA-8B-Base/Instruct Apache-2.0。须分别核实 weights、repo、数据及商业使用场景。 | 可做外部 proposal generator，让它产出多个完整参数候选或局部修订建议，由 Jev 判断接受/拒绝；为 apples-to-apples 对比，另外提供同一个 AR helper 生成的候选。 | 不能在没测延迟和准确率时假设“并行”实际更快；模型可能要多次去噪、显存读写密集、长度受配置影响。模型论文上的 benchmark 不是 Jev-agent 的效果证据。 |
| **Exact speculative decoding / speculative sampling** | [Leviathan et al. 论文](https://arxiv.org/abs/2211.17192)、[Chen et al. 论文](https://arxiv.org/abs/2302.01318)。小 drafter 提交多个 token，再由目标 AR 模型并行验证；修改过的拒绝采样可保持目标模型输出分布（算法/数值假设内）。 | 论文公开，不等于可复用实现/权重 license 相同；根据具体代码库许可。 | 在 helper 的连续文本输出路径中，可减少纯 AR 模式的串行 step 数；可把 drafter 的候选树展示给 Jev（作为决策辅助）并测采纳率。 | “分布等价”前提是按算法接受/拒绝并由目标模型验证。只要 Jev 自由挑选 token、改分布、加入拒绝或预算规则，就不再是对原目标分布的 exact sampling。不要把 speculative decoding 称为 Jev 决策加速的无损等价物。 |
| **多头/树式 speculative decoding（Medusa 等）** | [Medusa 作者仓库](https://github.com/FasterDecoding/Medusa)及其论文 *Medusa: Simple LLM Inference Acceleration Framework with Multiple Decoding Heads*（仓库 README 有论文链接）。附加预测头生成多 token 树，目标模型一次验证候选树；训练方案与模型架构相关。 | 代码/权重许可证以官方仓库和各 checkpoint 分别为准。 | 可将多头树映射为候选前缀/词片段列表，测 Jev 选择哪条、覆盖率和每次选择成本。可为 token-tree candidate-provider 做独立实验。 | 需要兼容模型/训练好的 heads 和推理实现；与通用“任意 helper 提供 logits”的模块边界不同。树中 proposal 被接受的加速结果不说明人工/机器决策质量；不能复制架构假设到不同 helper。 |

### 适用于 Jev 的实验假设

1. **阶段 A：维持已实现的 AR logits Top-k**，固定同一个 tokenizer、prompt 与 context；由 fake choice、local-top1 proxy、真实 Jev 三条路径分别运行，记录候选覆盖率、选择质量、延迟和成本。
2. **阶段 B：加入完整结构化 proposal**（工具、完整 JSON 参数、短片段），Jev 可接受、拒绝、请求澄清或进入 token 回退。由于现有原型的真实 Jev 长回答尚未验证，这比先迁移模型解码内核更能检验系统主张。
3. **阶段 C：并行 proposal 插件**，单独接一个 masked diffusion helper 或 Medusa-style candidate tree。调用协议应表达 `candidate_text / span / field / confidence / provenance`，不可假装它返回 AR `next_token_logits`。Jev 选择 span/字段/候选；需要逐 token 输出时，仅回退到有 next-token 条件分布的 helper。
4. 每种模型分别记录：成功任务吞吐/延迟、平均去噪/验证轮数、模型调用/token、Jev 选择次数、proposal 覆盖、最终准确率/约束保持率和内存峰值。并行度/每轮 token 数是性能指标，不是质量分数。

## 不应直接复制的内容

- 将某框架内置的 agent loop、提示模板、记忆格式、重试策略或状态对象直接移植成 Jev 的核心语义；这会造成依赖耦合，而且掩盖“Jev 每一步到底选择了什么”。
- MCP server / 浏览器 / ToolSandbox host console 对执行安全的隐含假设。隔离来自 Jev 自己的进程/容器、文件权限、网络、密钥和资源限制，不来自工具协议。
- 各 benchmark 的总分/leaderboard 名次，若任务集、用户模拟器、模型版本、grader 或运行模式不一致。特别是 tau 系列对 grading 修订有显式不兼容说明；WebArena 系列不同任务/截图版本也不可默认为同分布。
- diffusion 的“并行预测”表述、speculative decoding 的“exact”表述，除非验证实际算法前提、实现范围和 Jev 是否改变了目标采样分布。
- 任何 benchmark 任务文本、站点数据、trace 或模型权重的再发布，除非核实对应数据/模型条款；代码库的开源许可证不能推导出其全部素材都可重新分发。

## 来源清单（官方一手来源）

- [MCP specification](https://github.com/modelcontextprotocol/modelcontextprotocol) · [Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [LangGraph repository](https://github.com/langchain-ai/langgraph) · [official persistence docs](https://docs.langchain.com/oss/python/langgraph/persistence)
- [Pydantic AI repository](https://github.com/pydantic/pydantic-ai) · [official docs](https://pydantic.dev/docs/ai/overview/)
- [Gorilla / BFCL](https://github.com/ShishirPatil/gorilla) · [BFCL V4 leaderboard](https://gorilla.cs.berkeley.edu/leaderboard) · [BFCL paper](https://openreview.net/forum?id=2GmDdhBdDk)
- [τ-bench repository](https://github.com/sierra-research/tau2-bench) · [τ²-bench paper](https://arxiv.org/abs/2506.07982)
- [ToolSandbox repository](https://github.com/apple-aiml-research/ToolSandbox) · [ToolSandbox paper](https://arxiv.org/abs/2408.04682)
- [BrowserGym repository](https://github.com/ServiceNow/BrowserGym) · [BrowserGym paper](https://arxiv.org/abs/2412.05467) · [WebArena repository](https://github.com/web-arena-x/webarena) · [WebArena paper](https://arxiv.org/abs/2307.13854)
- [MDLM paper](https://arxiv.org/abs/2406.07524) · [MDLM repository](https://github.com/kuleshov-group/mdlm) · [LLaDA paper](https://arxiv.org/abs/2502.09992) · [LLaDA repository](https://github.com/ML-GSAI/LLaDA)
- [Speculative decoding paper](https://arxiv.org/abs/2211.17192) · [speculative sampling paper](https://arxiv.org/abs/2302.01318) · [Medusa repository](https://github.com/FasterDecoding/Medusa)
