"""Live Jev decisions over a small evolving decision-dense state machine."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jev_agent.context_residency import ContextBlock, ContextFault, ContextResidencyManager
from jev_agent.jev_client import TypeSafeJevChooser
from jev_agent.models import ChoiceOption
from jev_agent.virtual_option import VirtualOption, VirtualOptionManager


def option(option_id: str, description: str, page_id: str) -> VirtualOption:
    return VirtualOption(option_id, description, page_id=page_id, kind="action")


def action_options(manager: VirtualOptionManager) -> list[ChoiceOption]:
    options = [ChoiceOption(item.option_id, f"Current resident candidate: {item.description}", item) for item in manager.resident_options()]
    controls = {
        "COMMIT": "Commit a current validated resident candidate and execute the simulated operation.",
        "PAGE": "Materialize another page or context block because current coverage is insufficient.",
        "REFINE": "Construct a finer-grained OptionSpace from a current coarse candidate.",
        "CLARIFY": "Ask the user because current constraints or preferences are ambiguous.",
        "STOP": "Stop safely because the state is stale, unauthorized, or unrecoverable.",
    }
    options.extend(ChoiceOption(key, value) for key, value in controls.items())
    return options


def choose(chooser: TypeSafeJevChooser, state: str, options: list[ChoiceOption]) -> dict:
    started = perf_counter()
    result = chooser.choose(
        state=state,
        instructions="Choose exactly one resident candidate or runtime action. Do not invent an option.",
        options=options,
    )
    return {
        "choice": result.choice,
        "probabilities": result.probabilities,
        "confidence": result.confidence,
        "model": result.model,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "latency_ms": round(result.latency_ms or (perf_counter() - started) * 1000, 3),
    }


def run(chooser: TypeSafeJevChooser) -> dict:
    manager = VirtualOptionManager(max_resident=4, max_pages=12)
    manager.register_page("root", [option("WRONG", "status-only operation that does not satisfy the request", "root")])
    manager.register_page("recovered", [option("RECOVERED", "validated search for staging errors", "recovered")])
    manager.register_page("coarse", [option("COARSE", "coarse search operation with an underspecified query", "coarse")])
    manager.register_page("conflict", [option("FRIDAY", "depart Friday at 08:00", "conflict"), option("SATURDAY", "depart Saturday at 09:00", "conflict")])
    manager.register_page("stale", [option("STALE", "operation created under an older task revision", "stale")])
    manager.page_in("root")
    context = ContextResidencyManager(max_working=2, minimum_residency_steps=1)
    for i in range(4):
        context.register(ContextBlock(f"ctx{i}", f"context block {i} state", f"memory://{i}"))
    context.rebuild("context block 0 state")

    steps = [
        ("resident_commit", "COMMIT", "The current resident candidate is complete, current and authorized."),
        ("missing_page", "PAGE", "The resident candidate does not cover the explicit request; another option page is available."),
        ("commit_after_page", "COMMIT", "A current page has been materialized and contains the validated requested operation."),
        ("coarse_refine", "REFINE", "The resident candidate has the right tool but a coarse query field; refine it before execution."),
        ("commit_after_refine", "COMMIT", "The refined candidate is schema-valid and current; no coarse candidate remains resident."),
        ("ambiguous_clarify", "CLARIFY", "Friday and Saturday options conflict and the user has not specified a preference."),
        ("stale_stop", "STOP", "The only candidate is stale after a revision and no safe replacement is available."),
        ("context_page", "PAGE", "The required context block is cold; retrieve it before committing a decision."),
    ]
    rows = []
    simulated_effects = 0
    recoveries = 0
    for step_id, expected, state in steps:
        if step_id == "commit_after_page":
            manager.page_in("recovered")
        elif step_id == "coarse_refine":
            manager.evict_lru(1)
            manager.page_in("coarse")
        elif step_id == "commit_after_refine":
            manager.refine("COARSE", [option("EXACT", "validated search for staging errors", "refine:COARSE:r1")], page_id="refine:COARSE:r1")
        elif step_id == "ambiguous_clarify":
            manager.evict_lru(len(manager.resident_options()))
            manager.page_in("conflict")
        elif step_id == "stale_stop":
            manager.evict_lru(len(manager.resident_options()))
            manager.page_in("stale")
            manager.invalidate_page("stale")
        elif step_id == "context_page":
            try:
                context.require("ctx3")
            except ContextFault:
                pass
        decision = choose(chooser, state, action_options(manager))
        selected = decision["choice"]
        if step_id == "missing_page" and selected == "PAGE":
            manager.page_in("recovered")
            recoveries += 1
        if step_id == "context_page" and selected == "PAGE":
            context.rebuild("context block 3 state")
            recoveries += 1
        if step_id == "coarse_refine" and selected == "REFINE":
            manager.refine("COARSE", [option("EXACT", "validated search for staging errors", "refine:COARSE:r1")], page_id="refine:COARSE:r1")
            recoveries += 1
        if selected == "COMMIT" and step_id in {"resident_commit", "commit_after_page", "commit_after_refine"}:
            simulated_effects += 1
        rows.append({
            "step": step_id,
            "expected": expected,
            "selected": selected,
            "correct": selected == expected,
            "confidence": decision["confidence"],
            "model": decision["model"],
            "input_tokens": decision["input_tokens"],
            "output_tokens": decision["output_tokens"],
            "latency_ms": decision["latency_ms"],
            "resident_count": len(manager.resident_options()),
            "resident_bound": manager.max_resident,
            "context_working_count": len(context.resident()),
            "context_bound": context.max_working,
            "recovery": selected in {"PAGE", "REFINE"} and selected == expected,
        })
    return {
        "experiment": "live-jev-decision-dense-smoke",
        "steps": rows,
        "summary": {
            "steps": len(rows),
            "action_accuracy": sum(row["correct"] for row in rows) / len(rows),
            "recoveries": recoveries,
            "simulated_effects": simulated_effects,
            "resident_peak": max(row["resident_count"] for row in rows),
            "resident_bound": manager.max_resident,
            "context_peak": max(row["context_working_count"] for row in rows),
            "context_bound": context.max_working,
            "mean_latency_ms": sum(row["latency_ms"] for row in rows) / len(rows),
        },
        "notes": [
            "Live Jev controls an evolving local state machine; no external tool side effect is executed.",
            "This is a smoke sample, not the full 24-step oracle workload or a long-trajectory quality result.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not (os.environ.get("TYPESAFE_API_KEY") or os.environ.get("JEV_API_KEY")):
        raise SystemExit("Set TYPESAFE_API_KEY or JEV_API_KEY in the process environment")
    result = run(TypeSafeJevChooser(timeout_seconds=30.0))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
