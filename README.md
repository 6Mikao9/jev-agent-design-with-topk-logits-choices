# Decision-Native Agent Runtime

An open research runtime for bounded, non-generative decision models. The
runtime lets a model with a finite decision interface operate over a much
larger logical space of tools, memories, context blocks, and refinements.
Jev is the first backend we use for live experiments; the runtime API is
intended to remain backend independent.

## Quick start

### Core profile: no model weights

The core profile runs locally without a GPU, model weights, or an API key.
It is a deterministic protocol and workspace smoke test, not a language-model
quality benchmark.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
python -m jev_agent.cli --workspace .\agent_workspace
```

The CLI currently requires explicit structured planning and approval:

```text
:plan file.search {"text":"TODO","path":"."}
:approve
```

`:plan` prepares a candidate and `:approve` is the only command that permits a
side effect. This boundary makes workspace confinement, tool arguments, and
structured traces inspectable without a model.

### Optional 0.8B helper

Install the optional local helper dependencies when you want a small model to
propose natural-language candidates or tool arguments:

```powershell
pip install -e ".[models]"
```

Download weights into a cache outside this repository. Do not commit weights,
API keys, private traces, or generated benchmark output. CPU is sufficient for
functional checks; GPU and quantization settings depend on the installed
PyTorch build. See [the English quick start](docs/QUICKSTART.en.md).

### Live Jev

The live path reads the key from stdin so it does not appear in shell history:

```powershell
$env:TYPESAFE_API_KEY = "read this from a secret manager"
python -m jev_agent.cli --live --workspace .\agent_workspace --key-stdin
```

Keep the workspace isolated and review each proposed action. The current core
CLI is explicit and auditable; a fully autonomous natural-language shell is a
separate research target.

## What this runtime contributes

The central abstraction is a **Virtual Option Space**: a logical space can be
larger than the options resident in one decision request. The runtime pages
and refines that space while preserving stable IDs, revisions, and validation.

```text
Open world
    |
    v
Virtual option/context spaces
    |  PAGE / EXPAND       REFINE
    v                      v
Bounded resident decision surface --> DecisionModel
    |                                  |
    +------------- state transition <--+
                    |
          execute -> validate -> revise/invalidate
```

The current implementation provides:

- `DecisionModel` and `DecisionRuntime.step()` as the shared decision loop;
- virtual option pages with a configurable resident limit (Jev supports at
  most 255 options per request; the runtime reserves room for control
  choices);
- `PAGE`, `REFINE`, `CLARIFY`, `STOP`, and context-refresh transitions;
- bounded context residency with pinned blocks, aging, revisions, dependency
  invalidation, and stable block IDs;
- memory retrieval and evidence recovery with deterministic baselines;
- file and command tool protocols with explicit approval and workspace guards;
- execution validation through `ExecutionVerdict` and the stronger
  `ExecutionReceipt` protocol (`applied`, `rejected`, or `unknown`);
- structured trace edges and a stateful recovery workload.

The design treats paging as horizontal expansion of candidate coverage and
refinement as vertical expansion of candidate detail:

```text
PAGE / EXPAND  --> more logical candidates
REFINE         --> finer candidates for one resident option
```

An uncertain side effect is never retried implicitly. An `unknown` receipt
puts the task in `needs_reconciliation` until an external observer confirms
the result and advances the task revision.

## Evidence and current limits

The latest remote test run passes **159 tests**. These are runtime and
protocol checks, not a claim that Jev has reached production agent quality.
The most useful evidence snapshots are:

- [ExecutionReceipt report](docs/reports/2026-09-24-execution-receipt.zh-CN.md)
  - no automatic retry for uncertain side effects;
- [Execution verdict report](docs/reports/2026-09-24-runtime-execution-verdict.zh-CN.md)
  - stale but well-formed tool output triggers dependency recovery;
- [Stateful recovery workload](docs/reports/2026-09-24-stateful-recovery-workload.zh-CN.md)
  - a bounded scripted control-flow workload;
- [Live answer-blind paging report](docs/reports/2026-09-24-bounded-paging-seed31-live.zh-CN.md)
  - direct and verifier-assisted live Jev paging measurements.

The live experiments still have important limits: some workloads are scripted,
the core CLI is explicit rather than autonomous, and latency includes a noisy
remote service. Results should be read as runtime evidence and failure
boundaries, not as a finished agent benchmark.

## Repository map

```text
jev_agent/       runtime, models, paging, context, memory, and adapters
jev_tools/       file and command tools with approval and workspace guards
tests/            unit and integration tests
benchmarks/      small reproducible workload drivers
docs/            quick starts, design notes, and dated evidence reports
ops/             local automation checkpoints (ignored by Git)
```

The former Chinese landing page is preserved in
[README.zh-CN.md](README.zh-CN.md). The canonical public landing page is this
file. `README.en.md` remains as a compatibility entry point.

## Development

```powershell
python -m unittest discover -s tests -v
python -m compileall jev_agent jev_tools
```

The package has no mandatory runtime dependency. Optional model dependencies
are declared in `pyproject.toml`. Keep credentials, model caches, complete
private traces, and large benchmark artifacts outside the Git tree.

## Research roadmap

The near-term evaluation is organized around three questions:

1. **Decision-space virtualization:** can logical option counts scale while
   the resident decision surface stays bounded?
2. **PAGE/REFINE recovery:** can a missing or overly coarse option be repaired
   without replacing the decision backend?
3. **Context residency:** can dynamic context replacement improve useful
   evidence while keeping a fixed working budget?

Planned follow-up work includes real Jev end-to-end workloads without an
oracle locator, multi-needle and conflicting-evidence tests, P50/P95/cost
accounting, asynchronous materialization, and radix/trie helper overlap.

## Research positioning

We use the phrase *decision-native agent runtime* for the system abstraction,
rather than claiming that the current Jev implementation is the only possible
backend or that every mechanism is unprecedented. Novelty and prior art are
tracked separately in the research notes; publication claims should be checked
against the literature before submission.

## License

Add the repository license before publishing a stable release. The current
research snapshot intentionally does not claim a final licensing policy.
