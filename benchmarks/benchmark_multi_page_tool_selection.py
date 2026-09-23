"""Multi-page physical-tool selection over a bounded virtual OptionSpace.

The target page and target tool are hidden from the chooser. In ``--live`` mode
Jev first chooses a PAGE:<id>/CLARIFY/STOP control from page summaries, and only
the selected page is then materialized for a second Jev tool choice. No tool is
executed and no external side effects occur.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jev_agent.jev_client import TypeSafeJevChooser
from jev_agent.models import ChoiceOption

PAGES = {
    "files": ["read_file", "write_file", "list_files"],
    "calendar": ["create_event", "list_events", "delete_event"],
    "database": ["query_rows", "update_row", "delete_row"],
    "deploy": ["deploy_service", "rollback_service", "rollout_status"],
    "browser": ["open_url", "find_text", "download_file"],
    "memory": ["retrieve_recent", "retrieve_archive", "summarize_memory"],
}
SUMMARIES = {
    "files": "workspace file operations",
    "calendar": "calendar event scheduling",
    "database": "database row queries and updates",
    "deploy": "service deployment and rollout",
    "browser": "web browsing and page retrieval",
    "memory": "historical context and memory retrieval",
}
CASES = [
    ("read a source file", "files", "read_file", "COMMIT"),
    ("schedule a review meeting", "calendar", "create_event", "COMMIT"),
    ("query account rows", "database", "query_rows", "COMMIT"),
    ("deploy the api service", "deploy", "deploy_service", "COMMIT"),
    ("open the documentation url", "browser", "open_url", "COMMIT"),
    ("retrieve last week decision", "memory", "retrieve_recent", "COMMIT"),
    ("read or query the source", "files", "read_file", "CLARIFY"),
    ("inspect service rollout", "deploy", "rollout_status", "COMMIT"),
    ("delete the old database row", "database", "delete_row", "COMMIT"),
    ("download the report from webpage", "browser", "download_file", "COMMIT"),
    ("missing archive memory", "memory", "retrieve_archive", "COMMIT"),
    ("write then schedule", "files", "write_file", "CLARIFY"),
]


def lexical_score(query: str, text: str) -> int:
    words = set(query.lower().replace("_", " ").split())
    return len(words & set(text.lower().replace("_", " ").split()))


def ranked_pages(query: str) -> list[str]:
    return sorted(PAGES, key=lambda page: (lexical_score(query, SUMMARIES[page]), page), reverse=True)


def lexical_tool(query: str, page_id: str) -> str:
    return max(PAGES[page_id], key=lambda tool: (lexical_score(query, tool), tool))


def page_options() -> list[ChoiceOption]:
    return [
        ChoiceOption(f"PAGE:{page_id}", f"Materialize page {page_id}: {SUMMARIES[page_id]}")
        for page_id in PAGES
    ] + [
        ChoiceOption("CLARIFY", "Ask the user because the requested tool or constraint is ambiguous."),
        ChoiceOption("STOP", "Stop safely because no authorized page can satisfy the request."),
    ]


def tool_options(page_id: str) -> list[ChoiceOption]:
    return [
        ChoiceOption(tool, f"Use tool {tool.replace('_', ' ')} from the materialized {page_id} page.")
        for tool in PAGES[page_id]
    ] + [
        ChoiceOption("CLARIFY", "Ask the user because the requested operation is ambiguous."),
        ChoiceOption("STOP", "Stop safely because this page cannot satisfy the request."),
    ]


def run_case_live(chooser: TypeSafeJevChooser, query: str, target_page: str, target_tool: str, expected: str) -> dict:
    started = time.perf_counter()
    page_result = chooser.choose(
        state=(
            f"User request: {query}\n"
            "The physical tool catalog is partitioned into virtual pages. "
            "Only the following page summaries are visible; no tool details are resident yet."
        ),
        instructions="Choose exactly one PAGE:<page_id>, CLARIFY, or STOP. Do not invent a page or tool.",
        options=page_options(),
    )
    page_choice = page_result.choice
    page_id = page_choice.removeprefix("PAGE:") if page_choice.startswith("PAGE:") else None
    page_correct = page_id == target_page
    tool_choice = None
    tool_correct = False
    tool_latency_ms = 0.0
    if page_id in PAGES:
        tool_started = time.perf_counter()
        tool_result = chooser.choose(
            state=(
                f"User request: {query}\n"
                f"Materialized page: {page_id}\n"
                f"Page summary: {SUMMARIES[page_id]}\n"
                "Choose only among the tools on this materialized page."
            ),
            instructions="Choose exactly one tool, CLARIFY, or STOP. Do not invent a tool.",
            options=tool_options(page_id),
        )
        tool_choice = tool_result.choice
        tool_correct = tool_choice == target_tool
        tool_latency_ms = (time.perf_counter() - tool_started) * 1000
    final_success = (
        page_choice == "CLARIFY" if expected == "CLARIFY" else page_correct and tool_correct
    )
    return {
        "query": query,
        "target_page": target_page,
        "target_tool": target_tool,
        "expected_action": expected,
        "page_choice": page_choice,
        "page_correct": page_correct,
        "materialized_page": page_id,
        "tool_choice": tool_choice,
        "tool_correct": tool_correct,
        "final_success": final_success,
        "jev_calls": 1 + int(page_id in PAGES),
        "page_latency_ms": round(page_result.latency_ms, 3),
        "tool_latency_ms": round(tool_latency_ms, 3),
        "latency_ms": round((time.perf_counter() - started) * 1000, 3),
        "page_input_tokens": page_result.input_tokens,
        "page_output_tokens": page_result.output_tokens,
        "resident_bound": 2,
    }


def run_case_lexical(query: str, target_page: str, target_tool: str, expected: str) -> dict:
    started = time.perf_counter()
    ranked = ranked_pages(query)
    selected_page = ranked[0]
    page_correct = selected_page == target_page
    selected_tool = lexical_tool(query, selected_page)
    tool_correct = selected_tool == target_tool
    final_success = expected == "CLARIFY" or page_correct and tool_correct
    return {
        "query": query,
        "target_page": target_page,
        "target_tool": target_tool,
        "expected_action": expected,
        "ranked_pages": ranked,
        "page_choice": f"PAGE:{selected_page}",
        "page_correct": page_correct,
        "materialized_page": selected_page,
        "tool_choice": selected_tool,
        "tool_correct": tool_correct,
        "final_success": final_success,
        "jev_calls": 0,
        "latency_ms": round((time.perf_counter() - started) * 1000, 5),
        "resident_bound": 2,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "results" / "multi-page-tool-selection-latest.json")
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    chooser = TypeSafeJevChooser() if args.live else None
    rows = []
    for index, (query, target_page, target_tool, expected) in enumerate(CASES, 1):
        row = (
            run_case_live(chooser, query, target_page, target_tool, expected)
            if chooser is not None
            else run_case_lexical(query, target_page, target_tool, expected)
        )
        row["case"] = index
        rows.append(row)
    times = sorted(row["latency_ms"] for row in rows)
    page_rows = [row for row in rows if row["expected_action"] != "CLARIFY"]
    tool_rows = [row for row in page_rows if row["materialized_page"] is not None]
    clarify_rows = [row for row in rows if row["expected_action"] == "CLARIFY"]
    summary = {
        "name": "multi-page-tool-selection",
        "cases": len(rows),
        "target_hidden_from_chooser": True,
        "decision_backend": "live Jev" if args.live else "deterministic lexical baseline",
        "page_cases": len(page_rows),
        "page_localization_rate": round(sum(row["page_correct"] for row in page_rows) / len(page_rows), 3),
        "tool_cases": len(tool_rows),
        "in_page_tool_selection_rate": round(sum(row["tool_correct"] for row in tool_rows) / len(tool_rows), 3),
        "clarify_cases": len(clarify_rows),
        "clarify_accuracy": round(sum(row["page_choice"] == "CLARIFY" for row in clarify_rows) / len(clarify_rows), 3),
        "final_success_rate": round(sum(row["final_success"] for row in rows) / len(rows), 3),
        "jev_calls": sum(row["jev_calls"] for row in rows),
        "resident_bound": 2,
        "p50_ms": round(times[(len(times) - 1) // 2], 5),
        "p95_ms": round(times[min(len(times) - 1, max(0, int(len(times) * 0.95) - 1))], 5),
        "external_side_effects": 0,
    }
    output = {**summary, "steps": rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
