# Jev 原型未完成事项清单

这份清单把对话中提出、但截至当前提交还没有完整交付的事项整理成可执行队列。`部分完成` 表示已经有骨架、代理实验或设计文档，但还没有端到端验证；后续轮次按优先级继续推进，不重复已经完成的工作。

## 最近状态更新（2026-09-24）

- 当前主线已改用运行时不读取答案的多跳评估：seed7 翻页45/48、候选范围复核48/48；冻结提示的seed19顺序检查20/24→23/24，仍有提前CLARIFY。所有提交选项（含控制项）≤8，驻留工具≤2。下一项优先验证“缺能力 vs 真歧义”的判别，再补B参数REFINE、C真实上下文依赖。详见 [最新实验报告](reports/2026-09-24-bounded-paging.zh-CN.md)。旧oracle gate及43次重复调用的证据边界已更正。

- P0.2 已有 `JevAgentOrchestrator` 垂直切片：两阶段页表、工具 Agent、版本/权限执行和 trace 可回放；完整 Tool/Memory/Prediction/Control 统一调度仍待完成。
- P0.3 已完成真实 Jev Choice 页表回放、12-case recovery action、单跳多页工具定位和 22-step 串联；样本仍不足以证明长轨迹检索质量。
- Virtual Option Space 已有同步 manager 原型；Virtual Context Space 已有 pinned/working/cold、aging、utility、hysteresis 和 minimum-residency 基线。
- 逻辑空间 10/100/1K/10K/100K、resident K=8/16/32 的机制 scaling 已跑通：100K 时 resident peak 仍为 K，stable-ID miss 为 0；这不是 Jev 质量结果。
- arXiv 草稿已放入 `paper/main.tex`，实验表全部保留为 TODO/计划；当前环境没有 `pdflatex`，未生成 PDF。
- `DecisionModel`、Replay 和 Oracle backend 适配器已加入代码，用于替换 Jev 和做能力上界实验；真实 backend capability scaling 仍待跑。
- synthetic backend capability/page-recovery 基线已跑通；真实 Jev、多 backend 能力曲线和 RecoveryRate 仍待跑。
- 新增 Runtime Governor、字段级参数 prior、adaptive set materialization 和安全包络设计；目前均为计划/假设，没有伪造实验结果。
- lexical 超远捞针矩阵已完成首轮 18/18 精确词命中控制；语义干扰、摘要缺失、多针和两阶段 Jev 对照仍待跑。
- 开放参数协议、文件/命令工具和显式 `:plan → :approve` REPL 已实现；默认 scripted chooser，`--live` 才连接真实 Jev，尚未做真实 Jev 交互质量评测。
- PAGE 投机首轮 timing model 已完成：Top-1 命中45%、隐藏164ms；Top-2命中65%、隐藏238ms但浪费比67.5%。这是固定轨迹模型，不是端到端 Jev 加速，详见 [报告](reports/2026-09-24-speculative-page.zh-CN.md)。

## 已完成的基础事项

- 远端 Docker 可通过 SSH `32222` 端口直连；连接不使用网络代理。
- 远端 GPU 使用规则已写入项目运行规范：每次任务先 fresh 检查，只使用明确空闲的 GPU，当前 GPU0/1 未触碰。
- SGLang、vLLM、Qwen3.8-27B、Qwen3.5-0.8B 已在远端准备；模型权重不进入 Git。
- 0.8B helper 的 raw logits、去 softmax、KV cache 骨架和实测加速已完成。
- Qwen3.5-0.8B 与 Qwen3.8-27B 的同上下文 Top-k 重合率、Qwen3-0.6B 的方向性覆盖、BFCL 候选覆盖已完成首轮基线。
- 工具目录、选项空间、页表读取边界、错误摘要队列、状态机审计和超远捞针词法粗筛基线已提交。
- GitHub 原型仓库已推送，密钥、模型权重和大体积结果没有进入 Git。

## P0：先完成可运行的端到端原型

1. **真实 Jev 对话闭环**：把 0.8B/27B 候选、工具调用、澄清、冲突定位和 `END_DIALOGUE` 接到同一条真实 Jev 流程；分别记录 helper 生成速度、Jev 选择速度、网络耗时、工具耗时和回答质量。当前只有 proxy 对话和一次真实 Choice 接口检查。
2. **整合 Agent 运行时**：把 ToolSpace、MemorySpace、PredictionSpace、ControlSpace、版本校验、权限检查和执行 trace 接入一个可运行 orchestrator；当前组件大多可以单独运行。
3. **两阶段记忆接入真实 Jev**：使用页摘要排序和 `TOP_2/4/8` 选择，接入 `NONE/CLARIFY/STOP`、stale/revision、敏感页和读预算；当前 selector 使用 ChoiceBackend 形状，尚未完成真实 Jev 回放。
4. **超远捞针矩阵**：运行不同页数、噪声长度、针位置、多针、相似干扰、冲突事实和摘要缺失的实验；比较全量上下文、单阶段 RAG、固定 Top-K、分层页表和两阶段 Jev。
5. **候选接受/回退机制**：实现 `top-(n-m)` 可接受候选、候选不足触发 fallback，并测量大模型高概率 token 在 helper Top-k 外的概率、拒绝率和补救成本。

