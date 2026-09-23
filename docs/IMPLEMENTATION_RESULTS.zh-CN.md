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
