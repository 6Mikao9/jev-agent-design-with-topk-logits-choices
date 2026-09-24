# 实时交互 Agent 原型

## 启动

在仓库根目录执行：

```powershell
python -m jev_agent.cli --workspace agent_workspace
```

启动后会显示当前 backend 和可用工具数量。默认使用本地 scripted chooser，不需要 API key；它用于检查工具边界和交互流程，不代表 Jev 的选择质量。连接真实 Jev 时：

```powershell
$env:TYPESAFE_API_KEY = "从安全凭据来源读取的 key"
python -m jev_agent.cli --live --workspace agent_workspace
```

也可以用 `--key-stdin` 从标准输入读取 key。key 不接受命令行参数，不写入 trace。若要显式启用项目内 Python 命令，需要额外传 `--allow-command python`；默认命令只有只读 Git 子命令。

## 交互命令

```text
:help
:tools
:goal 检查当前项目配置
:plan file.search {"text":"TODO","path":"."}
:approve
:trace
:stop
:quit
```

`:plan` 只构造候选，不执行工具；`:approve` 才执行当前 Candidate。每个参数先经过 `ArgumentInput` 的候选选择、schema 校验和 revision guard，整组通过后才进入 `Agent` 的最终 Jev 选择。普通文本只记录为 observation，不会自动调用 shell；它会递增任务 revision 并清除尚未审批的候选，`:goal` 也是如此。未知的 `:command` 会报错，不会被当成任务文本。每次 `:approve` 尝试都会消费候选，包括失败、停止和人工复核结果，不能重复审批同一动作。

支持的第一版工具包括文件读取、写入、搜索、精确替换、目录创建、JSON 读写、受限命令、人工复核和停止控制。所有路径都限定在 workspace；命令使用 `shell=False`、argv 传递、cwd 限定和有界输出。程序 allowlist 不是 OS 沙箱，启用 Python 或其他程序时只应使用隔离 workspace/Docker。

工具执行结果会在终端显示有界内容（最多约 8 KB），因此文件读取正文、搜索匹配、目录项和命令输出都可见；持久 trace 只保留结构化摘要，不复制文件正文或完整命令输出。每次会话写入 `<workspace>/.jev_traces/session-<id>.json`，不会覆盖旧会话；trace 路径若解析到 workspace 外或经过 symlink 会被拒绝。当前脚本是可运行原型：没有自然语言到任意 shell 的自动规划，也没有浏览器/桌面控制；后续再接真实 Jev tool routing、memory paging 和 A/B/C workload。
