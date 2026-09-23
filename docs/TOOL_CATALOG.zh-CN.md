# Jev 本地工具目录

`jev_tools` 提供一组可选的本地工具契约，并适配 Jev 的 `ToolDefinition`、已有 JSON Schema 子集校验器和 `ChoiceOption` 候选选择。`build_local_catalog(workspace)` 不启动服务、不连接 Docker、不发起 HTTP，也不控制浏览器/桌面。调用端仍需在执行前进行 schema 校验；建议仅将必要工具传给某次 Agent run。

## 候选选择格式

`catalog_as_choice_options(catalog)` 按注册顺序产生短、稳定的 ID：`tool_01`、`tool_02`……；可用工具的 payload 是 `ToolSpec`。说明文本含工具名、用途和可用状态，便于 Jev 用有限候选 token 选择。`catalog_as_tool_definitions` 只暴露 `available=True` 的工具；它不会替 Jev 选择，也不绕过参数校验。

`catalog.mcp_descriptors()` 可把可执行工具导出成 MCP `tools/list` 形状的纯数据，`catalog.call(name, arguments)` 提供本地分发。两者都不启动 MCP 传输、不连接远端 server；若接 stdio/HTTP，应由外层另行配置信任、超时、网络和进程隔离。

## 工具与参数

所有参数均为 JSON 对象，未列字段由 `additionalProperties: false` 拒绝。`?` 表示可选。

| 名称 | 参数 | 能力/边界 |
|---|---|---|
| `file.read` | `path: string`；`max_bytes?: integer` | workspace 相对路径，默认最多 65,536 字节，硬上限 1 MB；UTF-8 |
| `file.write` | `path: string, text: string` | workspace 相对路径，最多 1 MB；可创建父目录、覆盖目标文件 |
| `file.list` | `path?: string, limit?: integer` | 单层列举；默认 `.`、100 项，最多 500 项 |
| `json.read` | `path: string` | workspace 内 JSON，最多 1 MB |
| `json.write` | `path: string, value: any JSON` | workspace 内格式化 JSON，最多 1 MB |
| `shell.run` | `argv: string[]`；`cwd?: string`；`timeout_seconds?: integer` | `shell=False`；默认仅 `git status/diff/log/show/rev-parse`，工作目录必须在 workspace 内，超时最多 15 秒；stdout/stderr 截断 |
| `http.request` | `method: GET\|POST, url: string`；`headers?: object`；`body?: string` | 占位，不发送请求；需要后续显式实现传输层、域名 allowlist 和策略 |
| `browser.act` | `action: open\|click\|type\|snapshot`；`target?: string` | 占位，不连接浏览器 |
| `computer.use` | `action: observe\|click\|type\|key`；`target?: string` | 占位，不控制桌面 |
| `human.review` | `summary: string`；`risk?: string` | 只产生 `review_required` 记录，不代表批准、不执行后续动作 |
| `control.stop` | `reason: string` | 只产生本地 `stopped` 控制结果 |

### 沙箱边界与集成注意事项

- 路径必须相对 workspace，拒绝 `..`、绝对路径及解析后逃出 workspace 的符号链接。目录列举不递归。实现不能消除并发运行时的符号链接竞态；需要对抗 workspace 内不可信并发写入时，应使用 OS 容器/权限隔离。
- 文件写入会覆盖同名文件，因此上层策略应对有影响的写入选择 `human.review` 或另外配置审批包装器。
- shell 默认不含 `python`、PowerShell 或通用 shell。Git 子命令有读操作 allowlist；集成方传入 `allowed_commands` 扩展时，等同于授予这些程序的代码执行权限，必须自行审计其参数、环境和副作用。
- 所有 schema 是 Agent 所用的轻量子集。直接调用 executor 的内部代码也应先调用 `validate_json_schema`；executor 层仍设有路径、大小、超时等硬边界。
- HTTP、浏览器、电脑使用能力通过候选目录可见，但未由 `catalog_as_tool_definitions` 暴露，且占位执行器只返回 `unavailable`。这让 Jev 可识别“需要此能力”，同时不会误认为已发生外部操作。

## 设计参考、来源与许可范围

本目录只借鉴抽象与接口模式，没有复制第三方实现代码或 schema：

- [Model Context Protocol Python SDK 工具文档](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/servers/tools.md)：函数工具、参数 JSON Schema 与发现/调用分离的概念；SDK 仓库声明 MIT。这里只借鉴概念，不依赖 SDK、不实现 MCP 协议。
- [LangGraph](https://github.com/langchain-ai/langgraph)：工具调用作为有类型输入/输出的图节点的设计思路；LangGraph 仓库采用 MIT。这里没有复制代码，也没有引入 LangGraph 依赖。
- [PydanticAI 工具文档](https://github.com/pydantic/pydantic-ai/blob/main/docs/tools.md) 与 [工具集文档](https://github.com/pydantic/pydantic-ai/blob/main/docs/toolsets.md)：工具定义/工具集合以及按运行时选择可用工具的思路；PydanticAI 仓库为 MIT。此目录没有复制代码或引入 PydanticAI 依赖。

Jev 适配与实现为本仓库新写的代码，继续受本仓库许可约束；参考项目许可证不自动转授给本目录之外的使用者。

## 最小验证

在仓库根目录执行：

```powershell
python -m unittest tests.test_tool_catalog
```
