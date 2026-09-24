# Jev Agent Prototype

This repository is a research runtime for agents backed by bounded decision models. Jev is the current backend; the runtime exposes virtual option spaces, resident context, paging, refinement, tool execution, and explicit recovery paths.

The project has two installation profiles:

* **Core / no language model:** the scripted chooser runs the workspace-local file, JSON, review, and restricted-command tools. It is useful for smoke tests and does not claim Jev quality.
* **Helper model:** install `pip install -e ".[models]"` and follow [the helper setup guide](docs/QUICKSTART.en.md) to enable a small Transformers model for candidate proposals. Model weights stay outside Git.

## Quick start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
jev-agent --workspace .\agent_workspace
```

Inside the REPL, use `:tools`, then `:plan file.search {"text":"TODO","path":"."}` and `:approve`. The scripted backend is deterministic. For a real provider, pass `--live --key-stdin` and pipe the key through standard input.

Run the test suite with `python -m unittest discover -s tests -v`. Read [the Chinese README](README.md), [the English design](docs/DESIGN.en.md), and [the publishing guide](docs/PUBLISHING.zh-CN.md) for research scope and evidence boundaries.

## Status

This is an active prototype. Long-form live Jev generation, production scheduling, and broad benchmark coverage are still being evaluated. See the reports under `docs/reports/` before interpreting a number as an end-to-end agent result.
