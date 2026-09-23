"""Offline recovery-gate matrix for bounded virtual tool pages.

Each target page is tested under empty, wrong-page, stale, and correct-resident
states. The gate blocks invalid tool resolution before any simulated effect,
recovers the target page, then performs in-page selection. No Jev/network or
external side effects are used.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jev_agent.virtual_option import OptionFault, StaleVirtualOption, VirtualOption, VirtualOptionManager

PAGES = {
    "files": ("read_file", "list_files"),
    "calendar": ("create_event", "list_events"),
    "database": ("query_rows", "update_row"),
    "browser": ("open_url", "find_text"),
}
STATES = ("empty", "wrong_page", "stale", "correct_resident")


def build_manager() -> VirtualOptionManager:
    manager = VirtualOptionManager(max_resident=2, max_pages=len(PAGES))
    for page_id, tools in PAGES.items():
        manager.register_page(
            page_id,
            [VirtualOption(f"{page_id}:{tool}", f"Use {tool}", page_id=page_id, kind="tool") for tool in tools],
        )
    return manager


def prepare(manager: VirtualOptionManager, target_page: str, state: str) -> str | None:
    if state == "empty":
        return None
    if state == "wrong_page":
        wrong = next(page for page in PAGES if page != target_page)
        manager.page_in(wrong)
        return wrong
    manager.page_in(target_page)
    if state == "stale":
        manager.invalidate_page(target_page)
    return target_page


def run_case(target_page: str, state: str) -> dict:
    manager = build_manager()
    target_tool = PAGES[target_page][0]
    resident_page = prepare(manager, target_page, state)
    target_id = f"{target_page}:{target_tool}"
    blocked = 0
    gate_trigger = "none"
    recovery = "none"
    tool_choice = None
    tool_correct = False
    # The gate runs before any tool effect. A non-resident or stale target is
    # deliberately attempted once to measure the blocked invalid call.
    try:
        manager.resolve(target_id)
        gate_trigger = "resident_ok"
    except StaleVirtualOption:
        blocked = 1
        gate_trigger = "stale_option"
    except OptionFault:
        blocked = 1
        gate_trigger = "missing_option"
    if gate_trigger != "resident_ok":
        try:
            if gate_trigger == "stale_option":
                # A stale page is refreshed with a higher revision before page-in.
                tools = PAGES[target_page]
                manager.register_page(
                    target_page,
                    [VirtualOption(f"{target_page}:{tool}", f"Use {tool}", page_id=target_page, kind="tool", revision=2) for tool in tools],
                    revision=2,
                )
            manager.page_in(target_page, limit=2)
            recovery = "page_recovery"
        except (OptionFault, StaleVirtualOption):
            recovery = "page_recovery_failed"
    # Selection is only exposed after a successful gate/recovery.
    try:
        resolved = manager.resolve(target_id)
        tool_choice = resolved.option_id
        tool_correct = resolved.option_id == target_id
    except (OptionFault, StaleVirtualOption):
        recovery = "page_recovery_failed"
    return {
        "target_page": target_page,
        "state": state,
        "initial_resident_page": resident_page,
        "gate_trigger": gate_trigger,
        "blocked_invalid_tool_calls": blocked,
        "page_recovery": recovery,
        "materialized_page": target_page if recovery == "page_recovery" or gate_trigger == "resident_ok" else None,
        "tool_choice": tool_choice,
        "in_page_selection": tool_correct,
        "end_to_end_success": tool_correct,
        "simulated_effects": 0,
        "resident_count": len(manager.resident_options()),
        "resident_bound": manager.max_resident,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "results" / "recovery-gate-matrix-latest.json")
    args = parser.parse_args()
    rows = [run_case(page, state) for page in PAGES for state in STATES]
    summary = {
        "name": "recovery-gate-matrix",
        "backend": "offline VirtualOptionManager",
        "cases": len(rows),
        "states": list(STATES),
        "pages": len(PAGES),
        "gate_trigger_counts": {k: sum(row["gate_trigger"] == k for row in rows) for k in ("resident_ok", "missing_option", "stale_option")},
        "blocked_invalid_tool_calls": sum(row["blocked_invalid_tool_calls"] for row in rows),
        "page_recovery_rate": round(sum(row["page_recovery"] == "page_recovery" for row in rows if row["state"] != "correct_resident") / (len(rows) - len(PAGES)), 3),
        "in_page_selection_rate": round(sum(row["in_page_selection"] for row in rows) / len(rows), 3),
        "end_to_end_success_rate": round(sum(row["end_to_end_success"] for row in rows) / len(rows), 3),
        "resident_peak": max(row["resident_count"] for row in rows),
        "resident_bound": 2,
        "external_side_effects": 0,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({**summary, "cases_detail": rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