## P1：把研究想法变成可复现实验

6. **更大规模 Top-k 实验**：扩展 Qwen3.5-0.8B/Qwen3.8-27B 的上下文集，覆盖中文、工具 JSON、长上下文和冲突输入；报告 Top10/20/50/100/250 重合、large-top1 miss、large-top-N coverage 和位置分桶结果。
7. **真实 Jev 速度表**：把 helper prefill/decode、Jev 请求、网络往返、工具准备和最终 decode 分开计时，避免把 proxy 速度当作 Jev 速度。
8. **KV cache 与并行重叠**：将 helper KV cache 接入 Agent 调度，让 prefill/decode 与无副作用工具准备、网络传输和候选校验重叠；测量排队、取消和 stale 后的浪费。
9. **扩散模型协同**：寻找许可证清晰且足够小的扩散/掩码语言模型，做多参数并行 proposal、轻量选择器、拒绝/接受和失败回退；BabyLM MDLM 目前只完成了质量边界观察。
10. **工具生态适配**：在隔离环境中挑选少量热门 agent 工具或框架，保留出处和许可证范围，转成 Jev 可选的安全 schema；目前只有本地工具目录和 MCP 形状描述，没有完整生态接入。
11. **状态机闭环**：把 trace 图、错误摘要、schema/dependency guard 接入实际运行；对稳定边做回放、漂移检测和人工审核，必要时导出只读决策图，不能直接自动执行未经验证的规则。
12. **公开 agent benchmark**：在隔离环境完成 BFCL 官方可执行评测，并补充 tau2/tau3、API-Bank 或同等多轮工具任务；分别报告工具正确率、错误副作用、修复率、Jev/helper 调用数、成本和 P50/P95 延迟。
    - **文字/ASCII 游戏与 AI PvP（计划，当前串联 workload 之后）**：优先复用 TextArena，OpenSpiel 作为备选；用可回放的回合制环境测长期决策、动作分页、参数细化和历史记忆，详见下文“游戏 benchmark 执行计划”。当前未下载或运行，没有对战结果。
13. **字段级参数 prior/case memory**：按 `(tool, field, state phase, semantic neighborhood)` 建立历史成功参数索引；与 schema/environment 候选合并成 `ArgumentOptionSpace`，只生成候选并交给 Jev 决策，不隐式绕过决策模型。先做 exact-state → state-machine match → semantic match 三级查找，评估参数构造步数、REFINE fault、延迟和错误副作用。该机制标为工程优化，相关的 case reuse/tool cache 已有近邻工作。
14. **Schema-aware radix/trie 参数候选与并行 proposal（新增计划）**：把枚举值、工具名、字段名、路径片段和历史成功参数组织成 radix tree；共享前缀只保留一次，按当前 schema/state 展开有限候选，允许 helper 并行预测独立字段或预取下一层候选，再把候选交给 Jev。它适合离散/共享前缀参数，不替代 Jev，也不直接加速连续自由文本；验收包括 candidate recall@K、非法参数率、Jev 调用数、候选物化时间、helper/网络 overlap、P50/P95 和副作用。高风险 COMMIT 必须经过 schema、revision 和权限校验。
15. **Runtime Governor（计划）**：输入完整 Jev 分布、熵、margin、候选规模、风险、成本、fault/history/budget/retrieval 特征，输出 `COMMIT/PAGE/EXPAND/REFINE/RETRIEVE/FALLBACK/CLARIFY`。以期望效用或边际 value-of-information 选择动作，不写死单一概率阈值；先用离线反事实标注，再比较 contextual bandit/offline RL，暂不把 PPO 作为首选。
16. **Adaptive set materialization（计划）**：根据当前状态选择值得 materialize 的最小 page subset，估计 `ΔV(page)=V(S∪page)-V(S)` 与成本的关系；比较固定 top-p、固定 top-k 和自适应集合。该方向与 value-based retrieval stopping 有关，作用对象扩大到整个 OptionSpace 变换，不能宣称单点原创。
17. **Learned Governor 安全层（计划）**：用 learned controller 负责效率，用 conformal/calibrated safety envelope 限制高风险 COMMIT；校准不足时只能 PAGE/REFINE/FALLBACK/CLARIFY。验收包括风险覆盖率、错误提交率、拒绝率、额外延迟和分布外状态。
18. **Candidate proposer 接口（计划）**：扩散模型、small AR、retriever、compiler 和历史 prior 都实现同一 proposer 接口；扩散模型只作为并行候选生成器，不作为论文 headline 或决策者。评估 proposal recall、Jev 选择成本和失败回退。
18a. **Speculative Option-Space Transitions（计划）**：把性能优化限制在独立的 `SpeculationSpace`：小模型/历史/局部性只预取无副作用的下一页或已选粗选项的 refinement 草案，绝不污染当前 Jev resident set。先比较关闭、top-1/top-2 `PAGE` 预取和固定下一页；只有 Jev 提交父级转移并通过 schema、权限、依赖和 revision guard 后才 promote，猜错或 stale 直接丢弃。首版只做 depth=1，候选融合先用单一排序，不能把 logits 当作未经校准的 page 概率。记录命中率、有效预取比、`min(准备耗时,Jev等待窗口)`、page stall、浪费比、stale 丢弃、额外 IO、helper 调用和任务成功率。`REFINE` 树、深度大于 1、radix/trie 共享前缀和 learned governor 是后续项；没有共享前缀时不强行使用 trie。该方向借鉴 speculative execution/prefetch 先例，贡献候选是对 PAGE/REFINE 决策空间的调度与一致性验证，不作单点首创声明。

