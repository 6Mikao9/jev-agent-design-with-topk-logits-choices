# Benchmark status

The scripts and fixtures are versioned. Large raw outputs under
`benchmarks/results/` are intentionally ignored from Git; the public summary
and fixed headline metrics are in
[`docs/IMPLEMENTATION_RESULTS.zh-CN.md`](../docs/IMPLEMENTATION_RESULTS.zh-CN.md).

## Synthetic control-flow check

`run_synthetic.py` is a deterministic mechanism check. Its scripted chooser
and helper can read each scenario's gold answer, so the results are oracle
upper bounds for the state machine, not quality estimates for Jev or a model.
The suite covers complete proposals, Top-k recovery, clarification, and stale
proposals after a task revision.

## Small-model candidate coverage

The first external task set is BFCL V4 `exec_simple`: 100 single-function
executable questions with reference calls. The Apache-2.0 data snapshot and
its source commit are recorded in [`data/bfcl-v4-exec-simple/`](data/bfcl-v4-exec-simple/SOURCE.md).
This category is kept separate from BFCL leaderboard categories.

Run a deterministic 30-task sample against a local causal model:

```sh
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
python -m benchmarks.run_bfcl_topk_coverage \
  --model /path/to/Qwen3-0.6B --device cuda --dtype bfloat16 --limit 30
```

For every reference call, the script asks the helper for its top 32 logits at
each reference-token prefix, then feeds the gold token back before checking
the next position. It reports token coverage at k=1, 8, and 32 and the share of
whole calls whose every reference token appeared in top-k. A perfect oracle is
assumed to select the correct token whenever it appears, so the whole-call
rate is an upper bound on what Jev can achieve with this helper and budget.
The script does not make Jev API calls, execute the BFCL tools, or produce an
official BFCL score. It measures whether the helper places the reference
continuation in its candidate set.

The sample is selected reproducibly with seed 2026. The full set is small
enough to run with `--limit 100`; use a separate held-out seed or dataset for
model selection and fine-tuning.

### Qwen3.5-0.8B 30-task sample

On 2026-09-24, the same seed-2026 sample was run with the local Qwen3.5-0.8B
checkpoint on one isolated RTX 5090. It took 55.449 seconds for 647 reference
tokens. Teacher-forced token coverage was 89.49% at k=1, 100% at k=8, and 100%
at k=32; the oracle reached all 30/30 complete calls at k=8 and k=32. This is
candidate availability only, not Jev choice accuracy or tool execution. The
raw result is kept outside Git under `benchmarks/results/`.

### Recorded full-set result

Qwen3-0.6B (596M parameters, BF16) was evaluated on all 100 examples using one
RTX 5090 in 41.9 seconds. Gold-token coverage was 87.52% at k=1, 98.97% at
k=8, and 99.83% at k=32. The oracle could reproduce all reference tokens for
78/100 calls at k=8 and 96/100 at k=32. This shows that most reference tokens
are available to a chooser, while four calls still contain at least one token
outside the helper's top 32. It does not measure whether Jev selects those
tokens correctly. The full output is
[`bfcl-v4-exec-simple-qwen3-0.6b-topk-100.json`](results/bfcl-v4-exec-simple-qwen3-0.6b-topk-100.json).

## Same-context next-token overlap

`compare_topk_overlap.py` compares Qwen3.5-0.8B and Qwen3.8-27B on eight
short English and Chinese contexts. Both checkpoints use the same 248,077-entry
tokenizer, so token-ID overlap is meaningful. The experiment asks for k = 10,
20, 50, 100, and 250 and also measures whether high-ranked large-model tokens
survive the small-model cut.

| Qwen3.5 small-model cut | mean overlap | large top-1 miss rate | large top-10 coverage |
| ---: | ---: | ---: | ---: |
| 10 | 6.75 / 10 | 0% | 67.5% |
| 20 | 12.38 / 20 | 0% | 83.75% |
| 50 | 32.5 / 50 | 0% | 96.25% |
| 100 | 61.75 / 100 | 0% | 97.5% |
| 250 | 149 / 250 | 0% | 98.75% |

The old Qwen3-0.6B checkpoint was also measured for the directional question.
Its tokenizer differs, so only decoded token-piece overlap is reported: the
Qwen3.8 top-1 token is absent from the 0.6B top-10 in 25% of these eight
contexts, absent from top-20 in 25%, and absent from top-100 in 12.5%.
Records: [`qwen35-vs-qwen38-topk-overlap.json`](results/qwen35-vs-qwen38-topk-overlap.json)
and [`qwen06-vs-qwen38-topk-overlap.json`](results/qwen06-vs-qwen38-topk-overlap.json).

## Dialogue and conflict-control experiment

`run_jev_guided_dialogue.py` feeds Qwen3.8-27B's top-20 candidates to a chooser
at every step and includes a separate `END_DIALOGUE` option. The option is
accepted only after a case-specific completion predicate; an early selection is
recorded as `premature_end`. The default run uses a deterministic top-1 proxy
so it is reproducible and does not spend a live Jev key. The same trace schema
can call `TypeSafeJevChooser` when a caller explicitly provides a key at runtime.

