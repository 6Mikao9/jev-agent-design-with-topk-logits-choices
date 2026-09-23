# Research positioning

This project presents a runtime for decision-native agents. The central abstraction is a replaceable Decision Model backend, `D(s,O) -> P(O)`, where Jev is the current prototype backend rather than the definition of the system.

The runtime manages two unbounded logical spaces through **dual virtualization**: a Virtual Option Space controls resident actions, while a Virtual Context Space controls resident context blocks. PAGE/EXPAND broadens candidate coverage; REFINE reduces granularity; ContextFault triggers second-stage context paging; REVISION/INVALIDATE preserve consistency.

Context is organized as Pinned, Working, and Cold tiers. Residency is a policy for semantic freshness and decision utility, not merely conventional RAG. The runtime does not rely on cross-request prefix/KV reuse, so it can mutate the working set aggressively; this does not claim that the Jev backend has no internal KV cache.

## DecisionModel backend boundary

`DecisionModel` accepts state and resident options/context and returns a probability distribution or typed decision. Backends may be Jev, a mock/oracle evaluator, or another typed decision service. This boundary keeps claims about option virtualization, context residency, refinement, fault recovery, and consistency independent of any single backend.

Context blocks carry `block_id`, `summary`, `raw_ref`, `revision`, `dependencies`, `last_access`, `access_count`, `utility`, `type`, `size`, and `pinned`. Aging is type-specific (pinned constraints do not age; task state ages slowly; observations and transient retrieval age faster). Utility aging updates from observed decision usefulness. Hysteresis, minimum residency, working-set history, and phase-aware replacement reduce thrashing.

The contribution boundary is the composition of Virtual Option Space, Virtual Context Space, decision-preserving refinement, and fault/recovery/consistency mechanisms. No individual component is claimed as independently novel. Current evidence is a mechanism baseline, a small Jev replay, and deterministic prototypes for option paging and context residency; broad system conclusions await the evaluation plan in `paper/main.tex`. The two managers are not yet a unified production scheduler.

## Planned control layer and novelty boundary

The next control layer is a **Runtime Governor**. It will consume the complete Decision Model distribution together with entropy, margin, resident-set size, risk, cost, fault/history, budget, and retrieval features, then choose among `COMMIT`, `PAGE`, `EXPAND`, `REFINE`, `RETRIEVE`, `FALLBACK`, and `CLARIFY`. The intended objective is expected utility or marginal value of information, rather than a hand-written probability threshold. This is a roadmap hypothesis; no learned-controller result is claimed yet.

Historical tool arguments will be indexed at field granularity by `(tool, field, state phase, semantic neighborhood)`. These priors only propose candidates for an `ArgumentOptionSpace`; Jev or another Decision Model still commits the choice. This is an engineering optimization with substantial neighboring work in case reuse, tool caching, and state-aware reuse, so it is not presented as a standalone novelty claim.

Paging is planned as adaptive set materialization: choose the smallest page subset whose estimated marginal value justifies its cost, instead of using a fixed probability cutoff. Offline counterfactual labeling is the first training route; contextual bandits or offline RL are later options. A learned Governor must be wrapped by a calibrated or conformal safety envelope that blocks high-risk `COMMIT` when the wrong-commit risk is not within the declared bound.

Candidate generators remain replaceable proposers. Diffusion is one possible parallel proposer alongside small AR models, retrieval, compilers, and historical priors; it is not the decision maker and is not a headline contribution. The novelty claim remains the runtime abstraction that virtualizes bounded decision and context interfaces and coordinates coverage, granularity, residency, and recovery under a finite resident set. All items in this section are plans or hypotheses until backed by the stated ablations and safety evaluations.
