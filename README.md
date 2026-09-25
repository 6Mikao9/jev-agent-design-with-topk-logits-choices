# Decision-Native Agent Runtime

[中文 README](README.zh-CN.md)

This repository is an open research runtime for bounded, non-generative decision models. It separates open-world capabilities into two manageable logical spaces and exposes only a bounded view to the decision interface when needed:

```text
Open World → Virtual Option Space → Resident Options
           → DecisionModel / Jev → State Transition
                 ↘ Virtual Context Space ↗
```

## Quick start

### Core: runs without downloading a model

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
jev-agent --workspace .\agent_workspace
```

Core mode uses a deterministic scripted chooser. It can exercise workspace tools, candidate approval, and structured traces without a GPU, model weights, or an API key.

### Optional 0.8B helper and Live Jev

```powershell
pip install -e ".[models]"
python -m jev_agent.cli --live --workspace .\agent_workspace --key-stdin
```

Keep model weights outside the repository. Provide the key through stdin or another secure credential source. For complete installation, testing, and boundary details, see the [Chinese quick start](docs/QUICKSTART.zh-CN.md) and the [English quick start](docs/QUICKSTART.en.md).

## Research focus

The project studies a Jev-native agent runtime for non-generative decision models:

```text
Open world → Virtual Option Space → Resident Option Space
           → Jev decision → State transition
```

The main design ideas are:

1. **Decision-space virtualization**: represent logically unbounded tool, action, and parameter spaces as bounded resident sets. `PAGE`/`EXPAND` increase horizontal coverage, while `REFINE` improves candidate granularity.
2. **Explicit runtime semantics**: options carry stable IDs, page ownership, revisions, and dependencies. `OptionFault`, `ContextFault`, `PAGE`, `REFINE`, `INVALIDATE`, `CLARIFY`, and `STOP` are recordable runtime events.
3. **Virtual Context Space**: manage Pinned, Working, and Cold context using utility, aging, hysteresis, and revision checks. The runtime does not assume cross-request prefix or KV-cache hits, so context can be safely rebuilt.
4. **Unified bounded execution**: `DecisionRuntime.step()` connects the `DecisionModel`, option residency, context refresh, result validation, optional execution, and tracing.
5. **Replaceable decision backends**: Jev is the current backend, not the definition of the system. Replay, Oracle, and future typed decision models can reuse the same runtime.
6. **Top-k fallback and progressive refinement**: external helper models may propose complete arguments, fragments, or token candidates. Jev can reject proposals and request bounded recovery, refinement, paging, or clarification.
7. **Decision-aware memory and replanning**: prioritize records that affect current constraints, parameter provenance, and candidate feasibility; invalidate affected evidence after revisions and re-evaluate dependent branches.

These are system-combination research claims. The project does not claim paging, dynamic vocabularies, memory management, or Jev agents as individually novel. System-level claims require oracle-free long-trajectory experiments, ablations, and cost/latency measurements.

## Repository contents

- `jev_agent/`: tool candidates, schema validation, dependency-aware memory, paged memory, `DecisionRuntime.step()`, Jev Choice integration, and Top-k token fallback.
- `benchmarks/`: synthetic control-flow checks, BFCL candidate-coverage experiments, Qwen comparisons, dialogue traces, and speed breakdowns.
- `tests/`: boundary tests for control flow, the tool catalog, KV cache behavior, and concurrent candidates.
- `pyproject.toml`: the core package and optional Transformers/Torch dependencies.

Run the basic test suite:

```powershell
python -m unittest discover -s tests -v
```

## Documentation

- [Chinese quick start](docs/QUICKSTART.zh-CN.md)
- [English quick start](docs/QUICKSTART.en.md)
- [Full technical design (English)](docs/DESIGN.en.md)
- [完整技术设计（中文）](docs/DESIGN.zh-CN.md)
- [Candidate coverage diagnosis](docs/CANDIDATE_COVERAGE.en.md)
- [Optional research directions](docs/OPTIONAL_IDEAS.en.md)
- [Versioning and archive policy](docs/VERSIONING.md)
- [Implementation results](docs/IMPLEMENTATION_RESULTS.en.md)
- [Benchmark status](benchmarks/README.md)
- [External benchmark download list](benchmarks/external/README.zh-CN.md)

## Status and limitations

This is an active research prototype. Long-form live Jev generation, production scheduling, broad benchmark coverage, long-horizon task dependence, and real tool-side-effect safety are still being evaluated. Deterministic and target-conditioned benchmark results should be interpreted as runtime or control-flow evidence rather than as estimates of Jev quality.

Model weights, runtime credentials, generated outputs, and large benchmark data are intentionally kept outside Git. See `benchmarks/results/` and the research reports for local outputs and evaluation boundaries.

The project is an independent research design and is not affiliated with the TypeSafe project. The author identity is intentionally not published. The current prototype version is `v0.7-runtime-prototype`; the initial draft dates from September 23, 2026, and the project remains in progress.
