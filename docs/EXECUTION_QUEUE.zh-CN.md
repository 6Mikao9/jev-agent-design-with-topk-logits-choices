# Jev 原型未完成事项清单

这份清单把对话中提出、但截至当前提交还没有完整交付的事项整理成可执行队列。`部分完成` 表示已经有骨架、代理实验或设计文档，但还没有端到端验证；后续轮次按优先级继续推进，不重复已经完成的工作。

## 最近状态更新（2026-09-24）

- P0.2 已有 `JevAgentOrchestrator` 垂直切片：两阶段页表、工具 Agent、版本/权限执行和 trace 可回放；完整 Tool/Memory/Prediction/Control 统一调度仍待完成。
- P0.3 已完成两次真实 Jev Choice 页表回放：一次 `CLARIFY`，一次两阶段读取成功；样本不足以证明检索质量。
- Virtual Option Space 已有同步 manager 原型；Virtual Context Space 已有 pinned/working/cold、aging、utility、hysteresis 和 minimum-residency 基线。
- 逻辑空间 10/100/1K/10K/100K、resident K=8/16/32 的机制 scaling 已跑通：100K 时 resident peak 仍为 K，stable-ID miss 为 0；这不是 Jev 质量结果。
- arXiv 草稿已放入 `paper/main.tex`，实验表全部保留为 TODO/计划；当前环境没有 `pdflatex`，未生成 PDF。
- `DecisionModel`、Replay 和 Oracle backend 适配器已加入代码，用于替换 Jev 和做能力上界实验；真实 backend capability scaling 仍待跑。
- synthetic backend capability/page-recovery 基线已跑通；真实 Jev、多 backend 能力曲线和 RecoveryRate 仍待跑。
- 新增 Runtime Governor、字段级参数 prior、adaptive set materialization 和安全包络设计；目前均为计划/假设，没有伪造实验结果。

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
13. **字段级参数 prior/case memory**：按 `(tool, field, state phase, semantic neighborhood)` 建立历史成功参数索引；与 schema/environment 候选合并成 `ArgumentOptionSpace`，只生成候选并交给 Jev 决策，不隐式绕过决策模型。先做 exact-state → state-machine match → semantic match 三级查找，评估参数构造步数、REFINE fault、延迟和错误副作用。该机制标为工程优化，相关的 case reuse/tool cache 已有近邻工作。
14. **Runtime Governor（计划）**：输入完整 Jev 分布、熵、margin、候选规模、风险、成本、fault/history/budget/retrieval 特征，输出 `COMMIT/PAGE/EXPAND/REFINE/RETRIEVE/FALLBACK/CLARIFY`。以期望效用或边际 value-of-information 选择动作，不写死单一概率阈值；先用离线反事实标注，再比较 contextual bandit/offline RL，暂不把 PPO 作为首选。
15. **Adaptive set materialization（计划）**：根据当前状态选择值得 materialize 的最小 page subset，估计 `ΔV(page)=V(S∪page)-V(S)` 与成本的关系；比较固定 top-p、固定 top-k 和自适应集合。该方向与 value-based retrieval stopping 有关，作用对象扩大到整个 OptionSpace 变换，不能宣称单点原创。
16. **Learned Governor 安全层（计划）**：用 learned controller 负责效率，用 conformal/calibrated safety envelope 限制高风险 COMMIT；校准不足时只能 PAGE/REFINE/FALLBACK/CLARIFY。验收包括风险覆盖率、错误提交率、拒绝率、额外延迟和分布外状态。
17. **Candidate proposer 接口（计划）**：扩散模型、small AR、retriever、compiler 和历史 prior 都实现同一 proposer 接口；扩散模型只作为并行候选生成器，不作为论文 headline 或决策者。评估 proposal recall、Jev 选择成本和失败回退。

## P2：记忆系统和工程化扩展

18. **分页记忆长期运行**：实现约 200 个一级目录、多级父页、原始子页回溯、摘要版本、LRU 只作排序/淘汰信号，以及向量/BM25 混合 RAG；专门测低频旧事实和父页合并造成的事实损失。
19. **上下文区域预算**：把任务核心、明确读取记忆、最近记忆、工具扩展、预测 proposal、错误/trace 分成独立预算，实现工具翻页、默认参数和最近成功历史。
20. **记忆评测消融**：测粗筛漏失率、`recall@M`、最终 `precision@K`、关键事实覆盖率、选择稳定性、校准误差、澄清率、读取字节和分阶段延迟；缓存命中率只作为成本指标。
21. **本地下载/传送 fallback**：整理不走代理的镜像下载、校验、断点续传、传到远端项目目录和本地临时权重清理脚本；不把权重或凭据写入仓库。
22. **远端项目清理**：在确认文件归属后，清理 Docker 内无关旧项目，保留其文档；操作范围限定在 `/home/liuyuntao/jev-agent-prototype`，不碰共享工作空间。

## P3：论文和新颖性核验

18. **相关工作审计**：核对 Jev memory、RAG、RAPTOR、GraphRAG、MemGPT/Letta、工具选择、状态机编译、扩散 proposal 和超远捞针工作，区分已有组件、组合创新和真正尚未验证的贡献候选。
19. **DeepSeek 架构小模型调查**：查找公开、许可证清晰、尺寸足够小的同架构科研模型；没有合适模型时记录检索范围和否定结果，不强行下载替代品。
20. **论文级复现包**：固定数据、随机种子、模型版本、GPU 选择、配置和结果格式，补齐许可证/出处、失败案例和消融图表，再讨论顶会投稿定位。
21. **凭据生命周期整理**：检查临时 API 凭据是否仍在本机文件或环境变量中，使用后清理运行日志和临时副本；任何凭据都不写入 Git 或公开文档。

## 执行规则

- 自动化按每 15 分钟一轮、最多 88 轮运行；每轮从本表选择下一个未完成项目，记录代码、实验、状态机和验证结果。
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
- **工具与 benchmark**：隔离下载并固定版本的推荐 benchmark（优先小体积代码/任务元数据）；BFCL 官方执行、tau 系列、ToolSandbox/BrowserGym 等必须分别记录许可证、环境和可比性，禁止把候选覆盖当官方成绩。
- **扩散与状态机**：并行 proposal 的净延迟、接受率和副作用隔离；错误摘要、决策图导出和自动边编译必须经过回放、漂移检测和人工复核。
- **研究与发布**：相关工作/新颖性继续以“组合接口候选”表述；论文实验保持 TODO，模型权重、数据集和凭据不进 Git。

本审计还发现两类容易混淆的表述，已统一修正：同步 VirtualOptionManager 已有机制实现，但统一生产调度器、异步 prefetch、学习型 replacement、真实 Jev scaling 仍未完成；固定 resident 在合成缺失目标实验中的 0% 是该策略的任务成功率，不是系统总体指标，也不代表 Jev 或 runtime 已“爆炸”。
