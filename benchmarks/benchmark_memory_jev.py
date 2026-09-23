"""Replay or run the two-stage page-table memory selector.

The default scripted chooser is deterministic and does not contact Jev. Set
``--live-jev`` with ``TYPESAFE_API_KEY`` or ``JEV_API_KEY`` in the process
environment to exercise the same selector against the real Choice endpoint.
No credential is accepted on the command line or written to the output.
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

from jev_agent.memory_selection import TwoStageMemorySelector
from jev_agent.models import ChoiceOption, ChoiceResult
from jev_agent.paged_memory import MemoryPage, PagedMemoryIndex


class ReplayChooser:
    """Select the page containing the query and the smallest useful prefix."""

    def choose(self, *, state: str, instructions: str, options: list[ChoiceOption]) -> ChoiceResult:
        if any(option.option_id.startswith("PAGE_") for option in options):
            choice = next(
                (option.option_id for option in options if "Friday" in option.description),
                "NONE",
            )
        else:
            choice = next(
                (option.option_id for option in options if option.option_id == "TOP_2"),
                next((option.option_id for option in options if option.option_id.startswith("TOP_")), "NONE"),
            )
        probabilities = {option.option_id: (1.0 if option.option_id == choice else 0.0) for option in options}
        return ChoiceResult(choice, probabilities, 1.0, "replay")


def build_index() -> PagedMemoryIndex:
    index = PagedMemoryIndex()
    index.upsert(MemoryPage("departure", "Friday departure plan", "Leave Friday at 08:00."))
    index.upsert(MemoryPage("transport", "TCP transport choice", "Use TCP for the upload."))
    index.upsert(MemoryPage("backup", "Backup checklist", "Keep two encrypted copies."))
    return index


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live-jev", action="store_true", help="call TypeSafe Choice instead of replay")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.live_jev:
        from jev_agent.jev_client import TypeSafeJevChooser

        chooser = TypeSafeJevChooser(timeout_seconds=30.0)
        backend = "typesafe_jev"
    else:
        chooser = ReplayChooser()
        backend = "replay"
    started = time.perf_counter()
    result = TwoStageMemorySelector(chooser).retrieve(
        build_index(), context="Which departure plan should I follow?"
    )
    elapsed_ms = (time.perf_counter() - started) * 1000
    output = {
        "experiment": "two-stage-paged-memory-selector",
        "backend": backend,
        "status": result.status,
        "candidate_ids": result.candidate_ids,
        "ranked_ids": result.ranked_ids,
        "selected_ids": result.selected_ids,
        "requested_count": result.requested_count,
        "read_bytes": result.read_bytes,
        "request_bytes": result.request_bytes,
        "stage_ms": result.stage_ms,
        "elapsed_ms": round(elapsed_ms, 3),
        "reason": result.reason,
        "pages": [{"page_id": page.page_id, "content": page.content} for page in result.pages],
        "notes": [
            "Replay is a mechanism check, not Jev quality evidence.",
            "Live mode reads the credential only from the process environment.",
        ],
    }
    encoded = json.dumps(output, ensure_ascii=False, indent=2)
    print(encoded)
    if args.output:
        args.output.write_text(encoded + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
