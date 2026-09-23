# Optional Research Directions

Author: Anonymous · Version: v0.6-prototype · Date: 2026-09-23

The main [design](DESIGN.en.md) adopts I1 and I3. I2 is a separate note. I4, I5, and I6 remain optional directions. These are research hypotheses without experimental results or a completed novelty survey.

| ID | Direction | Main question | Status |
| --- | --- | --- | --- |
| I1 | Decision-impact hierarchical memory | Which memory can change the current action? | Main design |
| I2 | Candidate coverage diagnosis | Is the system uncertain, or is the correct option absent? | Independent note |
| I3 | Dependency-aware local replanning | Which state must be rebuilt after one condition changes? | Main design |
| I4 | Adaptive construction granularity | Should this step use a call, field, fragment, or token? | Optional |
| I5 | Unified generation, retrieval, and interaction budget | Which next action is most likely to advance the task? | Optional |
| I6 | Execution-feedback training for candidate generation | How can the helper produce fewer, more useful candidates? | Optional |

## I1: Decision-impact memory

Attach entities, fields, constraints, candidate branches, and evidence to each memory item. Retrieve items that can change feasibility, preference, or parameter provenance under the current budget. Compare decision-impact retrieval with semantic similarity, recency, and fixed hot/cold rules at equal context budgets. MemGPT and related systems establish hierarchical context management; the potential increment here is the dependency between memory retrieval and candidate construction.

## I2: Candidate coverage

The separate [candidate coverage note](CANDIDATE_COVERAGE.en.md) distinguishes ambiguity, missing facts, invalid proposals, and uncovered actions. Adding a fallback option is not the same as reliably detecting missing candidates.

## I3: Dependency-aware replanning

Record task, tool, source-entity, and observation versions on candidates, arguments, and memory. Propagate invalidation when a goal, schema, resource, or user constraint changes. Reuse unaffected evidence and cold branches, while rebuilding invalid or missing fields. Compare this with full regeneration and text-cache reuse. Dependency tracking does not roll back external side effects.

## I4: Adaptive granularity

Choose complete calls, fields, fragments, or tokens based on schema structure, candidate quality, latency, cost, and past success. Pydantic AI's Jev and LLM fallback is an important baseline. The candidate increment is local completion and explicit granularity scheduling; compatibility with existing tools alone is not a novelty claim.

## I5: Unified budget scheduling

Treat execution, proposal refresh, cold-memory retrieval, environment observation, clarification, and escalation to a stronger model as competing actions. Estimate expected task progress minus cost, latency, and interaction burden. Compare with fixed candidate counts and fixed fallback rules. Information-value clarification is a related direction; the proposed scope is joint scheduling across generation, memory, observation, and interaction.

## I6: Training the candidate generator from execution feedback

Train for coverage, executable constraints, useful diversity, and low redundancy rather than only a plausible single answer. Do not label unexecuted candidates as failures. Compare untuned and specialized helpers on unseen tools, task success, semantic diversity, and total budget. Execution feedback, distillation, and preference optimization are established areas; the contribution must be defined after a reliable dataset exists.

## Current trade-off

The shared main design is I1 plus I3, using dependency references for both memory retrieval and local invalidation. The coarse-proposal-first path with explicit Jev-controlled external-logits Top-k fallback is included in the main loop. I4, I5, and I6 remain optional until prototype bottlenecks and experiments justify them.
