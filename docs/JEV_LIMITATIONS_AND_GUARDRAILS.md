# Jev limitations and agent guardrails

The agent should treat Jev as a bounded choice component rather than a
replacement for state extraction, deterministic tools, or review. The points
below turn the known failure modes into explicit interfaces and metrics.

## Context rot

Long raw traces contain tool chatter and stale observations that are irrelevant
to the next decision. Before a Jev call, build a small state packet containing
only:

- the current user goal and unresolved subtask;
- current constraints and the evidence references that support them;
- dependency versions and conflict pairs;
- the candidate descriptions and the allowed recovery controls.

Keep the raw trace in storage for audit, but do not send it wholesale to Jev.
The existing `TaskState`, dependency-aware `MemoryBank`, and impact tags are
the first implementation of this boundary. A later `StateExtractor` should
make the packet schema explicit and measure packet length, dropped fields, and
decision accuracy as trace noise increases.

## No rationale

Jev probabilities describe its choice over the submitted options; they are not
an explanation and are not Qwen token probabilities. Every choice should retain
the option list, selected option, probability map, confidence, latency, and
evidence IDs. Include explicit controls such as `REVIEW`, `CLARIFY`, and
`STOP_UNRESOLVED` so an uncertain decision has a human or model review path.
For open-ended text, `END_DIALOGUE` is a separate control and must pass a
task-specific completion predicate. A separate reviewer can produce a rationale
after the decision without feeding that rationale back as untrusted state.

## Exact arithmetic and multi-hop causality

Route date arithmetic, cross-period accounting, unit conversions, and other
exact multi-hop computations to deterministic Python/Go tools. Jev may select
the tool and validate the returned evidence, but it should not be the arithmetic
engine. The tool result and input assumptions become evidence references in the
next state packet.

## Candidate dropout and the embedded helper

The recorded same-context experiment measures the failure mode directly. With
Qwen3.5-0.8B, Qwen3.8-27B's top-1 token was present in the small model's top-10
for all eight contexts; with the older Qwen3-0.6B control it was missing in
25% of contexts. The report also records coverage for the large model's top-10,
20, and 50 sets. These rates should become a guardrail before enabling a small
helper in production.

The later embedded-helper optimization can avoid a full softmax. For a causal
helper, retain the final hidden state (and KV/Mamba state when supported), run
only the LM head, and use `torch.topk` on raw logits. Softmax is unnecessary for
ranking; apply it only if a calibrated probability is explicitly required.
The helper still must return exact token IDs, decoded pieces, and a cache key
for the state. Measure cache hit rate, helper latency, candidate miss rate, and
memory use against the current full-forward implementation before replacing it.

## Conflict-first test cases

Keep contradiction cases in the held-out suite. The current travel case says
“leave Friday” and “only free Saturday”; a valid answer must quote both facts
and ask one clarifying question. Future cases should vary the location of the
contradiction inside a noisy trace and score conflict-pair precision, missed
conflicts, unnecessary clarification, and premature `END_DIALOGUE`.
