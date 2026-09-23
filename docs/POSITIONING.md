# Research positioning

This project presents a runtime for decision-native agents. The central abstraction is a replaceable Decision Model backend, `D(s,O) -> P(O)`, where Jev is the current prototype backend rather than the definition of the system.

The runtime manages two unbounded logical spaces through **dual virtualization**: a Virtual Option Space controls resident actions, while a Virtual Context Space controls resident context blocks. PAGE/EXPAND broadens candidate coverage; REFINE reduces granularity; ContextFault triggers second-stage context paging; REVISION/INVALIDATE preserve consistency.

Context is organized as Pinned, Working, and Cold tiers. Residency is a policy for semantic freshness and decision utility, not merely conventional RAG. The runtime does not rely on cross-request prefix/KV reuse, so it can mutate the working set aggressively; this does not claim that the Jev backend has no internal KV cache.

## DecisionModel backend boundary

`DecisionModel` accepts state and resident options/context and returns a probability distribution or typed decision. Backends may be Jev, a mock/oracle evaluator, or another typed decision service. This boundary keeps claims about option virtualization, context residency, refinement, fault recovery, and consistency independent of any single backend.

Context blocks carry `block_id`, `summary`, `raw_ref`, `revision`, `dependencies`, `last_access`, `access_count`, `utility`, `type`, `size`, and `pinned`. Aging is type-specific (pinned constraints do not age; task state ages slowly; observations and transient retrieval age faster). Utility aging updates from observed decision usefulness. Hysteresis, minimum residency, working-set history, and phase-aware replacement reduce thrashing.

The contribution boundary is the composition of Virtual Option Space, Virtual Context Space, decision-preserving refinement, and fault/recovery/consistency mechanisms. No individual component is claimed as independently novel. Current evidence is a mechanism baseline, a small Jev replay, and deterministic prototypes for option paging and context residency; broad system conclusions await the evaluation plan in `paper/main.tex`. The two managers are not yet a unified production scheduler.
