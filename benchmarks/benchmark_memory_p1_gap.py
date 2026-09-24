"""Compare summary-only memory selection with bounded raw-evidence recovery."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jev_agent.context_residency import ContextBlock, ContextResidencyManager
from jev_agent.memory_recovery import RawEvidenceFallback
from jev_agent.memory_selection import TwoStageMemorySelector
from jev_agent.models import ChoiceOption
from jev_agent.paged_memory import MemoryPage, PagedMemoryIndex

from benchmarks.benchmark_memory_p0 import (OMISSIONS, POSITIONS, STATES, SummaryChooser, make_episode)


def _initial(meta: dict):
    index = PagedMemoryIndex(max_pages=64)
    target_meta = make_episode(meta["position"], meta["omission"], meta["state"], index)
    chooser = SummaryChooser(target_meta["query"],
                             stale_page=target_meta["target_page"] if meta["state"] == "stale" else None,
                             index=index)
    selector = TwoStageMemorySelector(chooser, max_candidates=16, max_pages=2,
                                      max_read_bytes=16_384, max_page_bytes=8_192)
    result = selector.retrieve(index, context=target_meta["query"])
    return index, target_meta, result


def run_episode(meta: dict, *, fallback: bool) -> dict:
    index, target_meta, initial = _initial(meta)
    recovered = RawEvidenceFallback(
        required_markers=("source=primary-record",), max_candidates=8,
        max_pages=2, max_read_bytes=16_384, max_page_bytes=8_192,
    ).recover(index, context=target_meta["query"], initial=initial) if fallback else None
    pages = recovered.pages if recovered is not None else initial.pages
    selected = {page.page_id for page in pages}
    target_read = target_meta["target_page"] in selected
    contradiction_read = (target_meta["contradiction_page"] in selected
                          if target_meta["contradiction_page"] else True)
    status = initial.status if recovered is None else (
        initial.status if recovered.status in {"not_needed", "not_attempted"} else recovered.status
    )
    answer_correct = target_read and contradiction_read and status in {"read_complete", "not_needed", "recovered"}
    guard_safe = (meta["state"] != "stale" and initial.status != "stale_selection") or (
        meta["state"] == "stale" and initial.status == "stale_selection")
    working = ContextResidencyManager(max_working=2)
    for page in pages:
        working.register(ContextBlock(page.page_id, page.summary, f"raw://{page.page_id}", revision=page.revision))
    resident = working.rebuild(target_meta["query"], advance_step=True) if pages else ()
    return {
        "episode_id": target_meta["episode_id"], "position": meta["position"],
        "omission": meta["omission"], "state": meta["state"],
        "initial_status": initial.status, "fallback_status": recovered.status if recovered else "disabled",
        "initial_selected_ids": list(initial.selected_ids),
        "recovered_ids": list(recovered.recovered_ids) if recovered else [],
        "target_page": target_meta["target_page"], "target_read": target_read,
        "needle_evidence_recall": target_read, "answer_correct": answer_correct,
        "guard_safe": guard_safe, "resident_ids": [block.block_id for block in resident],
        "read_bytes": recovered.read_bytes if recovered else initial.read_bytes,
        "reason": recovered.reason if recovered else initial.reason,
    }


def _summary(rows: list[dict]) -> dict:
    def mean(key: str, subset: list[dict] = rows):
        return sum(float(row[key]) for row in subset) / len(subset) if subset else 0.0
    return {
        "episodes": len(rows), "page_hit_rate": mean("target_read"),
        "needle_evidence_recall": mean("needle_evidence_recall"),
        "answer_correct_rate": mean("answer_correct"), "guard_safe_rate": mean("guard_safe"),
        "recovery_rate": sum(row["fallback_status"] == "recovered" for row in rows) / len(rows),
        "mean_read_bytes": mean("read_bytes"),
        "state": {state: {"needle_evidence_recall": mean("needle_evidence_recall", [r for r in rows if r["state"] == state]),
                           "answer_correct_rate": mean("answer_correct", [r for r in rows if r["state"] == state]),
                           "recovery_rate": sum(r["fallback_status"] == "recovered" for r in rows if r["state"] == state) /
                           len([r for r in rows if r["state"] == state])} for state in STATES},
    }


def run_suite() -> dict:
    metas = [{"position": position, "omission": omission, "state": state}
             for position in POSITIONS for omission in OMISSIONS for state in STATES]
    baseline = [run_episode(meta, fallback=False) for meta in metas]
    recovered = [run_episode(meta, fallback=True) for meta in metas]
    return {"experiment": "memory-p1-summary-gap-fallback-48",
            "config": {"episodes": len(metas), "required_markers": ["source=primary-record"],
                       "max_candidates": 8, "max_pages": 2, "max_scan_bytes": 65_536},
            "baseline": _summary(baseline), "fallback": _summary(recovered),
            "rows": [{"baseline": before, "fallback": after} for before, after in zip(baseline, recovered)],
            "limitations": ["Deterministic retrieval proxy, not live Jev quality.",
                            "The source marker is a task evidence contract, not a hidden target page id.",
                            "Raw scanning is bounded but not a vector or learned retriever."]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run_suite()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"baseline": report["baseline"], "fallback": report["fallback"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
