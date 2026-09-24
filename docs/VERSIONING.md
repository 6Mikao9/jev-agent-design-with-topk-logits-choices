# Versioning and archive policy

The package is pre-1.0 research software. `pyproject.toml` carries the
installable package version; design documents may retain their historical
experiment version in their header. New public entry points are summarized in
the root README and the bilingual quick-start guides.

## Current line

- `v0.7-runtime-prototype`: the bounded `DecisionRuntime.step()` loop,
  shared decision validation, memory recency fix, bilingual quick starts, and
  the existing option/context/memory primitives.
- The runtime loop is synchronous and bounded. Async speculation, a learned
  governor, a multi-level page table, and long-horizon live Jev evidence remain
  research work.

## Historical material

Reports under `docs/reports/` are immutable evidence snapshots. Earlier
design-only documents remain readable for provenance; they are not current API
contracts. When a public release is cut, superseded entry points should move
under `docs/archive/<release>/` with a short migration note rather than being
silently deleted.

## Release checklist

Before a tagged release, record the commit, Python/Torch/Transformers versions,
test command and count, benchmark seeds/configuration, known failures, and
whether any result used Replay/Oracle or a live Jev backend. Never include API
keys, model weights, private traces or generated caches.
