# 外部 benchmark 下载清单

本目录用于隔离外部 benchmark 的源码与数据，仅作调研和后续适配入口。仓库默认忽略目录内容；模型权重、运行时生成数据和大规模 benchmark 数据不提交到本项目。

| Benchmark | 来源 | 固定 commit | 许可证 | 本地状态 | 体积（约） | 运行说明 |
|---|---|---|---|---:|---:|---|
| AgentBench | https://github.com/THUDM/AgentBench | `d1e4a10db08c87075c78972e48ecc182be03e2d5` | Apache-2.0（见目录 LICENSE） | 已下载 shallow clone | 43.5 MB | 覆盖 DB、KG、DCG 等任务；先阅读各任务 README，运行可能需要服务、API 或额外数据。 |
| BrowserGym | https://github.com/ServiceNow/BrowserGym | `9e779f087de9a65668b6974d11f9ce9816026e96` | Apache-2.0（见目录 LICENSE） | 已下载 shallow clone | 2.7 MB | 提供浏览器任务环境；WorkArena 作为 BrowserGym 的任务生态使用，需要浏览器和外部服务配置。 |
| tau-bench | https://github.com/sierra-research/tau-bench | `59a200c6d575d595120f1cb70fea53cef0632f6b` | MIT（见目录 LICENSE） | 已下载 shallow clone | 59.8 MB | 工具调用与状态变化任务；运行前按 README 安装依赖并配置所需服务。 |
| ToolBench | https://github.com/OpenBMB/ToolBench | `d56fdd89faf8c91fa135090b212bb9057ee5cfc2` | Apache-2.0（见目录 LICENSE） | 已下载 shallow clone | 15.1 MB | 大工具空间和 API 调用压力测试；这里只保留源码入口，未下载模型权重或完整大数据。 |
| BFCL | https://github.com/ gorilla-llm | — | 已有本项目 `benchmarks/data/bfcl-v4-exec-simple` | 未重复下载 | — | 已有最小执行集和结果；后续可作为补充基线。 |

## 下载约束

- 这些目录是 shallow clone，仅保留当前下载时的 commit；更新时重新记录 commit、许可证和体积。
- 不把外部源码、大数据、缓存、模型权重加入 Git。运行生成物放在 `benchmarks/results/` 或外部临时目录。
- BrowserGym/WorkArena、AgentBench 部分任务和 tau-bench 可能依赖浏览器、数据库、模拟服务或 API；本项目暂不声称已经可直接复现。
- 推荐先做适配层和小规模 smoke test，再申请完整数据或服务。
