# 中文快速开始

## Core 模式：不下载模型

Core 安装不需要 GPU、模型权重或 API key，使用确定性的 scripted chooser 检查工具协议、workspace 边界和审批流程：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
jev-agent --workspace .\agent_workspace
```

也可以直接运行：

```powershell
python -m jev_agent.cli --workspace .\agent_workspace
```

`:tools` 查看工具，`:plan file.search {"text":"TODO","path":"."}` 创建候选，`:approve` 才允许副作用。Core 模式是协议 smoke test，不代表 Jev 质量。

## 可选 0.8B helper

需要本地 logits proposal 时再安装可选依赖：

```powershell
pip install -e ".[models]"
```

模型权重放在仓库外的 Transformers cache 或用户指定目录，不进 Git。CPU 可以做功能检查；GPU、量化和显存设置取决于本机 Torch 环境。

## Live Jev

不要把 key 写进命令行参数或仓库。建议从安全凭据来源读入，再通过 stdin：

```powershell
python -m jev_agent.cli --live --workspace .\agent_workspace --key-stdin
```

工具执行仍必须经过 `:plan` → `:approve`，workspace 外路径、未批准命令和未验证候选都会被拒绝。

## 开发检查

```powershell
python -m unittest discover -s tests -v
python -m compileall jev_agent jev_tools
```

当前统一同步 runtime 的最小入口是 `DecisionRuntime.step()`；旧版 `JevAgentOrchestrator` 仍保留用于兼容和历史实验。完整实验结果见 `docs/reports/`，原始模型权重、凭据和完整私有 trace 不进入仓库。
