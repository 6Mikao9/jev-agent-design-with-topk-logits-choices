# Qwen3.5 / Qwen3.8 / Jev experiment report

The run used eight fixed raw contexts and the same next-token query for both
models. Qwen3.5-0.8B and Qwen3.8-27B have the same 248,077-token vocabulary,
so their token-ID intersections are directly comparable. Qwen3-0.6B uses a
different vocabulary; its comparison uses decoded token pieces instead.

## Candidate overlap

| Qwen3.5 cut | mean intersection | Qwen3.8 top-1 missing from cut | Qwen3.8 top-10 coverage |
| ---: | ---: | ---: | ---: |
| 10 | 6.75 | 0% | 67.5% |
| 20 | 12.38 | 0% | 83.75% |
| 50 | 32.5 | 0% | 96.25% |
| 100 | 61.75 | 0% | 97.5% |
| 250 | 149 | 0% | 98.75% |

For the older Qwen3-0.6B directional control, Qwen3.8's top-1 piece is absent
from the small model's top-10 in 25% of contexts, absent from top-20 in 25%,
and absent from top-100 in 12.5%. A top-10 large-model set has mean coverage
of 53.75% in the 0.6B top-10 and 88.75% in the 0.6B top-100.

These are candidate-set statistics, not probabilities that Jev will choose the
right token. They also use a small hand-authored set, so they should be
expanded with held-out prompts before model selection.

## Dialogue control

The large model supplied top-20 candidates at every step. Each step also
offered `END_DIALOGUE`; it was accepted only after a case-specific completion
predicate. Four cases completed: arithmetic, TCP/UDP explanation, a four-step
backup checklist, and a contradictory Friday/Saturday travel request. The
conflict answer quoted both facts and asked one clarifying question.

The recorded default chooser is `local_top1_proxy`, which always takes the
large model's highest-ranked candidate and exercises `END_DIALOGUE` once the
predicate passes. This isolates the vocabulary/control-flow path without
spending a live Jev key. `TypeSafeJevChooser` remains available for a caller
that supplies a key at runtime; its choice probabilities must not be confused
with Qwen's token probabilities.

Luna's blind review of the final four paired answers gave every baseline and
proxy answer 5/5 for correctness, relevance, completeness, clarity, and
termination; all four pairs tied. The raw review is in
[`luna-judge-result.json`](results/luna-judge-result.json).

## Speed split

With Qwen3.5-0.8B providing top-100 candidates, mean helper candidate
generation took 6,337.62 ms across the four cases; the local chooser took
0.12 ms and end-to-end throughput was 10.93 tokens/s. The earlier Qwen3.8-27B
top-20 run measured 4,782.54 ms, 0.19 ms, and 16.96 tokens/s respectively.
The comparison is implementation-specific: the 0.8B path currently does a
full-prefix Transformers forward at every step, while the 27B path uses
SGLang's cached serving endpoint. KV/cache and logits-head optimizations remain
the next speed work.
