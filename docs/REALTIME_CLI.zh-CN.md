# 实时交互 Agent 原型

## 启动

在仓库根目录执行：

```powershell
python -m jev_agent.cli --workspace agent_workspace
```

默认使用本地 scripted chooser，不需要 API key；它用于检查工具边界和交互流程，不代表 Jev 的选择质量。连接真实 Jev 时：

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

`:plan` 只构造候选，不执行工具；`:approve` 才执行当前 Candidate。每个参数先经过 `ArgumentInput` 的候选选择、schema 校验和 revision guard，整组通过后才进入 `Agent` 的最终 Jev 选择。普通文本只记录为 observation，不会自动调用 shell。

支持的第一版工具包括文件读取、写入、搜索、精确替换、目录创建、JSON 读写、受限命令、人工复核和停止控制。所有路径都限定在 workspace；命令使用 `shell=False`、argv 传递、cwd 限定和有界输出。程序 allowlist 不是 OS 沙箱，启用 Python 或其他程序时只应使用隔离 workspace/Docker。

trace 写到 `<workspace>/.jev_trace.json`，只保留结构化结果摘要，不复制文件正文或完整命令输出。当前脚本是可运行原型：没有自然语言到任意 shell 的自动规划，也没有浏览器/桌面控制；后续再接真实 Jev tool routing、memory paging 和 A/B/C workload。
