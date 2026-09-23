"""Live Jev retrieval -> recovery -> simulated execution control loop."""
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

from jev_agent.jev_client import TypeSafeJevChooser
from jev_agent.memory_selection import TwoStageMemorySelector
from jev_agent.models import ChoiceOption
from jev_agent.paged_memory import MemoryPage, PagedMemoryIndex
from jev_agent.virtual_option import VirtualOption, VirtualOptionManager


def _option(option_id: str, description: str, page_id: str) -> VirtualOption:
    return VirtualOption(option_id, description, {"option_id": option_id}, page_id)


def _action_options(resident: tuple[VirtualOption, ...], *, controls: tuple[str, ...]) -> list[ChoiceOption]:
    options = [ChoiceOption(item.option_id, f"Resident candidate: {item.description}", item) for item in resident]
    descriptions = {
        "COMMIT": "Commit one current validated resident candidate and execute the simulated tool call.",
        "PAGE": "Materialize another page because the current resident candidates do not cover the request.",
        "REFINE": "Refine a current coarse resident candidate into more detailed valid candidates.",
        "CLARIFY": "Ask the user because the available evidence or constraints are ambiguous.",
        "STOP": "Stop safely because the current state is stale, unauthorized, or otherwise unsafe.",
    }
    options.extend(ChoiceOption(key, descriptions[key]) for key in controls)
    return options


def _choose(chooser: TypeSafeJevChooser, *, state: str, options: list[ChoiceOption]) -> dict:
    started = perf_counter()
    result = chooser.choose(
        state=state,
        instructions="Choose exactly one candidate or runtime control. Do not invent an option.",
        options=options,
    )
    return {
        "choice": result.choice,
        "probabilities": result.probabilities,
        "confidence": result.confidence,
        "latency_ms": round(result.latency_ms or (perf_counter() - started) * 1000, 3),
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
    }


