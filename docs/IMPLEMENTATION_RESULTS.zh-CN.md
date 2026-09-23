# 原型实现与首轮实测

本文补充 v0.6 设计文档，记录当前公开原型的实现边界和可复现实验。原始大文件结果保存在本地 `benchmarks/results/`，默认不会进入 Git；公开仓库保留脚本、测试和本摘要。

## 已实现模块

- `jev_agent/agent.py`：工具候选校验、执行、回退和显式恢复动作。
- `jev_agent/topk.py`：辅助模型 logits、精确 token ID 回灌、边界安全解码，以及 `END_DIALOGUE` 完整性控制。
- `jev_agent/models.py` 与 `memory.py`：依赖版本传播、按影响召回记忆和局部失效。
- `jev_agent/jev_client.py`：直连 TypeSafe System One 的 Jev Choice 适配器；密钥只从进程环境读取，不写入仓库。
- `jev_agent/orchestrator.py`：将两阶段页表读取、现有工具 Agent 和状态/错误 trace 串成可回放的单次执行闭环；它是垂直切片，不是完整规划器。
- `jev_agent/virtual_option.py`：同步 Virtual Option Space 原型，提供稳定虚拟 ID、有限 resident set、page-in/page-out、LRU、revision/stale、`OptionFault`/`RefineFault` 和基础 refine；异步 prefetch、跨空间 resolver 和大规模 fault loop 仍待实现。
- `jev_agent/context_residency.py`：Context-space 的 pinned/working/cold 基线，支持按类型 aging、utility reward、hysteresis、minimum residency 和 `ContextFault`；当前是确定性 lexical policy，尚未接入向量 RAG 或统一 fault scheduler。
- `jev_agent/decision_model.py`：可替换 `DecisionModel` 边界，以及 Jev/Choice 适配、Replay 和 Oracle backend；Oracle 只用于机制上界，不代表模型质量。
- `benchmarks/`：合成控制流、BFCL 候选覆盖、同上下文 top-k 重合、对话 trace 和速度拆分脚本。

## 评估证据边界与收敛计划

当前证据主要覆盖 runtime primitives 和受控机制边界：Virtual Option/Context、orchestrator 垂直切片、helper raw-logits/KV cache、BFCL/top-k 候选覆盖、top-k overlap、synthetic fallback、needle/对抗词法控制、两阶段 memory controls、少量真实 Jev Choice replay 和 parameter prior。它们没有组成真实长轨迹 Jev agent 的质量结论。

下一阶段按三条主线收敛：A) Decision-space virtualization；B) PAGE/REFINE/FALLBACK progressive recovery；C) dynamic context residency，最后用一个 20–100 步 decision-dense workload 串联三者。真实实验必须分别报告 missing detection、page localization、recovery success 和 end-to-end success；当前 synthetic page-recovery 的目标页由程序预先知道，因此属于机制上界，不能替代 retrieval→Jev→recovery 的真实结果。`P(EXPAND | target ∉ resident)` 只描述触发条件行为，不是完整 paging 质量指标。masked diffusion 的直接 proposal 负结果可保留为 appendix negative result。

## 候选覆盖结果

在 8 个固定中英文上下文上，Qwen3.5-0.8B 与 Qwen3.8-27B 使用相同的 248,077 项词表。Qwen3.5 top-k 与 Qwen3.8 top-k 的平均交集为：

| k | 平均交集 |
| ---: | ---: |
| 10 | 6.75 |
| 20 | 12.38 |
| 50 | 32.5 |
| 100 | 61.75 |
| 250 | 149 |

Qwen3.8 的 top-1 token 在 Qwen3.5 top10 中的 8 个上下文里都被保留；但整个 Qwen3.8 top10 集合中，平均有 32.5% 不在 Qwen3.5 top10。旧 Qwen3-0.6B 的词表不同，因此按 decoded token piece 比较：Qwen3.8 top-1 在其 top10 中有 25% 的上下文落选，top10 集合平均只有 53.75% 被保留。

## 自然语言对话与冲突澄清

27B 代理的四个样例通过了题目专属结束判定：算术、TCP/UDP、备份清单和 Friday/Saturday 冲突。该冲突提示已明确要求寻找矛盾，不能验证系统自主检测冲突的能力。0.8B 代理也通过结束判定，但把原文“想周五出发”改写成“必须周五出发”，未忠实引用。完整原文见[回答样例](../benchmarks/examples/dialogue-proxy.md)。`END_DIALOGUE` 和这些启发式检查用于控制结束，不构成语义正确性的证明。

