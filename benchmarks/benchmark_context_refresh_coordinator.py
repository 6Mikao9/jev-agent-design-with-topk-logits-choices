"""Proxy benchmark for bounded, parallel context refresh coordination.

The verifier is deterministic and local.  This measures runtime policy
overhead (directory shortlist, fan-out, cooldown, and stale-epoch rejection),
not Jev semantic quality.  A live Jev adapter can replace ``verify`` later.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jev_agent.context_refresh import ContextRefreshCoordinator, ContextVerification
from jev_agent.context_residency import ContextBlock, ContextFault, ContextResidencyManager


EVENTS = (
    ("deploy", "deploy current plan", "deploy"),
    ("rollback", "rollback recovery plan", "rollback"),
    ("audit", "audit approval evidence", "audit"),
    ("deploy", "deploy current plan", "deploy"),
    ("rollback", "rollback recovery plan", "rollback"),
    ("audit", "audit approval evidence", "audit"),
)


def build_manager() -> ContextResidencyManager:
    manager = ContextResidencyManager(max_working=1, hysteresis=0.05)
    manager.register(ContextBlock("goal", "global safety constraint", "raw://goal",
                                  kind="constraint", pinned=True))
    manager.register(ContextBlock("deploy", "deploy phase current plan", "raw://deploy", phase="deploy"))
    manager.register(ContextBlock("rollback", "rollback phase recovery plan", "raw://rollback", phase="rollback"))
    manager.register(ContextBlock("audit", "audit phase evidence review", "raw://audit", phase="audit"))
    manager.register(ContextBlock("noise", "unrelated historical note", "raw://noise"))
    return manager


def run_once(*, top_m: int, load_k: int, sleep_ms: float = 0.0) -> dict:
    manager = build_manager()
    coordinator = ContextRefreshCoordinator(manager, max_verifiers=top_m,
                                             max_refreshes_per_phase=8,
                                             cooldown_steps=0, max_workers=top_m)
    rows = []
    for phase, query, target in EVENTS:
        def verify(block, _query, _epoch, target=target):
            if sleep_ms:
                time.sleep(sleep_ms / 1000.0)
            return ContextVerification(block.block_id, block.block_id == target,
                                       0.95 if block.block_id == target else 0.10,
                                       "synthetic target" if block.block_id == target else "negative")

        started = time.perf_counter()
        result = coordinator.refresh(query, phase=phase, verifier=verify,
                                     top_m=top_m, load_k=load_k, reason="synthetic_fault")
        elapsed_ms = (time.perf_counter() - started) * 1000
        try:
            manager.require(target)
            hit = True
        except ContextFault:
            hit = False
        rows.append({"phase": phase, "target": target, "status": result.status,
                     "selected_ids": list(result.selected_ids), "hit": hit,
                     "candidate_ids": list(result.candidate_ids), "elapsed_ms": elapsed_ms,
                     "stage_ms": result.stage_ms})
    return {"rows": rows,
            "committed": sum(row["status"] == "committed" for row in rows),
            "hits": sum(row["hit"] for row in rows),
            "verifier_calls": sum(len(row["candidate_ids"]) for row in rows),
            "avg_elapsed_ms": sum(row["elapsed_ms"] for row in rows) / len(rows)}


def run_storm() -> dict:
    manager = build_manager()
    coordinator = ContextRefreshCoordinator(manager, max_verifiers=2,
                                             max_refreshes_per_phase=1,
                                             cooldown_steps=2, max_workers=2)
    statuses = []
    for _ in range(5):
        result = coordinator.refresh(
            "deploy current plan", phase="deploy",
            verifier=lambda block, _query, _epoch: ContextVerification(block.block_id, True, 0.9),
            top_m=2, load_k=1, reason="repeated_fault",
        )
        statuses.append(result.status)
    return {"statuses": statuses, "suppressed": statuses.count("suppressed")}


def run_stale() -> dict:
    manager = build_manager()
    coordinator = ContextRefreshCoordinator(manager, max_verifiers=2,
                                             cooldown_steps=0, max_workers=2)

    def stale(block, _query, _epoch):
        coordinator.notify_state_change()
        return ContextVerification(block.block_id, True, 1.0, "state changed")

    result = coordinator.refresh("deploy current plan", phase="deploy", verifier=stale,
                                 top_m=2, load_k=1, reason="revision_event")
    return {"status": result.status, "reason": result.reason,
            "resident_ids": [block.block_id for block in manager.resident()]}


def run_suite() -> dict:
    parallel = run_once(top_m=2, load_k=1, sleep_ms=2.0)
    return {
        "experiment": "bounded-context-refresh-coordinator-proxy",
        "config": {"events": EVENTS, "top_m": 2, "load_k": 1,
                   "verifier_sleep_ms": 2.0, "note": "local deterministic verifier"},
        "parallel": parallel,
        "storm_guard": run_storm(),
        "stale_guard": run_stale(),
        "limitations": [
            "Verifier is deterministic and does not establish Jev semantic accuracy.",
            "Context blocks still carry raw_content_ref; this benchmark measures residency, not external body loading.",
            "Directory uses lexical candidates; no vector index or multi-level traversal is enabled.",
            "Live Jev latency, rate limits, and confidence calibration require a separate experiment.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run_suite()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"parallel": report["parallel"], "storm_guard": report["storm_guard"],
                      "stale_guard": report["stale_guard"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