The four-case run completed all four answers, including a conflict case that
quoted the Friday/Saturday contradiction and asked one clarifying question.
Luna's blind review is stored in
[`luna-judge-result.json`](results/luna-judge-result.json); after the stricter
completion predicates, all four baseline/proxy pairs tied at 5/5 on correctness,
relevance, completeness, clarity, and termination.

### Helper speed breakdown

The helper was then switched to Qwen3.5-0.8B with top-100 candidates. On the
same four cases, the mean candidate-generation time was 6,337.62 ms and the
mean end-to-end rate was 10.93 tokens/s. The earlier Qwen3.8-27B top-20 run
measured 4,782.54 ms and 16.96 tokens/s. The 0.8B run currently recomputes the
full prefix with Transformers, while the 27B run uses SGLang's cached serving
path; this is an implementation comparison, not a claim that the smaller
model is intrinsically slower. The local chooser itself took 0.12 ms on the
0.8B run and 0.19 ms on the 27B run. The per-case table is in
[`jev-dialogue-speed-comparison.md`](results/jev-dialogue-speed-comparison.md).

## Live Jev check

`live_smoke.py` records one live Jev Choice call. On 2026-09-23 it selected the
correct `severity=error` proposal with confidence 0.99 from 399 input tokens.
This checks endpoint access and the Choice response format only. It does not
exercise Top-k fallback and is not an accuracy estimate. The runner reads the
credential from the process environment; credentials are never stored in the
repository or results.

## Next evaluations

- [BFCL V4](https://github.com/EnlightenedAI/BFCL): after token coverage is
  measured, integrate the official executable runner and add tool execution
  success, schema correctness, candidate coverage, fallback repair rate,
  incorrect execution count, Jev/helper calls, cost, and P50/P95 latency.
- [tau2-bench and tau3 guidance](https://github.com/sierra-research/tau2-bench):
  multi-turn stateful tasks for user corrections and changing environments.
- [API-Bank](https://github.com/AlibabaResearch/DAMO-ConvAI/tree/main/api-bank):
  API discovery and multi-step API use as a complementary tool-selection set.

For all comparisons, use the same task split and call/token/time budgets for
proposal-only, unconditional Top-k, and Jev-triggered fallback. Score with
validated arguments and deterministic execution results rather than Jev's
confidence alone.

### Needle memory baseline

Run `python benchmarks/benchmark_needle_memory.py --pages 100 --needle-position middle --noise-words 40 --seed 7 --limit 16 --output /tmp/needle.json`. This is a deterministic lexical coarse-prefilter baseline using PagedMemoryIndex; it does not measure two-stage Jev selection. Vary page count, needle position, noise length and limit, then compare recall@M, candidate count, latency and budgets.

`benchmark_needle_matrix.py` runs a small matrix over 100/1,000/10,000 pages,
40/160 noise words and first/middle/last needle positions. On 2026-09-24,
`limit=16` recalled the injected needle in all 18/18 cases. Candidate count was
one in every case; median selection time was about 0.15 ms, 1.46 ms and 15.0 ms
for 100, 1,000 and 10,000 pages respectively. This is a favorable exact-token
lexical control, not evidence for semantic long-context retrieval or Jev quality.

### Two-stage Jev memory replay

Run `python benchmarks/benchmark_memory_jev.py --output /tmp/memory-jev.json` to replay the page-summary ranking and `TOP_2/4/8` count choice without a network key. This only checks selector wiring and budget/version handling. To call the real Choice endpoint, set `TYPESAFE_API_KEY` or `JEV_API_KEY` in the process environment and add `--live-jev`; credentials are never accepted as command-line arguments or written to the output.

### Virtual Option Space scaling mechanism baseline

Run `python benchmarks/benchmark_virtual_option_scaling.py --output /tmp/virtual-option-scaling.json` for logical spaces of 10/100/1K/10K/100K options and resident bounds `K=8/16/32`. The benchmark measures deterministic page-in, `OptionFault`, LRU eviction, stable-ID resolution and the resident bound. It makes no Jev calls and is not a scaling result for task quality; follow-up experiments must add candidate deletion, Jev decisions, refinement and recovery-cost measurements.

### Decision Model capability and page recovery

Run `python benchmarks/benchmark_backend_capability.py --output /tmp/backend-capability.json` to compare a fixed resident set with synthetic `PAGE/EXPAND` recovery at backend capabilities 0.6/0.7/0.8/0.9/1.0. Logical option sizes and resident bounds match the paper plan. This is an oracle-style mechanism baseline: replace the synthetic backend with real Jev or another DecisionModel only after fixing the task split and measuring `RecoveryRate` on initially missing targets.

Read the fields separately: `coverage_rate` says whether the target became resident,
`resident_decision_success_rate` says how often the synthetic backend selected it after
it was visible, and `recovery_rate` says how many initial `OptionFault`s were repaired by
the strategy. `success_rate` is their end-to-end product for this benchmark. Therefore a
0% fixed-resident result at a large logical size is an intentional coverage lower bound,
not a claim that Jev or the runtime has 0% task accuracy. `initial_page_ins` is setup
cost; `recovery_page_ins` is the additional paging work.
