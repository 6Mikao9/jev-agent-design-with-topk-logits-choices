"""Two-needle conflict and insertion-order sensitivity benchmark.

This benchmark keeps the same two-stage summary-only selector as P0/P1, then
compares bounded raw-content and weighted-hybrid recovery.  It records joint
recall because reading one of two required evidence pages is insufficient.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jev_agent.memory_recovery import RawEvidenceFallback
from jev_agent.memory_selection import TwoStageMemorySelector
from jev_agent.models import ChoiceOption
from jev_agent.paged_memory import MemoryPage, PagedMemoryIndex

from benchmarks.benchmark_memory_p0 import SummaryChooser


ORDERS = ("target_first", "target_last", "random")
STRATEGIES = ("summary", "content", "hybrid")
TARGETS = ("needle-a", "needle-b")
QUERY = "project atlas deployment compare conflict"
MARKERS = tuple(f"source=primary-record {target}" for target in TARGETS)


def _content(kind: str, target: str | None = None) -> str:
    if kind == "primary":
        head = f"source=primary-record {target}"
    elif kind == "history":
        head = f"source=historical-record {target}"
    else:
        head = "source=decoy-record unrelated"
    return head + "\n" + "x" * 260


def build_index(order: str) -> PagedMemoryIndex:
    pages = [
        ("primary-a", "project atlas deployment note alpha", "primary", "needle-a"),
        ("primary-b", "project atlas deployment note beta", "primary", "needle-b"),
        ("history-a", "project atlas deployment needle-a historical conflict", "history", "needle-a"),
        ("history-b", "project atlas deployment needle-b historical conflict", "history", "needle-b"),
        ("decoy-a", "project atlas deployment needle-a needle-b unrelated", "decoy", None),
        ("decoy-b", "project atlas deployment needle-a needle-b unrelated", "decoy", None),
    ]
    if order == "target_last":
        pages = [pages[2], pages[3], pages[4], pages[5], pages[0], pages[1]]
    elif order == "random":
        pages = list(pages)
        random.Random(17).shuffle(pages)
    index = PagedMemoryIndex(max_pages=32)
    for page_id, summary, kind, target in pages:
        index.upsert(MemoryPage(page_id, summary, _content(kind, target)))
    return index


def run_case(order: str, strategy: str) -> dict:
    index = build_index(order)
    chooser = SummaryChooser(QUERY)
    initial = TwoStageMemorySelector(chooser, max_candidates=16, max_pages=2,
                                     max_read_bytes=16_384, max_page_bytes=8_192).retrieve(
                                         index, context=QUERY)
    if strategy == "summary":
        pages = initial.pages
        fallback_status = "disabled"
        recovered_ids: tuple[str, ...] = ()
    else:
        recovered = RawEvidenceFallback(
            required_markers=MARKERS, max_candidates=8, max_pages=2,
            max_read_bytes=16_384, max_page_bytes=8_192, max_scan_bytes=1_000,
            retrieval=strategy,
        ).recover(index, context=QUERY, initial=initial)
        pages = recovered.pages
        fallback_status = recovered.status
        recovered_ids = recovered.recovered_ids
    selected = {page.page_id for page in pages}
    candidate_set = set(initial.candidate_ids)
    candidate_count = sum(target in candidate_set for target in ("primary-a", "primary-b"))
    target_count = sum(target in selected for target in ("primary-a", "primary-b"))
    recovered_primary = sum(page_id in {"primary-a", "primary-b"} for page_id in recovered_ids)
    precision = recovered_primary / len(recovered_ids) if recovered_ids else 0.0
    return {
        "order": order, "strategy": strategy, "initial_status": initial.status,
        "initial_candidate_ids": list(initial.candidate_ids),
        "initial_selected_ids": list(initial.selected_ids), "selected_ids": sorted(selected),
        "recovered_ids": list(recovered_ids), "needle_recall": target_count / 2.0,
        "candidate_recall": candidate_count / 2.0,
        "joint_recall": target_count == 2, "marker_precision": precision,
        "answer_correct": target_count == 2,
        "fallback_status": fallback_status,
        "read_bytes": sum(len(page.content.encode("utf-8")) for page in pages),
    }


def run_suite() -> dict:
    rows = [run_case(order, strategy) for order in ORDERS for strategy in STRATEGIES]

    def mean(key: str, subset: list[dict]) -> float:
        return sum(float(row[key]) for row in subset) / len(subset) if subset else 0.0

    aggregate = {}
    for strategy in STRATEGIES:
        selected = [row for row in rows if row["strategy"] == strategy]
        aggregate[strategy] = {
            "candidate_recall": mean("candidate_recall", selected),
            "needle_recall": mean("needle_recall", selected),
            "joint_recall": mean("joint_recall", selected),
            "marker_precision": mean("marker_precision", selected),
            "answer_correct_rate": mean("answer_correct", selected),
            "mean_read_bytes": mean("read_bytes", selected),
            "order": {order: {"needle_recall": mean("needle_recall", [r for r in selected if r["order"] == order]),
                               "joint_recall": mean("joint_recall", [r for r in selected if r["order"] == order]),
                               "answer_correct": mean("answer_correct", [r for r in selected if r["order"] == order])}
                      for order in ORDERS},
        }
    return {"experiment": "memory-p2-multineedle-order-9-cases",
            "config": {"orders": ORDERS, "strategies": STRATEGIES, "required_markers": MARKERS,
                       "max_scan_bytes": 1_000, "max_pages": 2, "seed": 17},
            "aggregate": aggregate, "rows": rows,
            "limitations": ["Synthetic two-needle evidence contract, not live Jev quality.",
                            "Raw scanning is insertion-order bounded and stops at max_scan_bytes.",
                            "The marker contract is supplied by a verifier and is not a hidden page id."]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run_suite()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["aggregate"], ensure_ascii=False))


if __name__ == "__main__":
    main()