## P2：记忆系统和工程化扩展

19. **分页记忆长期运行**：实现约 200 个一级目录、多级父页、原始子页回溯、摘要版本、LRU 只作排序/淘汰信号，以及向量/BM25 混合 RAG；专门测低频旧事实和父页合并造成的事实损失。
20. **上下文区域预算**：把任务核心、明确读取记忆、最近记忆、工具扩展、预测 proposal、错误/trace 分成独立预算，实现工具翻页、默认参数和最近成功历史。
21. **记忆评测消融**：测粗筛漏失率、`recall@M`、最终 `precision@K`、关键事实覆盖率、选择稳定性、校准误差、澄清率、读取字节和分阶段延迟；缓存命中率只作为成本指标。
22. **本地下载/传送 fallback**：整理不走代理的镜像下载、校验、断点续传、传到远端项目目录和本地临时权重清理脚本；不把权重或凭据写入仓库。
23. **远端项目清理**：在确认文件归属后，清理 Docker 内无关旧项目，保留其文档；操作范围限定在 `/home/liuyuntao/jev-agent-prototype`，不碰共享工作空间。

## P3：论文和新颖性核验

24. **相关工作审计**：核对 Jev memory、RAG、RAPTOR、GraphRAG、MemGPT/Letta、工具选择、状态机编译、扩散 proposal 和超远捞针工作，区分已有组件、组合创新和真正尚未验证的贡献候选。
25. **DeepSeek 架构小模型调查**：查找公开、许可证清晰、尺寸足够小的同架构科研模型；没有合适模型时记录检索范围和否定结果，不强行下载替代品。
26. **论文级复现包**：固定数据、随机种子、模型版本、GPU 选择、配置和结果格式，补齐许可证/出处、失败案例和消融图表，再讨论顶会投稿定位。
27. **凭据生命周期整理**：检查临时 API 凭据是否仍在本机文件或环境变量中，使用后清理运行日志和临时副本；任何凭据都不写入 Git 或公开文档。

## 游戏 benchmark 执行计划（2026-09-24，尚未实施）

定位：作为 A/B/C 串联后的补充 workload，提供规则引擎裁决、长回合轨迹和 AI 对战。AI PvP 已有成熟框架，不作为新颖性主张；研究问题是同一 decision backend 在不同 runtime 策略下的胜率、恢复能力和预算利用率。

候选环境与用途（来源于官方资料，接入前固定 commit、许可证和规则配置）：

| 候选 | 用途 | 边界 |
| --- | --- | --- |
| TextArena 的 TicTacToe / ConnectFour | 先验证文字观察、合法动作、回合推进和胜负裁决 | 动作空间很小，只作适配 smoke，不证明大规模分页或记忆收益 |
| TextArena 的 Battleship / MemoryGame | 检查历史观察读取、重复动作和不完全信息下的决策 | 若默认观察已包含完整历史，必须单独标记 memory-limited wrapper；不声称原环境天然检验 C |
| 具有单位、目标与参数组合的回合制棋盘环境 | 按动作族/单位分 PAGE，按动作目标/参数做 REFINE，观察日志做 context paging | 先复用现成环境；只有确实缺少所需机制时再做小型公开扩展，不凭空添加无意义候选以制造 scaling |
| 自建可回放 ASCII 微型环境（资源、门、库存、冷却、交易） | 直接控制动作数、页数、参数错误、工具失败、矛盾观测和长轨迹噪声，作为 A/B/C 的主诊断环境 | 规则、状态转移和奖励全部由程序裁决；不能把最优动作标签放进观察 |
| OpenSpiel | 固定规则对手、搜索基线及完全/不完全信息对照 | 单独适配各玩家可见观察；全局 state 仅归裁判，不能直接传给玩家 |

协议与验收：

