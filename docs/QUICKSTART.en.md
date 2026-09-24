# Quick start and installation profiles

## Core profile (no model weights)

The core package has no mandatory network or model dependency. From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
python -m jev_agent.cli --workspace .\agent_workspace
```

The default scripted chooser is deliberately deterministic. It lets contributors inspect tool schemas, planning, approval, workspace confinement, and structured traces without an API key or GPU. It is a protocol smoke test, not a language-model benchmark.

## Optional 0.8B helper

Install the optional dependencies only when you need local logits proposals:

```powershell
pip install -e ".[models]"
```

Download model weights into a user-selected cache outside this repository and configure the helper through the benchmark or integration script. Do not commit weights, credentials, `.jev_traces`, or generated benchmark results. A CPU run is supported for functional checks; GPU and quantization settings depend on the installed Torch build.

## Live Jev

```powershell
$env:TYPESAFE_API_KEY = "read this from a secret manager"
python -m jev_agent.cli --live --workspace .\agent_workspace --key-stdin
```

The CLI accepts a key on stdin so it does not appear in shell history. Keep the workspace isolated. `:plan` prepares a candidate and `:approve` is the only command that permits a side effect.

## Development checks

```powershell
python -m unittest discover -s tests -v
python -m compileall jev_agent jev_tools
```

The project intentionally keeps old research reports under `docs/reports/`; they are evidence snapshots, not current API documentation. Current entry points are this guide, `README.md`, `README.en.md`, and `docs/REALTIME_CLI.zh-CN.md`.
