"""Offline ablation for context and Option Space budgets.

This benchmark measures packing capacity and request fan-out only.  It does
not call Jev and must not be read as a decision-quality result.  The synthetic
needle is intentionally placed near the end of an evidence region so that a
larger byte budget can expose a capacity effect without using a gold-aware
retriever.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jev_agent.context_budget import ContextBudget, ContextBudgetController, ContextSlice
from jev_agent.option_budget import OptionPageBudget


def synthetic_context() -> tuple[ContextSlice, ...]:
    slices: list[ContextSlice] = []
    slices.extend(
        ContextSlice("pinned", f"constraint-{index:02d}", "constraint " + "x" * 480, priority=2, required=True)
        for index in range(2)
    )
    slices.extend(
        ContextSlice("recent", f"recent-{index:02d}", "recent " + "r" * 360, priority=0.5)
        for index in range(10)
    )
    slices.extend(
        ContextSlice("working", f"working-{index:02d}", "working " + "w" * 520, priority=0.3)
        for index in range(16)
    )
    slices.extend(
        ContextSlice(
            "evidence",
            f"evidence-{index:02d}",
            "evidence " + ("needle=late-fact " if index == 15 else "") + "e" * 690,
            priority=0.1,
        )
        for index in range(18)
    )
    slices.extend(
        ContextSlice("options", f"option-{index:03d}", "option " + "o" * 110, priority=0.2)
        for index in range(50)
    )
    slices.extend(
        ContextSlice("trace", f"trace-{index:02d}", "trace " + "t" * 290, priority=0.1)
        for index in range(10)
    )
    return tuple(slices)


def run_context() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for name, budget in (("narrow_24k", ContextBudget()), ("wide_48k", ContextBudget.jev_wide())):
        packed = ContextBudgetController(budget).pack(synthetic_context())
        kept = {item.item_id for values in packed.sections.values() for item in values}
        rows.append(
            {
                "profile": name,
                "budget_bytes": budget.total,
                "packed_bytes": packed.total_bytes,
                "dropped_count": len(packed.dropped_ids),
                "dropped_ids": list(packed.dropped_ids),
                "late_needle_recovered": any(
                    item_id == "evidence-15" and "needle=late-fact" in text
                    for values in packed.sections.values()
                    for item_id, text in ((item.item_id, item.text) for item in values)
                ),
                "region_usage": packed.usage,
                "kept_count": len(kept),
            }
        )
    return rows


def run_options() -> list[dict[str, object]]:
    actions = tuple(f"tool:{index:03d}" for index in range(255))
    controls = ("PAGE", "REFINE", "CLARIFY", "REVIEW", "STOP", "NONE")
    rows: list[dict[str, object]] = []
    for target in (8, 16, 32, 64):
        budget = OptionPageBudget(decision_target=target)
        calls = budget.decision_calls(actions, controls=controls)
        target_call = next(index for index, call in enumerate(calls) if "tool:254" in call.candidates)
        rows.append(
            {
                "decision_target": target,
                "catalog_options": len(actions),
                "control_count": len(controls),
                "calls": len(calls),
                "candidate_counts": [len(call.candidates) for call in calls],
                "max_wire_count": max(call.wire_count for call in calls),
                "last_candidate_call": target_call,
                "all_within_wire_limit": all(call.wire_count <= 255 for call in calls),
            }
        )
    return rows


def main() -> None:
    result = {"context": run_context(), "options": run_options()}
    output = ROOT / "benchmarks" / "results" / "budget-ablation.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