1. 使用 ASCII 棋盘加简短规则；提供等信息量的结构化观察对照，区分读图/读字符错误与 runtime 错误。裁判负责确定性规则与终局；玩家只看自己的观察、历史和合法动作，不看对手隐藏信息或最优动作标签。
2. A：逻辑合法动作集大于 resident K 时，按自然动作类别分页；统计总可选动作数、实际提交 Jev 的选项数（包含控制项）、PAGE 次数、动作覆盖和错误页恢复。B：将粗动作逐层细化成完整参数，并成对注入候选缺失、schema/参数错误、工具超时、矛盾观测、用户更正和 revision 变化，统计非法动作、预算超限、恢复触发/漏触发、恢复步数与成功率。C：比较完整/截断历史、RAG replacement 与 bounded residency；读取的记忆只能来自该玩家先前见过的信息。
3. 先用冻结的随机合法对手、规则/搜索对手做可复现基线，再运行 Jev+完整 runtime、Jev+消融 runtime、helper-only、常规生成式 agent 的交叉 PvP。所有策略使用同一游戏规则、观测权限和合法性约束；不为某个方法暗中提供最优动作。
4. 配对随机种子并交换先后手/阵营，冻结模型和提示词，预注册页数、resident K、轨迹长度、噪声量、Jev/helper/tool-call/token/time budget 的 factorial 对照，分开报告同调用预算、同时间预算或同成本预算。主线先看正确率与机制，网络超时单列；不会将超时过滤后剩余对局的胜率当全量成绩。
5. 报告胜/负/和、置信区间、终局完成率、非法动作率、fault/recovery、关键历史读取、Jev/helper 调用数和 resident/context 实测峰值；另报告规则状态上的 action quality、regret、目标完成和资源/存活。复杂游戏不强行定义唯一“正确招”；最优动作准确率只用于有精确解的小状态。自我对弈双方得分对称不能证明进步；Elo 只在明确的对手池内作相对指标。
6. 保留逐回合轨迹与失败归因：观察表示、候选漏失、选错页、参数细化、历史遗忘、策略失误、API 错误分别记录；先最小复现，再设计工程/算法修复和消融，不因输一局就判定机制失败。