本轮长回答使用 `local_top1_proxy`，不能据此推断 Jev 的语言能力。HTTP 对话脚本提供真实 Jev 接口分支；独立 0.8B 脚本仅支持代理。真实 Jev 逐 token 长回答实验尚未完成。

## 速度拆分

在 top100 的 Qwen3.5-0.8B helper 运行中，四题平均候选生成耗时为 6,337.62 ms，local chooser 耗时为 0.12 ms，端到端吞吐为 10.93 tokens/s。对照的 Qwen3.8-27B top20 SGLang 运行分别为 4,782.54 ms、0.19 ms 和 16.96 tokens/s。

这些为历史原型计时，不是公平模型对比：0.8B 使用全前缀 Transformers，27B 使用 SGLang HTTP 服务；答案长度不同，未进行重复暖机评测。0.8B 的原计时代码未显式同步 CUDA，helper 分项不能视为可靠 GPU 执行耗时。真实 Jev 延迟尚未测得。后续需要同步计时、相同推理栈和缓存策略。排名已经直接使用 raw-logit topk；生成候选仍需要主干网络和 LM head，不能只靠 LM head 推理。

### 0.8B 原始 logits + KV cache 对照

在远端 Docker 的空闲 GPU 2 上，用同一份 Qwen3.5-0.8B、同一上下文和 32 个 top-1 续写步，显式同步 CUDA 对比 full-prefix 与 `FastLogitsHelper`：

| 路径 | 总耗时 | 吞吐 |
| --- | ---: | ---: |
| 每步重算完整前缀 | 2,541.25 ms | 12.59 tok/s |
| 首次 prefill + 单 token KV decode | 694.00 ms | 46.11 tok/s |

KV 路径 prefill 为 76.28 ms，decode 为 617.72 ms；两条路径的 top-1 序列 32/32 一致，按 full-prefix 总时间除以 KV decode 时间为 4.11 倍，按总时间为 3.66 倍。该数字只说明缓存和 raw-logit 排序的模型 forward 收益，不包含 Jev、网络或工具调用，也没有和 27B 做质量等价声明。可用 `benchmarks/benchmark_kv_cache.py` 重跑；结果原文件留在远端项目的 `benchmarks/results/`，模型权重未进入 Git。

## BFCL 候选覆盖（Qwen3.5-0.8B）

固定 BFCL V4 `exec_simple` 100 题中的 seed-2026、30 题样本，在远端单张空闲 RTX 5090 上 teacher-forced 运行 647 个参考 token，用时 55.449 秒。候选覆盖为：`k=1` 89.49%、`k=8` 100%、`k=32` 100%；oracle 在 `k=8` 和 `k=32` 均可覆盖完整 30/30 个参考调用。这个结果只说明正确 token 是否出现在 helper 候选集合，不代表 Jev 选择准确率、工具执行成功率或 BFCL 官方榜单成绩；原始 JSON 留在远端 `benchmarks/results/`，不进 Git。

## 隔离控制流基线

合成 6 个场景的脚本化控制流检查显示：proposal-only 的 oracle 完成率为 33.33%，显式 Top-k 回退和 always-Top-k 均为 83.33%；两种回退策略的 oracle action accuracy 都为 100%，但平均 helper calls 分别为 15.67 和 20.67。该套件的 chooser/helper 读取了场景金答案，只验证状态机、澄清和失效恢复，不能当作模型或 Jev 质量结果。

## DecisionModel capability 与 page recovery 机制基线

新增 `benchmarks/benchmark_backend_capability.py`，在逻辑选项规模 10/100/1K/10K/100K、resident `K=8/16/32` 上比较固定 resident set 与 synthetic `PAGE/EXPAND`。100K、backend capability=1.0、5 次抽样的结果为：固定 resident 在三种 K 下成功率均为 0%，page-expand 均为 100%；每组都保持 resident 上限，额外 page-in 为 5 次。该实验只验证“正确选项缺失时 page-in 能恢复”的机制，不包含 Jev 判断、真实任务质量或网络成本。

