"""Answer-blind, bounded multi-hop paging diagnostic with a real Choice backend.

Evaluation labels are owned by score_episode(); run_episode() receives only a
user request, catalog, and injected initial runtime state. A wrong page really
loads and a wrong tool really terminates the simulated task as a wrong answer.
Directory, tool and control choices all count toward the same interface cap.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jev_agent.jev_client import TypeSafeJevChooser
from jev_agent.models import ChoiceBackend, ChoiceOption
from jev_agent.virtual_option import VirtualOption, VirtualOptionManager


# Each operation has its own description. Every request specifies one action.
# Paired catalogs deliberately contain closely related capabilities.
CATALOG = (
    ("source", "Working-tree source code contents and source file names", (
        ("read_source", "Read the text of a source code file in the working tree.", "Show the current code inside parser.py in the working tree."),
        ("list_sources", "List source code file paths without reading their contents.", "List source file paths in the working tree; do not read their contents."))),
    ("project", "Project metadata and non-source documentation files", (
        ("read_project", "Read a local project metadata or README file.", "Show the text in the local project README.md."),
        ("list_project", "List local project metadata file names only.", "List names of local project metadata files; do not open them."))),
    ("docs", "Search the internal API documentation or open a known internal document", (
        ("search_docs", "Search internal API documentation for a topic.", "Search our internal API documentation for authentication."),
        ("open_doc", "Open an already identified internal documentation page.", "Open the known internal API document auth-guide; no search is needed."))),
    ("web", "Public web search results, excluding internal documentation", (
        ("search_web", "Search the public web for a topic.", "Search the public web for API release announcements."),
        ("open_result", "Open an already selected public web search result.", "Open the public search result already selected as result 3; do not search again."))),
    ("calendar", "People's calendar meetings and appointments", (
        ("create_event", "Create a meeting in a person's calendar.", "Create a review meeting on my calendar tomorrow at 10 UTC."),
        ("list_events", "List meetings already on a person's calendar.", "List my calendar meetings for tomorrow without creating any."))),
    ("scheduler", "Automated background jobs and scheduled machine tasks", (
        ("schedule_task", "Schedule an automated background job.", "Schedule an automated backup job every night; this is not a meeting."),
        ("list_tasks", "List configured automated background jobs.", "List the configured automated background jobs without scheduling new ones."))),
    ("accounts", "Customer account records, excluding purchase orders", (
        ("query_accounts", "Read customer account records without updating them.", "Read the billing owner field from customer account records."),
        ("update_account", "Update a customer account record.", "Update the billing owner of customer account A12 to Mei."))),
    ("orders", "Purchase order records, excluding customer accounts", (
        ("query_orders", "Read purchase order records without updates.", "Read the current status of purchase order O17."),
        ("update_order", "Update a purchase order record.", "Change purchase order O17's delivery note to 'front desk'."))),
    ("deploy", "Service deployment operations and rollout progress", (
        ("deploy_service", "Start deployment of a service release.", "Start deployment of the staging service release r7; no status check is requested."),
        ("rollout_status", "Read progress of an already running deployment.", "Read progress of the existing staging rollout; do not start a new deployment."))),
    ("monitor", "Service health measurements and alert acknowledgements", (
        ("inspect_metrics", "Read service latency measurements without acknowledging alerts.", "Read service latency measurements only; leave alerts unchanged."),
        ("ack_alert", "Mark an existing monitoring alert acknowledged, without reading metrics.", "Mark monitoring alert A9 as acknowledged; no measurements are requested."))),
    ("recent", "Recent conversation memory retrieval and summary generation", (
        ("retrieve_recent", "Retrieve verbatim evidence from recent conversation memory.", "Retrieve the exact recent conversation decision, without summarizing it."),
        ("summarize_recent", "Produce a summary of recent conversation memory.", "Summarize the recent conversation; do not return verbatim evidence."))),
    ("archive", "Archived older conversation memory retrieval and summarization", (
        ("retrieve_archive", "Retrieve verbatim evidence from archived old conversations.", "Retrieve the exact archived conversation decision, without summarizing it."),
        ("summarize_archive", "Produce a summary of archived old conversations.", "Summarize the archived old conversations; do not return verbatim evidence."))),
)


@dataclass(frozen=True)
class RuntimeRequest:
    query: str
    initial_page: str | None = None
    stale_initial: bool = False


@dataclass(frozen=True)
class EvaluationCase:
    case_id: str
    condition: str
    request: RuntimeRequest
    expected_page: str
    expected_tool: str


def catalog_pages(seed: int) -> dict:
    records = list(CATALOG)
    random.Random(seed).shuffle(records)
    pages = {}
    for i, (name, summary, specs) in enumerate(records):
        page_id = f"p{i:02d}"  # opaque IDs; no target-flag or rank supplied
        pages[page_id] = {"name": name, "summary": summary, "tools": [
            {"id": f"{page_id}:op{j}", "description": desc, "query": query}
            for j, (_, desc, query) in enumerate(specs)
        ]}
    return pages


def make_cases(pages: dict, conditions: list[str]) -> list[EvaluationCase]:
    by_name = {p["name"]: pid for pid, p in pages.items()}
    semantic_pairs = {CATALOG[i][0]: CATALOG[i ^ 1][0] for i in range(len(CATALOG))}
    cases = []
    # Alternate the answer's position; the first listed operation is not always gold.
    for i, (pid, page) in enumerate(pages.items()):
        tool = page["tools"][i % 2]
        for condition in conditions:
            initial = None
            if condition == "wrong_page":
                initial = by_name[semantic_pairs[page["name"]]]
            elif condition in ("stale", "correct_resident"):
                initial = pid
            cases.append(EvaluationCase(
                f"{page['name']}-{condition}", condition,
                RuntimeRequest(tool["query"], initial, condition == "stale"), pid, tool["id"],
            ))
    return cases


def register(manager: VirtualOptionManager, pages: dict, page_id: str, revision: int) -> None:
    manager.register_page(page_id, [
        VirtualOption(t["id"], t["description"], page_id=page_id, revision=revision, kind="tool")
        for t in pages[page_id]["tools"]
    ], revision=revision)


def run_episode(chooser: ChoiceBackend, request: RuntimeRequest, pages: dict,
                *, choice_cap: int = 8, max_calls: int = 10, allow_paging: bool = True) -> dict:
    """Runtime cannot access EvaluationCase or any expected page/tool labels."""
    if choice_cap < 5 or max_calls < 1:
        raise ValueError("choice_cap must be >=5; max_calls must be positive")
    manager = VirtualOptionManager(max_resident=2, max_pages=len(pages))
    revisions = {pid: 1 for pid in pages}
    for pid in pages:
        register(manager, pages, pid, 1)
    active = request.initial_page
    if active:
        manager.page_in(active)
        if request.stale_initial:
            revisions[active] = 2  # injected environment change, not an answer label
    ids = list(pages)
    window_size = choice_cap - 3
    windows = [ids[i:i + window_size] for i in range(0, len(ids), window_size)]
    cursor = 0
    events = []
    calls = []
    selected_tool = None
    terminal = "budget_exhausted"
    last_observation = ""
    resident_peak = len(manager.resident_options())
    started = perf_counter()
    for _ in range(max_calls):
        # Check *actual cached objects* against the catalog version; no hidden target.
        if active and any(o.revision != revisions[active] for o in manager.resident_options()):
            manager.invalidate_page(active)
            events.append({"event": "stale_block", "page": active})
            last_observation = "Cached page revision changed. Re-open a current page before using tools."
            active = None
        if active:
            options = [ChoiceOption(o.option_id, o.description) for o in manager.resident_options()]
            if allow_paging:
                options.append(ChoiceOption("PAGE", "No resident tool can do the requested action; browse the catalog."))
            stage = "tools"
            state = f"User request: {request.query}\nResident page: {pages[active]['summary']}\n{last_observation}"
            instructions = "Select a tool only if it satisfies the requested single action. Use PAGE for missing capability. Use CLARIFY only for an ambiguous request. Selecting a tool ends this simulated task."
        else:
            if not allow_paging:
                terminal = "no_resident_tools"
                break
            stage = "directory"
            options = [ChoiceOption(f"PAGE:{pid}", pages[pid]["summary"]) for pid in windows[cursor]]
            options.append(ChoiceOption("NEXT", "None of these page summaries fits; view the next catalog window."))
            state = f"User request: {request.query}\nCatalog window {cursor + 1}/{len(windows)}. Only these summaries are currently shown.\n{last_observation}"
            instructions = "Choose a page that contains the requested capability. If it is absent here, choose NEXT to continue browsing. CLARIFY is for ambiguous user intent, not for a missing page."
        options.extend([ChoiceOption("CLARIFY", "Ask the user to resolve an ambiguous request."),
                        ChoiceOption("STOP", "End without selecting a tool.")])
        if len(options) > choice_cap:
            raise AssertionError("submitted options exceed interface cap")
        entry = {"stage": stage, "state": state, "instructions": instructions,
                 "options": [asdict(o) for o in options], "option_count": len(options)}
        before_call = perf_counter()
        try:
            result = chooser.choose(state=state, instructions=instructions, options=options)
        except Exception as exc:
            # Do not print error bodies or credentials; partial progress is persisted.
            entry.update(error_type=type(exc).__name__, wall_ms=(perf_counter() - before_call)*1000)
            calls.append(entry)
            terminal = "transport_error"
            break
        entry.update(choice=result.choice, model=result.model, probabilities=result.probabilities,
                     confidence=result.confidence, latency_ms=result.latency_ms,
                     input_tokens=result.input_tokens, output_tokens=result.output_tokens,
                     wall_ms=(perf_counter() - before_call)*1000)
        calls.append(entry)
        choice = result.choice
        if choice not in {o.option_id for o in options}:
            terminal = "invalid_choice"
            break
        if choice in ("CLARIFY", "STOP"):
            terminal = choice.lower()
            break
        if stage == "directory":
            if choice == "NEXT":
                events.append({"event": "next_window", "from": cursor})
                cursor = (cursor + 1) % len(windows)
            else:
                active = choice.split(":", 1)[1]
                # Materialize whatever Jev selected, including an incorrect page.
                register(manager, pages, active, revisions[active])
                manager.page_in(active)
                events.append({"event": "page_in", "page": active})
                last_observation = "Page loaded. Inspect its tools against the user's request."
        elif choice == "PAGE":
            events.append({"event": "missing_capability", "page": active})
            last_observation = f"Left page '{pages[active]['summary']}' because its tools did not satisfy the request."
            active = None
        else:
            selected = manager.resolve(choice, expected_revision=revisions[active])
            selected_tool = selected.option_id
            terminal = "simulated_tool_selection"
            break
        resident_peak = max(resident_peak, len(manager.resident_options()))
    return {"terminal": terminal, "selected_tool": selected_tool, "calls": calls,
            "events": events, "resident_peak": resident_peak, "resident_bound": 2,
            "submitted_choice_peak": max((c["option_count"] for c in calls), default=0),
            "choice_cap": choice_cap, "wall_ms": (perf_counter()-started)*1000,
            "external_side_effects": 0}


def score_episode(case: EvaluationCase, trace: dict) -> dict:
    loaded = [e["page"] for e in trace["events"] if e["event"] == "page_in"]
    return {"case_id": case.case_id, "condition": case.condition,
            "expected_page": case.expected_page, "expected_tool": case.expected_tool,
            "initial_state": asdict(case.request), "success": trace["selected_tool"] == case.expected_tool,
            "first_page_correct": loaded[0] == case.expected_page if loaded else None,
            "wrong_pages_loaded": sum(p != case.expected_page for p in loaded), **trace}


def percentile(values: list[float], p: float) -> float:
    return sorted(values)[max(0, math.ceil(len(values)*p)-1)] if values else 0.0


def summarize(rows: list[dict]) -> dict:
    needs_page = [r for r in rows if r["condition"] != "correct_resident"]
    wrong_start = [r for r in rows if r["condition"] == "wrong_page"]
    missing = [r for r in wrong_start if any(e["event"] == "missing_capability" for e in r["events"])]
    all_calls = [c for r in rows for c in r["calls"]]
    ms = [r["wall_ms"] for r in rows]
    return {"completed_cases": len(rows), "successes": sum(r["success"] for r in rows),
            "success_rate": sum(r["success"] for r in rows)/len(rows) if rows else None,
            "by_condition": {s: {"n": len(rs), "successes": sum(r["success"] for r in rs)}
                             for s in sorted({r["condition"] for r in rows})
                             if (rs := [r for r in rows if r["condition"] == s])},
            "initial_nonresident_cases": len(needs_page),
            "first_page_correct_count": sum(r["first_page_correct"] is True for r in needs_page),
            "missing_detection_numerator": len(missing), "missing_detection_denominator": len(wrong_start),
            "wrong_start_recovery_successes": sum(r["success"] for r in missing),
            "wrong_page_loads": sum(r["wrong_pages_loaded"] for r in rows),
            "next_window_actions": sum(e["event"] == "next_window" for r in rows for e in r["events"]),
            "stale_blocks": sum(e["event"] == "stale_block" for r in rows for e in r["events"]),
            "api_calls": len(all_calls), "transport_errors": sum("error_type" in c for c in all_calls),
            "resident_peak": max((r["resident_peak"] for r in rows), default=0),
            "submitted_choice_peak": max((r["submitted_choice_peak"] for r in rows), default=0),
            "case_p50_ms": statistics.median(ms) if ms else None,
            "case_p95_ms_nearest_rank": percentile(ms, .95),
            "request_p50_ms": statistics.median([c["latency_ms"] for c in all_calls if "latency_ms" in c]) if any("latency_ms" in c for c in all_calls) else None,
            "input_tokens": sum(c.get("input_tokens", 0) for c in all_calls),
            "output_tokens": sum(c.get("output_tokens", 0) for c in all_calls),
            "external_side_effects": 0}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--choice-cap", type=int, default=8)
    parser.add_argument("--max-calls", type=int, default=10)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--states", nargs="+", choices=("empty", "wrong_page", "stale", "correct_resident"),
                        default=["empty", "wrong_page", "stale", "correct_resident"])
    parser.add_argument("--no-paging", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--key-stdin", action="store_true")
    args = parser.parse_args()
    config = {"seed": args.seed, "choice_cap": args.choice_cap, "max_calls": args.max_calls,
              "limit": args.limit, "conditions": args.states, "allow_paging": not args.no_paging,
              "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    pages = catalog_pages(args.seed)
    cases = make_cases(pages, args.states)
    if args.limit is not None:
        cases = cases[:args.limit]
    report = {"experiment": "answer-blind-bounded-paging", "backend": "live Jev",
              "config": config, "logical_pages": len(pages), "logical_tools": sum(len(p["tools"]) for p in pages.values()),
              "catalog": pages, "planned_cases": len(cases), "rows": [],
              "limitations": ["Handwritten atomic queries; no external tool execution.",
                              "Initial conditions are experimental interventions prepared by the evaluator.",
                              "Runtime never receives expected page/tool; labels used only after termination.",
                              "Measures A paging; does not establish B refinement or C memory utility."]}
    if args.resume and args.output.exists():
        report = json.loads(args.output.read_text(encoding="utf-8"))
        if report["config"] != config:
            raise SystemExit("Resume config/script mismatch; choose a new output")
    elif args.output.exists():
        raise SystemExit("Output already exists; use --resume or another path")
    chooser = TypeSafeJevChooser(api_key=sys.stdin.readline().strip() if args.key_stdin else None, timeout_seconds=30)
    done = {r["case_id"] for r in report["rows"]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for case in cases:
        if case.case_id in done:
            continue
        trace = run_episode(chooser, case.request, pages, choice_cap=args.choice_cap,
                            max_calls=args.max_calls, allow_paging=not args.no_paging)
        row = score_episode(case, trace)
        report["rows"].append(row)
        report["summary"] = summarize(report["rows"])
        report["complete"] = len(report["rows"]) == len(cases)
        temp = args.output.with_suffix(args.output.suffix + ".partial")
        temp.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        temp.replace(args.output)
        print(json.dumps({"case": case.case_id, "success": row["success"], "calls": len(trace["calls"]), "terminal": trace["terminal"]}), flush=True)
        if trace["terminal"] == "transport_error":
            print("Stopped after transport error; partial report saved. No automatic retries.", flush=True)
            break
    print(json.dumps(report.get("summary", {}), indent=2))


if __name__ == "__main__":
    main()
