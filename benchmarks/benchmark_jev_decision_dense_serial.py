"""Live 22-step A/B/C decision-dense workload.

The workload composes context paging, virtual tool-page selection, in-page tool
selection, refinement, stale STOP and clarification. All tool effects are
simulated. Target IDs are evaluation metadata only and are never sent to Jev.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jev_agent.context_residency import ContextBlock, ContextFault, ContextResidencyManager
from jev_agent.jev_client import TypeSafeJevChooser
from jev_agent.models import ChoiceBackend, ChoiceOption, ChoiceResult
from jev_agent.virtual_option import OptionFault, VirtualOption, VirtualOptionManager

PAGES = {
    "files": {"summary": "workspace file operations", "tools": ["read_file", "write_file", "list_files"]},
    "calendar": {"summary": "calendar event scheduling", "tools": ["create_event", "list_events", "delete_event"]},
    "database": {"summary": "database row queries and updates", "tools": ["query_rows", "update_row", "delete_row"]},
    "browser": {"summary": "web browsing and page retrieval", "tools": ["open_url", "find_text", "download_file"]},
    "memory": {"summary": "historical context and memory retrieval", "tools": ["retrieve_recent", "retrieve_archive", "summarize_memory"]},
}
CONTEXTS = {
    "ctx_workspace": "current workspace paths and file permission constraints",
    "ctx_calendar": "current meeting timezone and scheduling constraints",
    "ctx_records": "current database schema and record safety constraints",
    "ctx_browser": "current browser session and allowed domains",
    "ctx_history": "recent task history and prior decisions",
}


@dataclass(frozen=True)
class Event:
    name: str
    kind: str
    query: str = ""
    page: str | None = None
    tool: str | None = None
    context: str | None = None
    expected: str = ""


EVENTS = (
    Event("context_workspace", "context_page", query=CONTEXTS["ctx_workspace"], context="ctx_workspace", expected="PAGE_CONTEXT:ctx_workspace"),
    Event("page_files", "page", query="read the source file", page="files", expected="PAGE:files"),
    Event("tool_read_file", "tool", query="read the source file", page="files", tool="read_file", expected="files:read_file"),
    Event("commit_file_read", "commit", query="the validated file read candidate is complete and authorized", expected="COMMIT"),
    Event("context_calendar", "context_page", query=CONTEXTS["ctx_calendar"], context="ctx_calendar", expected="PAGE_CONTEXT:ctx_calendar"),
    Event("page_calendar", "page", query="schedule a review meeting", page="calendar", expected="PAGE:calendar"),
    Event("tool_create_event", "tool", query="schedule a review meeting", page="calendar", tool="create_event", expected="calendar:create_event"),
    Event("refine_event", "refine", query="the event tool is right but the time and timezone fields are underspecified", page="calendar", expected="REFINE"),
    Event("commit_event", "commit", query="the refined calendar event candidate is schema-valid and authorized", expected="COMMIT"),
    Event("context_records", "context_page", query=CONTEXTS["ctx_records"], context="ctx_records", expected="PAGE_CONTEXT:ctx_records"),
    Event("page_database", "page", query="query account records", page="database", expected="PAGE:database"),
    Event("tool_query_rows", "tool", query="query account records", page="database", tool="query_rows", expected="database:query_rows"),
    Event("commit_query", "commit", query="the read-only database query candidate is complete and safe", expected="COMMIT"),
    Event("ambiguous_request", "clarify", query="the request conflicts between reading a file and querying a database", expected="CLARIFY"),
    Event("context_browser", "context_page", query=CONTEXTS["ctx_browser"], context="ctx_browser", expected="PAGE_CONTEXT:ctx_browser"),
    Event("page_browser", "page", query="open the documentation URL", page="browser", expected="PAGE:browser"),
    Event("tool_open_url", "tool", query="open the documentation URL", page="browser", tool="open_url", expected="browser:open_url"),
    Event("stale_stop", "stale_stop", query="the current browser candidate is stale after a revision and no safe replacement is resident", expected="STOP"),
    Event("context_history", "context_page", query=CONTEXTS["ctx_history"], context="ctx_history", expected="PAGE_CONTEXT:ctx_history"),
    Event("page_memory", "page", query="retrieve the recent task decision", page="memory", expected="PAGE:memory"),
    Event("tool_retrieve_recent", "tool", query="retrieve the recent task decision", page="memory", tool="retrieve_recent", expected="memory:retrieve_recent"),
    Event("commit_memory", "commit", query="the retrieved task decision is current and read-only", expected="COMMIT"),
)


class ContractChooser(ChoiceBackend):
    """Offline wiring backend; it consumes the expected label only for control replay."""

    def choose(self, *, state: str, instructions: str, options: list[ChoiceOption]) -> ChoiceResult:
        expected = state.rsplit("\nEVAL_EXPECTED=", 1)[-1]
        if expected not in {option.option_id for option in options}:
            expected = options[0].option_id
        return ChoiceResult(expected, {option.option_id: (1.0 if option.option_id == expected else 0.0) for option in options}, 1.0, "contract", latency_ms=0.01)


_STOPWORDS = {
    "the", "a", "an", "and", "or", "to", "of", "for", "with", "is", "are",
    "current", "request", "candidate", "operation", "safe", "read", "recent",
}


def _query_terms(text: str) -> set[str]:
    return {
        token
        for token in "".join(ch.lower() if ch.isalnum() else " " for ch in text).split()
        if token not in _STOPWORDS and len(token) > 2
    }


def ranked_pages(query: str) -> list[tuple[str, int]]:
    """Return a small lexical directory ranking without using evaluation metadata."""
    query_terms = _query_terms(query)
    ranked: list[tuple[str, int, int]] = []
    for position, (page_id, spec) in enumerate(PAGES.items()):
        searchable = _query_terms(" ".join([page_id, spec["summary"], *spec["tools"]]))
        score = len(query_terms & searchable)
        ranked.append((page_id, score, position))
    ranked.sort(key=lambda item: (-item[1], item[2]))
    return [(page_id, score) for page_id, score, _ in ranked]


def page_choices(query: str = "") -> list[ChoiceOption]:
    ranked = ranked_pages(query)
    return [ChoiceOption(f"PAGE:{page_id}", f"Directory candidate page {page_id}: {PAGES[page_id]['summary']}") for page_id, _ in ranked] + [
        ChoiceOption("CLARIFY", "Ask the user because the request is ambiguous."),
        ChoiceOption("STOP", "Stop safely because no current authorized page can satisfy the request."),
    ]


def context_choices() -> list[ChoiceOption]:
    return [ChoiceOption(f"PAGE_CONTEXT:{block_id}", f"Materialize context block {block_id}: {summary}") for block_id, summary in CONTEXTS.items()] + [
        ChoiceOption("CLARIFY", "Ask the user because context requirements are ambiguous."),
        ChoiceOption("STOP", "Stop safely because required context is unavailable or unsafe."),
    ]


def tool_choices(manager: VirtualOptionManager) -> list[ChoiceOption]:
    options = [ChoiceOption(item.option_id, f"Use resident tool candidate: {item.description}") for item in manager.resident_options()]
    options.extend([
        ChoiceOption("REFINE", "Refine the current coarse tool candidate into valid parameterized options."),
        ChoiceOption("PAGE", "Materialize another tool page because current coverage is insufficient."),
        ChoiceOption("CLARIFY", "Ask the user because the tool request is ambiguous."),
        ChoiceOption("STOP", "Stop safely because the current tool candidates are stale or unsafe."),
    ])
    return options


def control_choices(controls: tuple[str, ...]) -> list[ChoiceOption]:
    descriptions = {
        "COMMIT": "Commit the current validated candidate and execute the simulated operation.",
        "REFINE": "Refine the current coarse candidate into valid detailed candidates.",
        "PAGE": "Materialize another option page because current coverage is insufficient.",
        "CLARIFY": "Ask the user because constraints are ambiguous.",
        "STOP": "Stop safely because state is stale or unsafe.",
    }
    return [ChoiceOption(control, descriptions[control]) for control in controls]


def action_choices(manager: VirtualOptionManager, controls: tuple[str, ...]) -> list[ChoiceOption]:
    """Candidate selection is kept separate from control/action selection."""
    return [ChoiceOption(item.option_id, f"Resident candidate: {item.description}") for item in manager.resident_options()] + control_choices(controls)


def choose(chooser: ChoiceBackend, *, state: str, options: list[ChoiceOption], expected: str | None = None) -> dict:
    started = perf_counter()
    # The expected suffix is present only for ContractChooser and is removed from
    # live prompts; it prevents target leakage into the live Jev path.
    live_state = state
    if isinstance(chooser, ContractChooser) and expected is not None:
        live_state = f"{state}\nEVAL_EXPECTED={expected}"
    result = chooser.choose(state=live_state, instructions="Choose exactly one listed candidate or runtime control. Do not invent an option.", options=options)
    return {
        "selected": result.choice,
        "correct": result.choice == expected if expected is not None else None,
        "latency_ms": round(result.latency_ms or (perf_counter() - started) * 1000, 3),
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "model": result.model,
    }


def run(chooser: ChoiceBackend) -> dict:
    manager = VirtualOptionManager(max_resident=4, max_pages=16)
    for page_id, spec in PAGES.items():
        manager.register_page(page_id, [VirtualOption(f"{page_id}:{tool}", f"{tool.replace('_', ' ')} operation", page_id=page_id, kind="action") for tool in spec["tools"]])
    context = ContextResidencyManager(max_working=2, minimum_residency_steps=1)
    for block_id, summary in CONTEXTS.items():
        context.register(ContextBlock(block_id, summary, f"memory://{block_id}", kind="task_state" if block_id == "ctx_workspace" else "observation"))
    rows = []
    simulated_effects = 0
    validated_candidate: str | None = None
    for event in EVENTS:
        fault = None
        recovery = None
        recovery_selected = None
        effect_performed = False
        if event.kind == "context_page":
            try:
                context.require(event.context or "")
            except ContextFault:
                fault = "ContextFault"
            decision = choose(chooser, state=f"The required context is cold. Query: {event.query}", options=context_choices(), expected=event.expected)
            if decision["selected"].startswith("PAGE_CONTEXT:"):
                selected_context = decision["selected"].split(":", 1)[1]
                if selected_context in CONTEXTS:
                    context.rebuild(CONTEXTS[selected_context])
                    recovery = "context_rebuild"
        elif event.kind == "page":
            ranked = ranked_pages(event.query)
            directory_hint = ", ".join(f"{page_id} (rank {score})" for page_id, score in ranked[:3])
            decision = choose(chooser, state=f"User request: {event.query}\nThe physical tool catalog is partitioned into virtual pages. Choose a page from the summaries. The lexical directory ranks these candidates first: {directory_hint}.", options=page_choices(event.query), expected=event.expected)
            if decision["selected"].startswith("PAGE:"):
                selected_page = decision["selected"].split(":", 1)[1]
                if selected_page in PAGES:
                    manager.page_in(selected_page)
                    recovery = "page_in"
        elif event.kind == "tool":
            # A tool decision is not allowed to run against an unrelated or empty
            # resident set. Use the runtime's lexical directory to recover the
            # likely page, then expose the in-page candidates separately.
            ranked = ranked_pages(event.query)
            likely_page = ranked[0][0]
            has_likely_page = any(item.option_id.startswith(f"{likely_page}:") for item in manager.resident_options())
            recovery_latency = 0.0
            recovery_input_tokens = 0
            recovery_output_tokens = 0
            if not has_likely_page:
                fault = "OptionFault"
                directory_hint = ", ".join(f"{page_id} (rank {score})" for page_id, score in ranked[:3])
                page_recovery = choose(
                    chooser,
                    state=f"The requested tool is not resident. Recover by selecting a page from the ranked directory. User request: {event.query}. Candidates: {directory_hint}.",
                    options=page_choices(event.query),
                    expected=f"PAGE:{likely_page}",
                )
                recovery_selected = page_recovery["selected"]
                recovery_latency = page_recovery["latency_ms"]
                recovery_input_tokens = page_recovery["input_tokens"] or 0
                recovery_output_tokens = page_recovery["output_tokens"] or 0
                if recovery_selected == f"PAGE:{likely_page}":
                    manager.page_in(likely_page)
                    recovery = "page_recovery"
            decision = choose(chooser, state=f"User request: {event.query}\nOnly the current materialized page tools are resident. Choose a tool candidate or a recovery control.", options=tool_choices(manager), expected=event.expected)
            decision["latency_ms"] = round(decision["latency_ms"] + recovery_latency, 3)
            decision["input_tokens"] = (decision["input_tokens"] or 0) + recovery_input_tokens
            decision["output_tokens"] = (decision["output_tokens"] or 0) + recovery_output_tokens
            if decision["selected"] in {item.option_id for item in manager.resident_options()}:
                validated_candidate = decision["selected"]
        elif event.kind == "refine":
            if not any(item.option_id == "calendar:create_event" for item in manager.resident_options()):
                fault = "OptionFault"
            decision = choose(chooser, state=f"User request: {event.query}\nThe current coarse candidate is identified by the runtime; choose the next action.", options=control_choices(("REFINE", "PAGE", "CLARIFY", "STOP")), expected=event.expected)
            if decision["selected"] == "REFINE" and fault is None:
                manager.refine("calendar:create_event", [VirtualOption("calendar:create_event:exact", "create event with exact time and timezone", page_id="refine:calendar:create_event:r1", kind="action")], page_id="refine:calendar:create_event:r1")
                validated_candidate = "calendar:create_event:exact"
                recovery = "refine"
        elif event.kind == "commit":
            decision = choose(chooser, state=f"{event.query}\nThe runtime has already selected one validated candidate; choose only the commit action or a safe control.", options=control_choices(("COMMIT", "CLARIFY", "STOP")), expected=event.expected)
            if decision["selected"] == "COMMIT" and validated_candidate is not None:
                simulated_effects += 1
                effect_performed = True
        elif event.kind == "clarify":
            decision = choose(chooser, state=event.query, options=control_choices(("CLARIFY", "PAGE", "STOP")), expected=event.expected)
            recovery = "safe_pause" if decision["selected"] == "CLARIFY" else None
        elif event.kind == "stale_stop":
            try:
                manager.invalidate_page("browser")
            except KeyError:
                pass
            validated_candidate = None
            fault = "StaleVirtualOption"
            decision = choose(chooser, state=event.query, options=control_choices(("STOP", "PAGE", "CLARIFY")), expected=event.expected)
            recovery = "terminal_stop" if decision["selected"] == "STOP" else None
        else:
            raise ValueError(event.kind)
        rows.append({
            "step": event.name,
            "kind": event.kind,
            "expected": event.expected,
            "selected": decision["selected"],
            "correct": decision["correct"],
            "fault": fault,
            "recovery": recovery,
            "recovery_selected": recovery_selected,
            "latency_ms": decision["latency_ms"],
            "input_tokens": decision["input_tokens"],
            "output_tokens": decision["output_tokens"],
            "resident_count": len(manager.resident_options()),
            "resident_bound": manager.max_resident,
            "context_working_count": len(context.resident()),
            "context_bound": context.max_working,
            "simulated_side_effect": effect_performed,
        })
    return {
        "experiment": "jev-decision-dense-serial-22-step",
        "backend": "contract" if isinstance(chooser, ContractChooser) else "live Jev",
        "steps": rows,
        "summary": {
            "steps": len(rows),
            "decision_accuracy": sum(row["correct"] for row in rows) / len(rows),
            "faults": sum(row["fault"] is not None for row in rows),
            "recoveries": sum(row["recovery"] is not None for row in rows),
            "simulated_effects": simulated_effects,
            "resident_peak": max(row["resident_count"] for row in rows),
            "resident_bound": manager.max_resident,
            "context_peak": max(row["context_working_count"] for row in rows),
            "context_bound": context.max_working,
            "mean_latency_ms": sum(row["latency_ms"] for row in rows) / len(rows),
            "external_side_effects": 0,
        },
        "notes": [
            "Target page/tool IDs are evaluation metadata and are not included in live Jev state or options.",
            "All tool effects are simulated; no external side effects occur.",
            "This is a bounded serial workload, not a full benchmark suite.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if args.live:
        if not (os.environ.get("TYPESAFE_API_KEY") or os.environ.get("JEV_API_KEY")):
            raise SystemExit("Set TYPESAFE_API_KEY or JEV_API_KEY in the process environment")
        chooser: ChoiceBackend = TypeSafeJevChooser(timeout_seconds=30.0)
    else:
        chooser = ContractChooser()
    result = run(chooser)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
