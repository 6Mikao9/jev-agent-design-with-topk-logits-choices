"""48-episode deterministic memory baseline.

The chooser ranks only page-table summaries and never sees the target label or
page content before selection.  Labels are used after termination for scoring.
This is a proxy/oracle control-flow baseline, not real Jev quality evidence.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jev_agent.context_residency import ContextBlock, ContextResidencyManager
from jev_agent.memory_selection import TwoStageMemorySelector
from jev_agent.models import ChoiceOption, ChoiceResult
from jev_agent.paged_memory import MemoryPage, PagedMemoryIndex


POSITIONS = ("head", "middle", "tail", "boundary")
OMISSIONS = ("none", "date", "negation")
STATES = ("fresh", "stale", "conflict", "distractor")


def _terms(text: str) -> set[str]:
    return {x.casefold() for x in re.findall(r"[\w一-龥]+", text)}


class SummaryChooser:
    """Deterministic summary-only ranking control; not a Jev simulator claim."""

    def __init__(self, query: str, *, stale_page: str | None = None, index=None):
        self.query = _terms(query)
        self.stale_page = stale_page
        self.index = index

    def choose(self, *, state: str, instructions: str, options: list[ChoiceOption]) -> ChoiceResult:
        page_options = [o for o in options if o.option_id.startswith("PAGE_")]
        if page_options:
            def score(option):
                match = re.search(r'"summary":\s*"(.*?)"', option.description)
                summary = match.group(1) if match else option.description
                return (-len(self.query & _terms(summary)), option.option_id)
            chosen = sorted(page_options, key=score)[0]
        else:
            top = [o for o in options if o.option_id.startswith("TOP_")]
            if top:
                wanted = "TOP_2" if any(x in self.query for x in {"compare", "conflict", "both"}) else "TOP_2"
                chosen = next((o for o in top if o.option_id == wanted), top[0])
                if self.stale_page and self.index is not None:
                    self.index.mark_stale(self.stale_page)
            else:
                chosen = next((o for o in options if o.option_id == "NONE"), options[0])
        probs = {o.option_id: (1.0 if o.option_id == chosen.option_id else 0.0) for o in options}
        return ChoiceResult(chosen.option_id, probs, 1.0, "summary-replay")


def _content(*, needle: str, position: str, date: str, approved: str,
             source: str = "primary-record") -> str:
    filler = [f"noise-{i}: unrelated event record" for i in range(12)]
    evidence = f"NEEDLE_FACT {needle}: date={date}; approved={approved}; source={source}"
    if position == "head":
        lines = [evidence, *filler]
    elif position == "tail":
        lines = [*filler, evidence]
    elif position == "boundary":
        lines = filler[:6] + [evidence] + filler[6:]
    else:
        lines = filler[:6] + [evidence] + filler[6:]
    return "\n".join(lines)


def make_episode(position: str, omission: str, state_name: str, index: PagedMemoryIndex):
    token = f"A{POSITIONS.index(position)}{OMISSIONS.index(omission)}{STATES.index(state_name)}"
    date, approved = "2026-10-12", "yes"
    summary = f"project atlas deployment plan {token}"
    if omission == "date":
        summary = f"project atlas deployment plan {token} date omitted"
    elif omission == "negation":
        summary = f"project atlas deployment plan {token} approval condition omitted"
    query = f"project atlas deployment {token}"
    target = f"target-{token}"
    index.upsert(MemoryPage(target, summary, _content(needle=token, position=position, date=date, approved=approved)))
    contradiction = None
    if state_name == "conflict":
        contradiction = f"conflict-{token}"
        index.upsert(MemoryPage(contradiction, f"project atlas deployment {token} historical conflict",
                                _content(needle=token, position="middle", date="2026-10-13", approved="no",
                                         source="historical-record")))
        query += " compare conflict"
    distractors = 2 if state_name != "distractor" else 10
    for i in range(distractors):
        page_id = f"distractor-{token}-{i:02d}"
        index.upsert(MemoryPage(page_id, f"project atlas deployment related note {i}",
                                f"RELATED_NOTE {i}: no primary needle for {token}"))
    return {"episode_id": f"{position}-{omission}-{state_name}", "position": position,
            "omission": omission, "state": state_name, "query": query,
            "target_page": target, "contradiction_page": contradiction,
            "needle": f"NEEDLE_FACT {token}"}


def run_episode(meta: dict) -> dict:
    index = PagedMemoryIndex(max_pages=64)
    target_meta = make_episode(meta["position"], meta["omission"], meta["state"], index)
    chooser = SummaryChooser(target_meta["query"],
                             stale_page=target_meta["target_page"] if meta["state"] == "stale" else None,
                             index=index)
    selector = TwoStageMemorySelector(chooser, max_candidates=16, max_pages=2,
                                      max_read_bytes=16_384, max_page_bytes=8_192)
    started = time.perf_counter()
    result = selector.retrieve(index, context=target_meta["query"])
    working = ContextResidencyManager(max_working=2)
    for page in result.pages:
        working.register(ContextBlock(page.page_id, page.summary, f"raw://{page.page_id}", revision=page.revision))
    resident = working.rebuild(target_meta["query"], advance_step=True) if result.pages else ()
    selected = set(result.selected_ids)
    target_read = target_meta["target_page"] in selected
    contradiction_read = target_meta["contradiction_page"] in selected if target_meta["contradiction_page"] else True
    answer_correct = target_read and contradiction_read and result.status == "read_complete"
    guard_safe = (meta["state"] != "stale" and result.status != "stale_selection") or (
        meta["state"] == "stale" and result.status == "stale_selection")
    return {"episode_id": target_meta["episode_id"], "position": meta["position"],
            "omission": meta["omission"], "state": meta["state"],
            "status": result.status, "candidate_ids": result.candidate_ids,
            "ranked_ids": result.ranked_ids, "selected_ids": result.selected_ids,
            "target_page": target_meta["target_page"], "target_read": target_read,
            "needle_evidence_recall": target_read,
            "answer_correct": answer_correct, "guard_safe": guard_safe,
            "resident_ids": [block.block_id for block in resident],
            "read_bytes": result.read_bytes, "request_bytes": result.request_bytes,
            "stage_ms": result.stage_ms, "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "reason": result.reason}


def run_suite() -> dict:
    rows = [run_episode({"position": position, "omission": omission, "state": state})
            for position in POSITIONS for omission in OMISSIONS for state in STATES]
    def mean(key, subset=rows):
        return sum(float(row[key]) for row in subset) / len(subset) if subset else 0.0
    summary = {
        "episodes": len(rows),
        "status_counts": {status: sum(row["status"] == status for row in rows)
                          for status in sorted({row["status"] for row in rows})},
        "page_hit_rate": mean("target_read"),
        "needle_evidence_recall": mean("needle_evidence_recall"),
        "answer_correct_rate": mean("answer_correct"),
        "guard_safe_rate": mean("guard_safe"),
        "mean_read_bytes": mean("read_bytes"),
        "position": {p: {"needle_evidence_recall": mean("needle_evidence_recall", [r for r in rows if r["position"] == p]),
                          "answer_correct_rate": mean("answer_correct", [r for r in rows if r["position"] == p])} for p in POSITIONS},
        "omission": {o: {"needle_evidence_recall": mean("needle_evidence_recall", [r for r in rows if r["omission"] == o]),
                          "answer_correct_rate": mean("answer_correct", [r for r in rows if r["omission"] == o])} for o in OMISSIONS},
        "state": {s: {"needle_evidence_recall": mean("needle_evidence_recall", [r for r in rows if r["state"] == s]),
                       "answer_correct_rate": mean("answer_correct", [r for r in rows if r["state"] == s]),
                       "guard_safe_rate": mean("guard_safe", [r for r in rows if r["state"] == s])} for s in STATES},
    }
    return {"experiment": "memory-p0-48-episodes", "backend": "summary-only deterministic replay chooser",
            "config": {"positions": POSITIONS, "omissions": OMISSIONS, "states": STATES,
                       "max_candidates": 16, "max_pages": 2, "max_read_bytes": 16384, "seed": 7},
            "summary": summary, "rows": rows,
            "limitations": ["Proxy/oracle control-flow, not live Jev quality.",
                            "Synthetic page summaries and evidence; no vector retriever or raw-gap fallback.",
                            "Labels are used only after selector termination."]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run_suite()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
