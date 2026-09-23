"""Replay bounded two-stage memory control paths without a network key."""
from __future__ import annotations

import argparse
import json
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
    def __init__(self, *, desired_count: int = 1, stale_page: str | None = None, index=None):
        self.desired_count = desired_count
        self.stale_page = stale_page
        self.index = index

    def choose(self, *, state: str, instructions: str, options: list[ChoiceOption]) -> ChoiceResult:
        page_options = [item for item in options if item.option_id.startswith("PAGE_")]
        if page_options:
            # The first page is the scenario's relevant page.  This is a
            # deterministic chooser for state-machine wiring, not a quality model.
            choice = page_options[0].option_id
        else:
            top_options = [item for item in options if item.option_id.startswith("TOP_")]
            wanted = f"TOP_{self.desired_count}"
            choice = wanted if any(item.option_id == wanted for item in top_options) else top_options[0].option_id
            if self.stale_page and self.index is not None:
                self.index.mark_stale(self.stale_page)
        probabilities = {item.option_id: (1.0 if item.option_id == choice else 0.0) for item in options}
        return ChoiceResult(choice, probabilities, 1.0, "replay")


def _index(pages: list[MemoryPage]) -> PagedMemoryIndex:
    index = PagedMemoryIndex(max_pages=max(1, len(pages)))
    for page in pages:
        index.upsert(page)
    return index


def run_case(name: str) -> dict:
    if name == "single":
        index = _index([
            MemoryPage("departure", "Friday departure plan", "Leave Friday at 08:00."),
            MemoryPage("unrelated", "TCP transport choice", "Use TCP."),
        ])
        chooser = ReplayChooser(index=index)
        context = "Which departure plan should I follow?"
        selector = TwoStageMemorySelector(chooser)
    elif name == "ambiguous_two_pages":
        index = _index([
            MemoryPage("fri", "Friday departure plan", "Leave Friday at 08:00."),
            MemoryPage("sat", "Saturday departure alternative", "Leave Saturday at 09:00."),
        ])
        chooser = ReplayChooser(desired_count=2, index=index)
        context = "Compare the Friday and Saturday departure plans."
        selector = TwoStageMemorySelector(chooser)
    elif name == "no_candidates":
        index = _index([MemoryPage("tcp", "TCP transport choice", "Use TCP.")])
        chooser = ReplayChooser(index=index)
        context = "Which departure plan should I follow?"
        selector = TwoStageMemorySelector(chooser)
    elif name == "read_budget":
        index = _index([MemoryPage("departure", "Friday departure plan", "x" * 128)])
        chooser = ReplayChooser(index=index)
        context = "Which departure plan should I follow?"
        selector = TwoStageMemorySelector(chooser, max_page_bytes=32)
    elif name == "stale_after_count":
        index = _index([MemoryPage("departure", "Friday departure plan", "Leave Friday at 08:00.")])
        chooser = ReplayChooser(desired_count=1, stale_page="departure", index=index)
        context = "Which departure plan should I follow?"
        selector = TwoStageMemorySelector(chooser)
    else:
        raise ValueError(f"unknown case: {name}")
    started = time.perf_counter()
    result = selector.retrieve(index, context=context)
    return {
        "case": name,
        "status": result.status,
        "candidate_ids": result.candidate_ids,
        "ranked_ids": result.ranked_ids,
        "selected_ids": result.selected_ids,
        "requested_count": result.requested_count,
        "read_bytes": result.read_bytes,
        "request_bytes": result.request_bytes,
        "stage_ms": result.stage_ms,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        "reason": result.reason,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = {
        "experiment": "two-stage-memory-control-matrix",
        "cases": [run_case(name) for name in (
            "single", "ambiguous_two_pages", "no_candidates", "read_budget", "stale_after_count"
        )],
        "notes": [
            "Replay chooser is deterministic wiring/oracle control, not Jev quality evidence.",
            "The matrix checks bounded reads, ambiguity width, no-candidate control, budget rejection and stale recovery.",
        ],
    }
    encoded = json.dumps(result, ensure_ascii=False, indent=2)
    print(encoded)
    if args.output:
        args.output.write_text(encoded + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