这里的 `success_rate` 是端到端合成指标，必须和三个分项一起看：`coverage_rate` 表示目标最终是否进入 resident set，`resident_decision_success_rate` 表示目标已经可见时 synthetic backend 是否选中，`recovery_rate` 表示初始 `OptionFault` 被 PAGE/EXPAND 修复的比例。因而大逻辑空间下 fixed-resident 的 0% 是“永不分页导致目标不可见”的覆盖下界，不是 Jev 或整个 runtime 的真实任务准确率；`initial_page_ins` 是每轮初始化成本，`recovery_page_ins` 才是额外恢复成本。

## 小型 masked-diffusion proposal 试验

从 [BabyLM 2026 Strict-Small MDLM 模型卡](https://huggingface.co/amosluna/babylm-2026-strict-small-mdlm-seed42) 下载了 Apache-2.0 的 98.4M 参数 checkpoint（约 377 MiB，权重不进 Git），在远端空闲 GPU 2 上成功加载。三个不同长度/去噪步数的完整 proposal 通过 `ParallelCandidateGenerator` 并行调度，单次约 0.34–0.44 秒；这是接口和调度验证，不是质量结果。

初始无约束运行会在所有位置生成 `[EOS]`，加上特殊控制 token 抑制后，英文样例仍出现大量重复词或乱码片段。这个失败很有价值：masked-diffusion 的双向去噪输出不能直接当作 AR next-token logits，必须有长度/特殊 token 约束、结构化 validator 和 Jev 的拒绝/重提案出口。该实验暂不把候选交给真实 Jev，也没有执行任何工具。

## 已知限制与护栏

依赖版本、记忆召回和 `CLARIFY/STOP_UNRESOLVED` 已有基础实现；结构化 state packet、`REVIEW` 通道和通用精确算术路由仍是拟议优化，尚无缓解收益实验。用户提供的 Context Rot / No Rationale 等描述作为待检验假设保留，尚未独立核实其来源或因果解释。详细说明见 [JEV_LIMITATIONS_AND_GUARDRAILS.md](JEV_LIMITATIONS_AND_GUARDRAILS.md)。

## 两阶段页表的真实 Jev Choice 回放

2026-09-24 使用临时进程凭据直连 TypeSafe Choice，未把凭据写入仓库或结果。清晰请求的一次回放完成了两次 Jev 选择：第一阶段保留 `departure` 页，第二阶段选择 `TOP_1`（候选池只有一页时的安全降级），最终读取 22 字节原文；两次 Jev 请求耗时约 1.08 秒和 1.71 秒，总耗时约 2.79 秒。另一次故意含糊的请求触发了 `CLARIFY`，没有读取原文。两次结果都验证了 `NONE/CLARIFY/STOP` 和明确读取边界，但样本太小，不能说明检索质量或概率校准收益。

## 超远捞针 lexical 控制矩阵

`benchmarks/benchmark_needle_matrix.py` 在 100/1,000/10,000 页、40/160 个噪声词和首/中/尾三种针位置上运行 18 个配置，`limit=16`。2026-09-24 的 18/18 个配置都找回了显式注入的针页，每个配置只返回 1 个候选；100、1,000、10,000 页的选择耗时中位数约为 0.15、1.46、15.0 ms。该结果只说明 PagedMemoryIndex 的精确词法粗筛在这个有利构造下随页数近似线性增长，不能外推到语义检索、摘要丢失、相似干扰、多针或真实 Jev 质量。

## 超远捞针 adversarial lexical 控制

随后运行 `benchmark_needle_adversarial.py` 做负向控制：100 页、`limit=16`、目标固定在最后一页时，摘要含完整查询词的 case 命中；事实只出现在正文、摘要使用同义改写时均漏失；前面放置 32 个相同查询词的 decoy 页时也因候选上限漏失。这些是词法粗筛的预期边界，不是 Jev 选择失败，后续需要语义摘要、混合检索和自适应 page materialization。

## 两阶段记忆控制矩阵

新增 `benchmarks/benchmark_memory_matrix.py`，在无网络 replay chooser 下覆盖五条路径：单页读取、两页歧义读取、无候选、单页超出读取预算、计数选择后页面变 stale。2026-09-24 五个 case 分别得到 `read_complete`、`read_complete`、`no_candidates`、`read_budget_exceeded`、`stale_selection`；单页和双页读取分别为 22 和 46 字节。该结果验证边界和阻断逻辑，不代表真实 Jev 的排序质量。

## 候选回退控制流复跑

2026-09-24 在远端重新运行 `benchmarks/run_synthetic.py`，报告副本为 `benchmarks/results/synthetic-control-flow-latest.json`，远端原始文件为 `/tmp/synthetic-control-flow-latest.json`。6 个脚本场景中，proposal-only 完成 2/6（33.33%），显式 Top-k fallback 和 always-Top-k 都完成 5/6（83.33%）；显式 fallback 平均 helper 调用 15.67 次，always-Top-k 为 20.67 次。chooser/helper 读取脚本金标准，因此这些是控制流上界，不是 Jev 或模型质量结果。

## 第一轮真实 Jev recovery action benchmark

2026-09-24 使用直连 TypeSafe Choice 运行 `benchmarks/benchmark_jev_recovery.py` 的 6 个受控 case：resident valid→`COMMIT`、target missing→`PAGE`、coarse option→`REFINE`、ambiguous pages→`CLARIFY`、stale revision→`STOP`、schema gap with page available→`PAGE`。6/6 选择与预期一致；平均 Jev 请求耗时约 1,973.5 ms，范围约 795.0–4,214.9 ms。报告为 [jev-recovery-live.json](../benchmarks/results/jev-recovery-live.json)，不含凭据。该结果只验证受控 action contract，不代表 page localization、端到端执行成功或长轨迹稳定性。

## 真实 Jev recovery action 第二轮

将受控 action cases 扩展到 12 个后，2026-09-24 得到 COMMIT 1/1、PAGE 4/4、REFINE 2/2、CLARIFY 2/2、STOP 3/3，混淆矩阵无误选。平均请求耗时 2,097.8 ms，中位数 1,156.0 ms，范围 856.6–4,428.3 ms。报告为 [jev-recovery-live-12.json](../benchmarks/results/jev-recovery-live-12.json)。它仍只测 Jev 是否遵守受控 runtime action contract，没有执行工具副作用，也没有测 page localization 或长轨迹稳定性。

## 真实 Jev retrieval→recovery 闭环 smoke

新增 `benchmarks/benchmark_jev_closed_loop.py`，把 live Jev action、`PagedMemoryIndex`/`TwoStageMemorySelector`、`VirtualOptionManager` 的 page-in/refine 和无副作用模拟执行串起来。首轮发现 `REFINE` 后父选项仍留在 resident set，导致第二次决策重复选择 `REFINE`；已修复为子页 materialize 后移除父候选，并加入回归测试。修复后四个 case（resident commit、missing-page recovery、coarse refine、ambiguous clarify）全部完成预期终态，3 个到达模拟执行，1 个安全澄清。报告为 [jev-closed-loop-fixed2.json](../benchmarks/results/jev-closed-loop-fixed2.json)。这仍是小型 smoke，不是长轨迹或真实工具副作用评测。

## 24 步 decision-dense workload 控制基线

远端运行 `benchmarks/benchmark_decision_dense_workload.py` 得到 24 步轨迹：11 次 COMMIT、4 次 PAGE、2 次 REFINE、2 次 ContextFault、1 次 stale revision、1 次 CLARIFY、3 次 STOP。resident 上限 4、观测峰值 4；context 上限 3、观测峰值 3；共 6 次 fault、12 次 recovery、11 次模拟副作用，外部副作用为 0，总成本 30.0 units。报告为 [decision-dense-workload-latest.json](../benchmarks/results/decision-dense-workload-latest.json)。这是 oracle/control-flow 基线，不代表真实 Jev 决策质量。

## 真实 Jev decision-dense smoke

新增 `benchmarks/benchmark_jev_decision_dense_live.py`，把真实 Jev Choice 接口接到一个 8 步、状态逐步变化的本地 workload：resident `COMMIT`、缺失页 `PAGE`、恢复后 `COMMIT`、粗粒度候选 `REFINE`、细化后 `COMMIT`、歧义 `CLARIFY`、stale `STOP` 和冷上下文 `PAGE`。2026-09-24 直连运行得到 8/8（100%）动作正确，3 次受控 recovery，3 次无副作用模拟执行；resident 峰值 2/4、context 峰值 2/2。首轮平均 Jev 请求耗时 7,641.5 ms，其中 11.6–19.4 s 的长尾明显；记录 token 数后再次运行得到平均 2,535.2 ms，最大 5,974.9 ms，输入 433–484 tokens、输出 56–75 tokens，动作仍为 8/8。报告为 [jev-decision-dense-live.json](../benchmarks/results/jev-decision-dense-live.json) 和 [jev-decision-dense-live-rerun.json](../benchmarks/results/jev-decision-dense-live-rerun.json)，均不含凭据。

相对预期：动作正确率比 smoke 最低预期更好；延迟比生产目标更差且跨运行波动很大，不能外推到长轨迹、复杂检索或真实工具副作用。

## Jev 延迟分解与长尾诊断

新增 `benchmarks/benchmark_jev_latency_breakdown.py`，用直连 HTTPS 分开记录连接建立、收到响应头前的等待（TTFB 加 API 网关/服务端等待）和响应体读取。有效 key 的 fresh-connection 运行完成 7/8 个请求：每次 DNS/TCP/TLS 建连约 0.32–0.49 s，响应体读取约 0.02 ms，但响应头等待从 0.38 s 到 6.28 s 不等，另有一次 30 s 读取超时。报告为 [jev-latency-breakdown-fresh.json](../benchmarks/results/jev-latency-breakdown-fresh.json)。同一 payload 的持久连接对照 8/8 成功，平均 635.7 ms、P95 823.5 ms、最大 1,041.9 ms，报告为 [jev-latency-breakdown-valid.json](../benchmarks/results/jev-latency-breakdown-valid.json)。

结论：7.64 s 的首轮均值主要来自跨境 HTTPS 路径和 API 网关/服务端排队或推理的 TTFB 长尾；新建 TLS 连接是每次约 0.3–0.5 s 的次要固定成本。响应体、JSON 解析、本机 GPU、helper 和应用层重试都不能解释 4–19 s 的长尾：客户端没有应用层重试，payload 只有约 433–484 input tokens，body 读取约 0.02 ms。工程上优先使用带连接池的直连 HTTP 客户端（保留 `trust_env=False` 和 TLS 校验）、记录 request-id/TTFB、设置超时与重连；算法上减少串行 Jev 调用，在高置信稳定状态走本地安全 fast path，只在 fault、分叉、低置信或 `END_DIALOGUE` 节点调用 Jev，并把 helper 预取与网络请求重叠。持久连接对照相对预期明显更好，但服务端 TTFB 仍需单独优化或换低延迟区域/端点。

## 多物理工具与多虚拟页的真实 Jev 选择

新增 `benchmarks/benchmark_multi_page_tool_selection.py`。实验把 18 个物理工具划分到 6 个虚拟页，resident 上限为 2；Jev 第一阶段只看到用户 query 和 6 个页摘要，必须选择 `PAGE:<page_id>`、`CLARIFY` 或 `STOP`，系统随后只 materialize Jev 选中的页，第二阶段再让 Jev 从该页的 3 个工具中选择。目标页和目标工具只用于事后评估，没有进入 Jev state/options，也没有执行工具副作用。

2026-09-24 真实 Jev 运行 12 个 case：10 个需要选页、2 个故意含糊。页定位 10/10，页内工具选择 10/10，澄清 2/2，最终成功 12/12；共 22 次 Jev 调用，resident 上限 2，单 case 总延迟 P50 1,296.6 ms、P95 1,438.4 ms，外部副作用为 0。报告为 [multi-page-tool-selection-live.json](../benchmarks/results/multi-page-tool-selection-live.json)。

同一 case 的确定性词法控制只有页定位 60%、页内工具选择 50%、澄清 0%、最终成功 58.3%，报告为 [multi-page-tool-selection-latest.json](../benchmarks/results/multi-page-tool-selection-latest.json)。相对预期：真实 Jev 在这个单跳、多页、小 resident 上限实验中明显好于控制，也超过了最低预期；但还没有证明多跳错误页恢复、更大的页目录、长轨迹或真实工具副作用。

## 22 步真实 Jev A/B/C 串联 workload

新增 `benchmarks/benchmark_jev_decision_dense_serial.py`，把 context page、虚拟工具页、页内工具选择、REFINE、提交、CLARIFY 和 stale STOP 串成同一条 22 步轨迹。真实 Jev 的第一次运行保留为失败对照：19/22（86.4%），`page_files` 误选 `CLARIFY`，下一步在空 resident 上继续选工具并误选 `PAGE`，`commit_query` 又把 resident 工具 ID 当成动作返回；这说明孤立动作 100% 不能直接外推到串联轨迹。原始报告为 `benchmarks/results/jev-decision-dense-serial-live.json`。

针对这三个错误，runtime 增加了两处保护：工具决策前先用不含评估目标的词法页目录检查候选页是否 resident，缺失时重新走 PAGE recovery；提交、REFINE、CLARIFY 和 STOP 使用只含控制动作的选项面，把候选选择与动作选择分开；COMMIT 只有在已有 validated candidate 时才产生模拟副作用。修复后的直连复跑得到 22/22（100%）、4 次 fault、13 次 recovery、4 次模拟执行，resident 峰值 4/4、context 峰值 2/2、外部副作用 0，平均 Jev 请求 1,019.6 ms。报告为 [jev-decision-dense-serial-live-rerun.json](../benchmarks/results/jev-decision-dense-serial-live-rerun.json)。

相对预期：机制边界和最终动作正确率好于修复前，且保持了 resident/context 上限；代价是每步仍需真实 Jev，平均延迟高于离线 contract，尚未证明 20–100 步长轨迹、错误页多跳恢复或真实工具副作用。下一步先加入一个显式错误页恢复 case 验证 recovery gate，再扩大到 20–100 步并比较 fixed resident、retrieval 和 virtual paging。

随后用 `--inject-page-miss` 故意把首次文件页决策改成 `CLARIFY`，只检验 runtime 是否阻止空 resident 直接进入工具层。真实 Jev 运行记录 1 个 `OptionFault`、1 次 `page_recovery`，恢复调用返回 `PAGE:files`，随后 `files:read_file` 选对；`blocked_invalid_tool_calls=1`、`page_recovery_successes=1`、外部副作用仍为 0。由于首个错误是实验器故意注入，原始 22 步决策准确率为 21/22（95.5%）不应与正常复跑的 22/22 混为一谈。报告为 [jev-decision-dense-serial-live-injected.json](../benchmarks/results/jev-decision-dense-serial-live-injected.json)。相对预期：门控行为符合预期，且没有错误工具副作用；下一步再扩展到空页、错误页和 stale 页的矩阵。

## Recovery gate 四状态矩阵

新增 `benchmarks/benchmark_recovery_gate_matrix.py`，在不调用网络或真实 Jev 的控制实验中，将 files、calendar、database、browser 四个页分别置于 `empty`、`wrong_page`、`stale`、`correct_resident` 四种状态，共 16 cases。gate 在 12 个非正确 resident case 中全部阻断非法工具解析；stale 页先刷新 revision 再 page-in，16/16 页内选择正确、16/16 端到端成功，resident 峰值 2/2，外部副作用 0。报告为 [recovery-gate-matrix-latest.json](../benchmarks/results/recovery-gate-matrix-latest.json)。相对预期：机制结果符合预期，证明门控、stale refresh 和页内选择边界已打通；这是 manager 上界，不能替代真实 Jev 的页定位质量。

同一 16-case 矩阵随后接入真实 Jev，脚本为 `benchmarks/benchmark_recovery_gate_live.py`。Jev 只接收自然语言 query、四个页摘要和当前 materialized page 的工具选项；target page/tool 只用于事后断言。真实运行中 12 个非 resident case 全部先被 gate 阻断，页恢复、页内选择和端到端均为 100%，`blocked_invalid_tool_calls=12`，resident 峰值 2/2，外部副作用 0；所有 case 总延迟 P50 1,306.3 ms、P95 1,346.9 ms。报告为 [recovery-gate-live-latest.json](../benchmarks/results/recovery-gate-live-latest.json)。相对预期：真实 Jev 在这个小页目录、短 query 矩阵上达到预期；这仍不能外推到更大页目录、语义相似干扰或多跳错误恢复。

## Radix/trie 参数候选设计判断

基数树适合把工具名、字段名、枚举值、路径片段和历史成功参数按共享前缀组织起来。它能减少候选描述和候选物化，并让 helper 同时预测互相独立的字段或预取下一层；候选仍需进入 Jev 的 OptionSpace，不能绕过 Jev 决策。对连续自由文本参数，基数树收益有限，应退回 schema/grammar validator 或普通 proposal。该方向已加入 roadmap，后续用参数 recall@K、非法参数率、候选物化时间、Jev 调用数、helper/网络 overlap 和副作用做验证；扩散 proposal 暂留为可选后续路线，当前小型 masked-diffusion 的质量边界不足以作为主线。