来源：[TextArena 官方仓库](https://github.com/TextArena/TextArena)、[游戏目录](https://github.com/TextArena/TextArena/blob/main/textarena/envs/README.md)、[OpenSpiel 官方仓库](https://github.com/google-deepmind/open_spiel)。上述是设计与候选筛选，不是运行证据；执行顺序仍为当前多页检查 → A/B/C 串联 → 游戏适配 smoke → 冻结对手基线 → PvP 消融。

## 执行规则

- 原先每 15 分钟、最多 88 轮的 `jev` heartbeat 已按用户要求暂停；后续按本队列手动推进，已有状态和报告保留。
- 远端 GPU 任务必须先重新运行 `nvidia-smi`，只使用真正空闲的 GPU；任何长任务结束后再次确认空闲状态。
- 先用 proxy/oracle 做机制测试，再标记真实 Jev 结果；两者不能混写。
- 每个实验保留配置和失败边界；结果 JSON、模型权重、API key 和远端临时文件不提交到 Git。

## 统一运行时定位（DecisionModel 与双重虚拟化）

系统抽象为可替换的 `DecisionModel: D(s,O) -> P(O)` backend；Jev 是当前原型 backend，未来可替换 Mock/Oracle 或其他 typed decision backend。Open World 通过 Virtual Option Space 管理 resident options，通过 Virtual Context Space 管理 resident context blocks，随后驱动 Decision Model 与 state transition。PAGE/EXPAND 扩大候选覆盖，REFINE 降低候选粒度，ContextFault 触发二阶段 context paging，REVISION/INVALIDATE 保持一致性。

Context 分为 Pinned、Working、Cold 三层。Context block 元数据包括 `block_id/summary/raw_ref/revision/dependencies/last_access/access_count/utility/type/size/pinned`。按类型 aging：Pinned 不老化，任务状态慢老化，观察与 transient retrieval 快老化；utility aging 根据实际决策用途更新。采用 hysteresis、minimum residency、working-set history 与 phase-aware anti-thrashing。memory/RAG 在此是 context residency policy，而非普通“给模型找资料”。runtime 不依赖跨请求 prefix/KV reuse，允许 aggressive context mutation；这不等于声称 Jev backend 完全没有 KV cache。贡献边界是 Virtual Option + Context virtualization、decision-preserving refinement、fault/recovery/consistency 的组合，不声称各组件单点新颖。

## Roadmap 审计（2026-09-24）

本轮复核了执行队列、定位、研究笔记、论文和 benchmark 说明。当前主线已经覆盖：真实 Jev 闭环、两阶段页表记忆、Virtual Option/Context Space、PAGE/REFINE/RECOVERY、helper raw-logits/KV overlap、27B 与小模型候选覆盖、工具与状态机、公开 benchmark、扩散 proposal 以及论文草稿。以下项目仍必须保留在队列中，不能从设计文字推断为已完成：

- **端到端真实性**：真实 Jev 逐 token 自然语言、真实 Jev 速度拆分、helper 与网络/工具 overlap、回答质量盲评。
- **恢复与控制**：真实 backend 的 `RecoveryRate`、`Runtime Governor`、自适应 page materialization、候选不足时的 fallback、风险安全包络，以及 stale/revision 后的统一 fault loop。
- **记忆与检索**：多级约 200 页页表、向量/BM25 混合检索、超远捞针矩阵、摘要丢事实和冲突事实消融；现有 lexical/selector 结果只属于机制基线。
- **工具与 benchmark**：推荐 benchmark 的轻量代码入口已隔离下载并记录版本/许可证；隔离运行、BFCL 官方执行、tau 系列、ToolSandbox/BrowserGym 等仍需分别固定环境和可比性，禁止把候选覆盖当官方成绩。
- **扩散与状态机**：并行 proposal 的净延迟、接受率和副作用隔离；错误摘要、决策图导出和自动边编译必须经过回放、漂移检测和人工复核。
- **研究与发布**：相关工作/新颖性继续以“组合接口候选”表述；论文实验保持 TODO，模型权重、数据集和凭据不进 Git。

本审计还发现两类容易混淆的表述，已统一修正：同步 VirtualOptionManager 已有机制实现，但统一生产调度器、异步 prefetch、学习型 replacement、真实 Jev scaling 仍未完成；固定 resident 在合成缺失目标实验中的 0% 是该策略的任务成功率，不是系统总体指标，也不代表 Jev 或 runtime 已“爆炸”。

## Evaluation convergence（2026-09-24）

本轮把评估收敛到三条主线，避免继续堆叠彼此孤立的数字。现阶段已经完成的是系统原语和受控边界证据：Virtual Option/Context、稳定 ID、page-in/out、refine、revision/stale、orchestrator 垂直切片、helper raw-logits/KV cache、BFCL/top-k 候选覆盖、top-k overlap、synthetic fallback、needle/对抗词法控制、两阶段 memory 控制矩阵、少量真实 Jev Choice replay，以及字段级 parameter prior。它们证明代码路径和边界可运行，但不等同于端到端 agent 质量。

后续优先级调整为：完成当前 parameter prior 验证后暂停扩展散乱 feature，先做真实 Jev 闭环，再按以下顺序补齐论文级证据：

1. **A — Decision-space virtualization**：对比 fixed resident、检索 top-k、分层候选和 virtual paging；扩大 logical option scale，记录 resident 大小、覆盖、恢复、延迟和成本。
2. **B — Progressive refinement and recovery**：构造受控的 resident、missing、coarse、ambiguous、stale cases，测 `COMMIT/PAGE/REFINE/FALLBACK/CLARIFY/STOP` confusion matrix，并接入真实 Jev。
3. **C — Dynamic context residency**：比较 static、append-only、RAG replacement、aging、aging+anti-thrashing；记录关键事实覆盖、选择稳定性、读取预算和决策效用。
4. **串联 workload**：实现一个 20–100 步的 decision-dense deterministic workload，使三条主线在同一轨迹中真实触发，再报告端到端 success、P50/P95 latency、成本、fault 数和副作用。

当前进度：

- **A：已有不读取答案的真实多跳诊断，规模仍小。** 100K logical options 结果仍属机制上界。旧 12 页 recovery-gate 用隐藏 target 辅助恢复，47/48 还受 monitor 双意图欠标注影响，已纠正证据边界。新 bounded paging（12 页/24 工具，所有提交选项含控制项 ≤8）seed=7 为 45/48、错误页恢复 9/12；候选范围复核后 48/48、错误页恢复 12/12，调用数 +50%。固定 resident 对照为错误页 0/12、正确页 12/12。下一步冻结提示后做未见请求和 retrieval/hierarchical 对照；详见 [实验报告](reports/2026-09-24-bounded-paging.zh-CN.md)。
- **B：受控闭环已完成，规模仍小。** 真实 Jev recovery action 为 12/12，4-case retrieval→recovery smoke 为 4/4，8-step live decision-dense smoke 为 8/8；尚未覆盖长轨迹、多次失败、真实工具副作用和更大 confusion matrix。
- **C：目前只有机制触发，尚无真实任务依赖证据。** 24-step deterministic workload 和 22-step live 串联能触发 context paging/ContextFault，但被重建的 context 内容没有作为后续任务决策的必要输入；static/append-only/RAG/aging 消融、关键事实召回与任务效用评测仍待。
- **串联 workload：22/43 次真实调用诊断已跑通，真正任务依赖仍待。** 22-step 的 19/22→22/22 与 43-call 的 43/43 验证受控路径；后者重复模板，不代表长程推理。A 已补多跳诊断，之后优先补真实参数 REFINE、上下文事实被后续任务消费的 C 消融，再串成 20–100 步依赖轨迹。

5. **工程优化（排在机制正确性之后）**：连接池和 HTTP/2/1.1 keep-alive、TTFB/request-id 观测、超时与安全重连、Jev/helper/工具并行 overlap、radix/trie 候选预取、高置信 fast path、决策批处理与调用合并。验收统一记录 fresh vs reuse、P50/P95、端到端 wall time、Jev 调用次数、fallback/recovery 正确率；任何 fast path 都不能绕过高风险 COMMIT 的校验。

四个关键缺口必须分开测量，不能用 oracle locator 代替真实检索：

- missing detection：目标是否被判定为不在 resident；
- page localization：检索/页表是否找到包含目标的候选页；
- recovery success：PAGE/EXPAND/REFINE 后是否恢复正确决策；
- end-to-end success：上述步骤与 Jev 决策、执行和状态提交合并后的结果。

因此 `P(EXPAND | target ∉ resident)` 只能作为缺失触发行为的条件指标，不能直接当作 paging 质量。当前 synthetic capability/page-recovery 的目标页由程序已知，属于机制上界。4 页与 12 页 recovery-gate live harness 也会用隐藏 target 决定 gate、修复分支和计分，尽管 target ID 不直接出现在模型 prompt；这些结果不能替代答案盲定位。resident 峰值只统计 manager 中驻留的工具候选，不含目录菜单和 CLARIFY/STOP 控制项。真实 Jev 的单跳多页定位已完成，但多跳错误页恢复、更大页目录、20–100 步任务依赖 workload 和端到端 latency/cost/quality 仍未完成。

masked diffusion 的直接 proposal 质量负结果可以保留在 appendix 或失败分析中，暂不作为主线贡献；它只说明当前小型 checkpoint 的直接用法边界，不否定 proposer 接口或并行候选方向。

- adversarial lexical 控制已补上：正文-only、摘要改写和 32 个 decoy 页都会漏失，验证了当前粗筛的已知边界；语义/两阶段 Jev 对照仍待跑。

- 两阶段 memory control matrix 已完成无网络回放：单页/双页成功读取，无候选、读取超预算和 stale selection 均安全阻断；真实 Jev 多页概率与质量仍待跑。

- 候选回退控制流已复跑并保存报告；当前结果仍是 scripted oracle 上界，真实 Jev 选择、top-(n-m) 接受和补救成本仍待测。
### P1 参数先验（已完成）

`ParameterPrior` 按工具、字段和阶段记录成功率与 revision，并按 exact-state → state-machine → semantic/lexical 三级检索生成候选。候选仅进入 `OptionSpace`，最终仍由 Jev/DecisionModel 选择；过期或 revision 不兼容记录会被过滤。这是工程优化，不是单独的新颖性主张。

- 第一轮真实 Jev recovery action benchmark 已完成：6 个受控 COMMIT/PAGE/REFINE/CLARIFY/STOP case 全部选对；下一步优先扩大到 missing detection、page localization、recovery success 分离的多 case 矩阵和真实执行闭环。

- 真实 Jev recovery action 已从 6 个扩展到 12 个受控 case，当前 12/12；下一步不再增加纯 action 分类规模，转向真实 retrieval→Jev→PAGE/REFINE→执行的闭环和失败案例。

- 真实 Jev retrieval→recovery smoke 已完成 4/4 终态契约；期间发现并修复 refine 后父候选未移除的 runtime bug。下一步优先扩大为多页、多 fault、无 oracle locator 的 decision-dense workload，再测真实工具执行与长轨迹成本。

- 24 步 decision-dense deterministic workload 已跑通：三类 resident/context 上限保持，PAGE/REFINE/ContextFault/stale/CLARIFY/STOP 均触发并恢复；live Jev action 已接入 8 步 smoke，后续继续扩大真实 retrieval 和长轨迹成本评测。

- 8 步 live Jev decision-dense smoke 已完成：真实 Jev 选择 8/8 个预期动作，覆盖 COMMIT/PAGE/REFINE/CLARIFY/STOP、页恢复和冷上下文恢复；resident/context 峰值分别为 2/4 和 2/2。报告为 `benchmarks/results/jev-decision-dense-live.json`。相对预期：动作正确率更好，但平均 7.64 s 且有 11.6–19.4 s 长尾，延迟更差；下一步优先扩大多页、多 fault、无 oracle locator 的真实 retrieval→Jev→recovery workload，并记录 P50/P95。

- 延迟长尾诊断已完成：fresh 直连分段显示建连约 0.32–0.49 s，响应体约 0.02 ms，主要等待在 response-header/TTFB（0.38–6.28 s，另有一次 30 s timeout）；持久连接对照平均 635.7 ms、P95 823.5 ms。相对预期：确认连接池能明显改善固定开销，但服务端/跨境路径长尾仍存在。后续优先接入连接池与 TTFB/request-id 观测，再用高置信 fast path、调用合并和 helper/网络 overlap 减少串行 Jev 次数。

- 多物理工具/多虚拟页真实 Jev 选择已完成：18 个物理工具、6 个页、resident 上限 2；10 个需选页的 case 全部定位正确、页内工具 10/10、2 个歧义 case 全部 CLARIFY，最终 12/12。报告为 `benchmarks/results/multi-page-tool-selection-live.json`。相对预期：明显好于确定性词法控制（最终 58.3%）和最低预期；单跳实验已通过，后续转向多跳错误页恢复、更大页目录和串联扩展。

- 22-step 真实 Jev A/B/C 机制串联已完成首轮与修复复跑：首轮 19/22（86.4%）暴露页选择失败后继续执行、以及 COMMIT 与 resident candidate 混在同一选项面的两个 runtime 问题；修复后使用 lexical page directory、工具前置 coverage gate 和 control-only action surface，22/22，fault 4、recovery 13、模拟执行 4，resident/context 峰值 4/4 与 2/2，外部副作用 0。报告为 `benchmarks/results/jev-decision-dense-serial-live.json` 与 `benchmarks/results/jev-decision-dense-serial-live-rerun.json`。该 workload 的 C 仅触发 context paging，不包含由重建内容驱动的后续任务依赖；平均 1.02 s/步仍高于离线 contract，下一步先补显式错误页 recovery，再扩大具有真实依赖的 20–100 步 workload。
- 显式错误页 recovery 已做一次真实 Jev 故障注入：首次文件页故意返回 `CLARIFY`，随后工具前置 gate 触发 `OptionFault`，阻止空 resident 工具调用并重新选择 `PAGE:files`；页恢复和页内工具均成功，`blocked_invalid_tool_calls=1`、`page_recovery_successes=1`、外部副作用 0。报告为 `benchmarks/results/jev-decision-dense-serial-live-injected.json`；21/22 是包含故意注入错误的诊断值，不能替代正常 22/22。下一步扩展 empty/wrong-page/stale-page/correct-page 四状态矩阵。
- recovery gate 四状态控制矩阵已完成：4 页 × `empty/wrong_page/stale/correct_resident` 共 16 cases，12 次非法工具解析在 gate 层阻断，stale 页经 revision refresh 后恢复；页恢复、页内选择和端到端均 100%，resident 峰值 2/2，外部副作用 0。报告为 `benchmarks/results/recovery-gate-matrix-latest.json`。相对预期：manager 机制边界符合预期；仍需把同一矩阵接到真实 Jev，测 Jev 的页定位和恢复选择错误。
- recovery gate 真实 Jev 四状态矩阵已完成：4 页 × 4 状态共 16 cases，报告为 `benchmarks/results/recovery-gate-live-latest.json`。模型得到 query、页摘要和当前页工具，但 harness 用隐藏 target ID 决定 gate/恢复分支与计分；12 个非 resident case 被阻断，报告中的页恢复、页内选择和端到端均为 100%，P50/P95 为 1,306.3/1,346.9 ms。resident 峰值 2/2 只计工具候选，不含目录与控制项。此结果说明受控门控流程可运行，不是答案盲检索质量。
- 12 页 × 4 状态的 recovery-gate 两次报告 `benchmarks/results/recovery-gate-large-live-latest.json` 与 `benchmarks/results/recovery-gate-large-live-root-repeat.json` 均为 47/48；隐藏 target 驱动 gate 与恢复分支。monitor query 同时要求 inspect 和 ack、gold 只标 inspect，故不能将单个未匹配计分断言为模型混淆。
- 43 次串行决策调用真实 Jev 已完成：21 个事件重复两轮，再加最终 stale-stop，43/43，fault 7、recovery 25、模拟执行 8，resident/context 峰值 4/4 与 2/2，外部副作用 0，平均 675.0 ms/次。报告为 `benchmarks/results/jev-decision-dense-serial-long-live.json`。它重复固定事件和 query，没有真实跨周期长程依赖；C 仍缺少由 context 内容驱动的后续任务决策。
- `benchmarks/benchmark_jev_bounded_paging.py` 已完成 seed=7 的真实多跳评估：45/48，错误页起步9/12；范围复核开发集复跑48/48，代价为116→174次调用。所有目录/工具/控制选项统一计入8项上限，工具resident另限2。下一轮优先冻结提示后验证未见请求、加入拒绝/歧义负例和retrieval对照；报告 `docs/reports/2026-09-24-bounded-paging.zh-CN.md`。
- seed=19顺序/目标位置检查已完成：相同提示下24 episodes为20/24→23/24，错误页恢复8/12→11/12；剩余一例直接CLARIFY，无候选可供复核。优先加入缺能力/真歧义负例，不允许无条件覆盖CLARIFY；完整70个单元测试通过。本轮是A的诊断推进，B/C完整闭环尚未完成。

- **第10轮：按需 context refresh 原型已加入，但标为可关闭的 P2 实验。** `ContextRefreshCoordinator` 实现了 cooldown、阶段刷新预算、目录 `top-M`、并发 block verifier、epoch/revision 校验和原子 `commit_selected`；确定性代理轨迹为 6/6 提交、6/6 目标命中，重复触发 4/5 被抑制，旧 epoch 被拒绝，远端 125 项测试通过。报告为 `docs/reports/2026-09-24-context-refresh-coordinator.zh-CN.md`。这仍不是多级页表、真实 Jev 质量或正文加载结果。摘要策略暂定为 L0 结构化元数据 → L1 混合 RAG 预筛 → L2 0.8B 异步摘要候选 → L3 Jev 选择 → L4 原文/冲突校验；0.8B 摘要不可替代原文证据，纯 RAG 也不能替代 revision guard。

- **第12轮：真实 Jev context refresh smoke。** 在 5 个不透明 block ID 的受控 case 上，目录召回为 4/4；gold case 初始驻留命中 1/4，刷新后 3/4，3 个真正缺失 case 恢复 2/3；无 gold 歧义 case 没有误刷新。20 次 verifier 调用的 P50/P95 为 663.8/703.2 ms；audit evidence case 保守返回 `NO_EVIDENCE`，不能直接判为语义错误。第一次候选 key 返回 401，换用下一条一次性 key 后完成；报告为 `docs/reports/2026-09-24-context-refresh-live.zh-CN.md`，不把失败凭据请求计入质量。

- **第13轮：上下文空间建模。** README 新增 Context Space / Option Space 位置图和放入/移出规则，明确新事件先注册、Pinned/Working/Cold 区分、淘汰后进入 Cold、原始证据/trace 不自动注入、Virtual Option 与 Shadow Option 分开；同时标出当前实现仍是单级目录，正文 materialization、自动摘要和跨空间统一调度尚未完成。

- **第14轮：正文 materialization 契约。** 新增显式 source mapping/callback 的 `ContextMaterializer`，按 UTF-8 字节预算、stale/expected revision 和 SHA-256 返回正文；它不直接读任意路径、不改变 resident set。4 个代理 case 中 2 个摘要遗漏 marker 成功回读，stale 和超预算各 1 个被拒绝；远端 130 项测试通过。报告为 `docs/reports/2026-09-24-context-materialization.zh-CN.md`。下一步才是把真实 Jev 的 `NO_EVIDENCE` 接到正文回读与 evidence contract。

- **第15轮：真实 Jev `NO_EVIDENCE` → raw evidence fallback。** 新增 `ContextEvidenceFallback`，只对目录候选有界 materialize 正文，检查完整 marker、唯一性和 revision 后再提交。5 个真实 case 中，初始 gold 命中 1/4；Jev coordinator 直接命中 3/4；加入 fallback 后最终 gold 命中 4/4，3 个缺失 case 恢复 3/3；无 gold 歧义安全拒绝。20 次调用 P50/P95 为 690.6/767.7 ms。报告为 `docs/reports/2026-09-24-context-refresh-live-fallback.zh-CN.md`。这是 evidence-contract 价值，不是通用 Jev 准确率；目录漏召回和语义 evidence 仍待。

- **第16轮：Working/Cold 规则与预算审计。** README 补充了当前 score、aging、minimum residency、hysteresis、revision/stale 的准确行为；明确 Working 被替换后只是进入 Cold，不会删除，Pinned 不参与 working 上限，新 block 先入 index。同步列出当前分散硬上限（working 8、memory 16/8/32 KiB、grounded evidence 4/16 KiB、materializer 16 KiB、refresh M≤4）和一套待验证的 24 KiB Context Frame 规划预算。当前仍没有统一 budget controller，规划值不能当实现结果。

- **第17轮：分区 ContextBudgetController。** 将 24 KiB 规划预算实现为 `pinned/recent/working/evidence/options/trace` 六个独立分区；按 UTF-8 字节和优先级打包，分区不互相借用，Pinned/required 超限报错，普通低优先级 slice 记录 dropped。代理结果按预期丢弃长历史并拒绝 Pinned 超限；远端 137 项测试通过。报告为 `docs/reports/2026-09-24-context-budget.zh-CN.md`。尚未接入真实 Jev prompt，下一步需要 workload A/B/C 对照来验证这套预算是否提高证据召回和任务正确率。
- **第18轮：255-entry Option Space 页预算。** 新增 `OptionPageBudget`，把 255 定义为 Jev Choice 的目录页/线协议上限，实际调用默认 16 个动作候选并预留 6 个 `PAGE/REFINE/CLARIFY/REVIEW/STOP/NONE` 控制项；40 个候选切分为 `[16,16,8]`，总数始终不超过 255。本地和远端 bundled Python **141 项测试通过**、3 项可选依赖跳过。新增 `ContextBudget.jev_wide()` 的 48 KiB UTF-8 字节宽配置，24 KiB 继续作为窄基线。报告为 `docs/reports/2026-09-24-option-page-budget.zh-CN.md`。TypeSafe 当前文档给出 Jev 1.13 每请求 64k tokens、`state`+最长问题 32k tokens；本项目 24/48 KiB 与 2048-token 本地服务参数都是保守工程预算。下一步用真实 Jev 对照 8/16/32/64 decision batch 和 24/48 KiB context，记录质量、控制项误选和延迟。
- **第19轮：预算离线容量对照。** `benchmarks/benchmark_budget_ablation.py` 固定 255 个逻辑候选和末尾 evidence needle，对照 24/48 KiB Context 与 8/16/32/64 action batch。48 KiB 合成配置只丢 1 个 slice 并保住 needle，24 KiB 丢 43 个且漏掉 needle；255 候选分别需要 32/16/8/4 批次。报告为 `docs/reports/2026-09-24-budget-ablation.zh-CN.md`，结果是 proxy 容量信号，不是 Jev 质量结论。下一步接受控真实 Jev workload，测批次质量和延迟。