def _run_case(chooser: TypeSafeJevChooser, name: str) -> dict:
    manager = VirtualOptionManager(max_resident=4, max_pages=8)
    actions: list[dict] = []
    execution_count = 0

    if name == "resident_commit":
        page_id = "resident-search"
        manager.register_page(page_id, [_option("SEARCH_VALID", "search staging errors for the last 30 minutes", page_id)])
        manager.page_in(page_id)
        expected_terminal = "COMMIT"
        state = "The current resident search candidate is complete, current, authorized, and satisfies the request."
        decision = _choose(chooser, state=state, options=_action_options(manager.resident_options(), controls=("COMMIT", "PAGE", "REFINE", "CLARIFY", "STOP")))
        actions.append(decision)
        if decision["choice"] == "COMMIT":
            execution_count += 1
        return {"case": name, "expected_terminal": expected_terminal, "actions": actions, "final_status": "executed" if execution_count else decision["choice"], "execution_count": execution_count}

    if name == "missing_page":
        resident_id = "resident-wrong"
        manager.register_page(resident_id, [_option("STATUS_ONLY", "read service status without the requested error query", resident_id)])
        manager.page_in(resident_id)
        index = PagedMemoryIndex(max_pages=4)
        index.upsert(MemoryPage("deploy-page", "staging error query operation", "The page contains the current error-search candidate."))
        index.upsert(MemoryPage("noise-page", "unrelated backup note", "No search action."))
        decision = _choose(chooser, state="The current resident option set does not cover the explicit staging error-query request; the page directory may contain a suitable option.", options=_action_options(manager.resident_options(), controls=("PAGE", "REFINE", "CLARIFY", "STOP")))
        actions.append(decision)
        localization = {"candidate_page_ids": [], "selected_page_ids": [], "target_page_in_candidates": False}
        if decision["choice"] == "PAGE":
            selector = TwoStageMemorySelector(chooser, max_candidates=4, count_options=(1, 2, 4), max_pages=4)
            memory = selector.retrieve(index, context="Find the staging error query operation.")
            localization = {"candidate_page_ids": list(memory.candidate_ids), "selected_page_ids": list(memory.selected_ids), "target_page_in_candidates": "deploy-page" in memory.candidate_ids}
            if memory.status == "read_complete":
                options = [_option("SEARCH_ERROR", "search staging errors for the last 30 minutes", "deploy-page")]
                manager.register_page("deploy-page", options)
                manager.page_in("deploy-page")
                follow = _choose(chooser, state="A current page has been materialized and contains a validated error-search candidate.", options=_action_options(manager.resident_options(), controls=("COMMIT", "REFINE", "CLARIFY", "STOP")))
                actions.append(follow)
                if follow["choice"] == "COMMIT":
                    execution_count += 1
            return {"case": name, "expected_terminal": "COMMIT", "actions": actions, "memory_status": memory.status, "localization": localization, "final_status": "executed" if execution_count else actions[-1]["choice"], "execution_count": execution_count}
        return {"case": name, "expected_terminal": "PAGE", "actions": actions, "memory_status": "not_entered", "localization": localization, "final_status": decision["choice"], "execution_count": execution_count}

    if name == "coarse_refine":
        page_id = "coarse-search"
        manager.register_page(page_id, [_option("SEARCH_COARSE", "search staging logs with an underspecified query field", page_id)])
        manager.page_in(page_id)
        first = _choose(chooser, state="A resident search candidate has the correct tool but a coarse query field; refine locally before execution.", options=_action_options(manager.resident_options(), controls=("REFINE", "PAGE", "CLARIFY", "STOP")))
        actions.append(first)
        if first["choice"] == "REFINE":
            manager.refine("SEARCH_COARSE", [_option("SEARCH_EXACT", "search staging errors for the last 30 minutes", "refine:SEARCH_COARSE:r1")], page_id="refine:SEARCH_COARSE:r1")
            second = _choose(chooser, state="The coarse search candidate was refined into a current schema-valid query candidate. No coarse candidate remains resident.", options=_action_options(manager.resident_options(), controls=("COMMIT", "CLARIFY", "STOP")))
            actions.append(second)
            if second["choice"] == "COMMIT":
                execution_count += 1
        return {"case": name, "expected_terminal": "COMMIT", "actions": actions, "final_status": "executed" if execution_count else actions[-1]["choice"], "execution_count": execution_count}

    if name == "ambiguous_clarify":
        page_id = "conflict"
        manager.register_page(page_id, [_option("FRIDAY", "depart Friday at 08:00", page_id), _option("SATURDAY", "depart Saturday at 09:00", page_id)])
        manager.page_in(page_id)
        decision = _choose(chooser, state="Two current resident options conflict on the departure day and the user has not stated a preference.", options=_action_options(manager.resident_options(), controls=("COMMIT", "PAGE", "REFINE", "CLARIFY", "STOP")))
        actions.append(decision)
        return {"case": name, "expected_terminal": "CLARIFY", "actions": actions, "final_status": decision["choice"], "execution_count": execution_count}

    raise ValueError(name)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not (os.environ.get("TYPESAFE_API_KEY") or os.environ.get("JEV_API_KEY")):
        raise SystemExit("Set TYPESAFE_API_KEY or JEV_API_KEY in the process environment")
    chooser = TypeSafeJevChooser(timeout_seconds=30.0)
    cases = []
    for name in ("resident_commit", "missing_page", "coarse_refine", "ambiguous_clarify"):
        try:
            cases.append(_run_case(chooser, name))
        except Exception as exc:
            cases.append({"case": name, "error": type(exc).__name__ + ": " + str(exc)})
    completed = [case for case in cases if "error" not in case]
    terminal_correct = [case for case in completed if case.get("final_status") == case.get("expected_terminal") or (case.get("expected_terminal") == "COMMIT" and case.get("final_status") == "executed")]
    output = {
        "experiment": "live-jev-retrieval-recovery-closed-loop",
        "cases": cases,
        "summary": {"submitted": len(cases), "completed": len(completed), "errors": len(cases) - len(completed), "terminal_contract_rate": len(terminal_correct) / len(completed) if completed else None, "executed_side_effects": sum(case.get("execution_count", 0) for case in completed)},
        "notes": [
            "Tool execution is simulated and has no external side effect.",
            "missing_page uses the real PagedMemoryIndex and TwoStageMemorySelector after Jev selects PAGE; no target page is directly supplied to the selector.",
            "This is a small closed-loop smoke benchmark, not a long-trajectory workload.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
