# I2: Candidate Coverage Diagnosis and Recovery

Author: Anonymous · Version: v0.6-prototype · Date: 2026-09-23

This note treats candidate coverage as an independent research question for the main [Jev-native agent design](DESIGN.en.md). It has no experimental results yet.

## Why this matters

Jev receives a supplied candidate set. If the correct action is absent, it may still assign a concentrated probability to the best available option. The system therefore needs recovery controls instead of treating the highest probability as proof that the set is complete.

`FALLBACK_TOPK` can express that existing proposals are unsuitable. It does not by itself make the rejection diagnosis reliable.

## Failure causes and recovery

| Situation | Observable signals | Possible recovery |
| --- | --- | --- |
| Ambiguous candidates | Several options satisfy known conditions | Ask for a preference or add a discriminating observation |
| Explicit constraint violation | Schema, range, or prerequisite check fails | Repair, re-propose, or remove the candidate |
| Missing fact | Entity, field meaning, or environment state is unknown | Look up the environment or ask the user |
| Correct action may be uncovered | Homogeneous proposals, incompatible constraints, repeated failures | Expand sources, re-propose, or use Top-k construction |
| State changed | User correction, tool version, or resource update | Invalidate dependencies and replan through I3 |

These causes can coexist. Confidence comes from the current distribution and is not an independent completeness proof. Candidate order, duplication, controlled additions and removals, source diversity, and validation history are useful diagnostic signals, but none is sufficient alone.

## Relation to Top-k fallback

```text
FALLBACK_TOPK    Existing drafts do not fit; construct this field step by step
REPROPOSE        Refresh complete-field or fragment candidates
LOOKUP           Retrieve missing environment information
CLARIFY          Ask the user for a missing requirement
STOP_UNRESOLVED  Stop and report the unresolved portion
```

`FALLBACK_TOPK` requires a logits-capable helper and remaining budget. At each round, the helper's logits are reduced to a dynamic token table containing the highest-probability `k` tokens; Jev chooses the next token from that table, the token is appended to the prefix, and the helper produces the next table. A missing resource ID or undecided user requirement cannot be recovered by continuation; observation or clarification comes first.

## Evaluation

Construct tasks where the correct item is deliberately removed, near-duplicates are added, constraints conflict, facts are missing, or state changes mid-run. Compare highest-probability selection, a confidence threshold, explicit rejection plus `FALLBACK_TOPK`, and a diagnostic policy combining coverage risk, constraints, and information gaps. Report incorrect high-confidence execution, coverage, false fallback triggers, missed fallback cases, post-recovery success, and total cost.

This note does not claim that a fallback option solves candidate coverage. Correct candidate generation, Jev's interpretation of recovery controls, and cross-tool calibration remain open questions.
