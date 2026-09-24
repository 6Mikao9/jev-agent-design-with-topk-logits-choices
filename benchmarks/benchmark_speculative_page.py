"""Deterministic PAGE shadow-prefetch experiment.

This is a timing model, not a live Jev/network benchmark.  It measures how much
page preparation could overlap a fixed Jev wait window under a known transition
trace.  The predictor is an explicit ranking signal and never changes choices.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jev_agent.speculation import rank_pages
from jev_agent.virtual_option import VirtualOption, VirtualOptionManager


PAGES = ("tools", "memory", "files", "git", "control", "history")
COST_MS = {"tools": 18.0, "memory": 30.0, "files": 24.0, "git": 12.0, "control": 8.0, "history": 20.0}
TRACE = ("tools", "files", "files", "git", "memory", "files", "tools", "history",
         "memory", "files", "git", "tools", "history", "memory", "files", "tools",
         "git", "files", "memory", "tools", "history")
TRANSITIONS = {
    "tools": (("files", .68), ("memory", .18), ("git", .08), ("history", .06)),
    "files": (("git", .46), ("tools", .25), ("memory", .17), ("history", .12)),
    "git": (("memory", .52), ("files", .27), ("tools", .13), ("history", .08)),
    "memory": (("files", .61), ("tools", .19), ("history", .12), ("git", .08)),
    "history": (("memory", .44), ("tools", .29), ("files", .18), ("git", .09)),
    "control": (("tools", .50), ("files", .30), ("memory", .20)),
}


def run(top_b: int, *, jev_wait_ms: float) -> dict:
    manager = VirtualOptionManager(max_resident=2)
    for page in PAGES:
        manager.register_page(page, [VirtualOption(f"{page}:0", page, page_id=page)])
    hits = 0
    prefetched = 0
    useful = 0
    baseline_stall = 0.0
    residual_stall = 0.0
    hidden = 0.0
    rows = []
    for current, target in zip(TRACE, TRACE[1:]):
        ranking = rank_pages(TRANSITIONS[current], top_b=top_b)
        prefetched += len(ranking)
        cost = COST_MS[target]
        baseline_stall += cost
        hit = target in ranking
        if hit:
            hits += 1
            useful += 1
            hidden_now = min(cost, jev_wait_ms)
        else:
            hidden_now = 0.0
        hidden += hidden_now
        residual_stall += cost - hidden_now
        rows.append({"current": current, "target": target, "ranked_pages": ranking,
                     "hit": hit, "prepare_cost_ms": cost, "hidden_ms": hidden_now,
                     "residual_stall_ms": cost - hidden_now})
    return {"mode": f"top-{top_b}", "steps": len(rows), "jev_wait_ms": jev_wait_ms,
            "prefetch_hit_rate": hits / len(rows), "useful_prefetch_ratio": useful / prefetched,
            "baseline_stall_ms": baseline_stall, "residual_stall_ms": residual_stall,
            "hidden_latency_ms": hidden, "waste_ratio": 1 - useful / prefetched,
            "rows": rows}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--jev-wait-ms", type=float, default=20.0)
    args = parser.parse_args()
    if args.jev_wait_ms < 0:
        raise SystemExit("--jev-wait-ms must be non-negative")
    results = [{"mode": "none", "steps": len(TRACE) - 1, "jev_wait_ms": args.jev_wait_ms,
                "prefetch_hit_rate": 0.0, "useful_prefetch_ratio": 0.0,
                "baseline_stall_ms": sum(COST_MS[p] for p in TRACE[1:]),
                "residual_stall_ms": sum(COST_MS[p] for p in TRACE[1:]),
                "hidden_latency_ms": 0.0, "waste_ratio": 0.0, "rows": []}]
    results.extend(run(k, jev_wait_ms=args.jev_wait_ms) for k in (1, 2))
    report = {"experiment": "synthetic-page-speculation", "backend": "deterministic timing model",
              "limitations": ["Known transition trace and costs; no real Jev/API/network.",
                              "No page content is used to choose the target; trace labels score only after prediction.",
                              "The model assumes preparation starts during the Jev wait window and has no shared-resource contention."],
              "results": results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = [{"mode": r["mode"], **{x: r[x] for x in (
        "prefetch_hit_rate", "useful_prefetch_ratio", "residual_stall_ms",
        "hidden_latency_ms", "waste_ratio")}} for r in results]
    print(json.dumps({"results": summary}, ensure_ascii=False))


if __name__ == "__main__":
    main()
