"""Deterministic real-time context replacement benchmark."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jev_agent.context_residency import ContextBlock, ContextFault, ContextResidencyManager


EVENTS = (
    ("deploy", 1),
    ("rollback", 1),
    ("audit", 1),
    ("deploy", 2),
)


def _manager(*, minimum_residency_steps: int = 0) -> ContextResidencyManager:
    manager = ContextResidencyManager(max_working=2, hysteresis=0.05,
                                      minimum_residency_steps=minimum_residency_steps)
    manager.register(ContextBlock("goal", "global safety constraint", "raw://goal",
                                  kind="constraint", pinned=True))
    manager.register(ContextBlock("deploy", "deploy phase current plan", "raw://deploy", phase="deploy"))
    manager.register(ContextBlock("rollback", "rollback phase recovery plan", "raw://rollback", phase="rollback"))
    manager.register(ContextBlock("audit", "audit phase evidence review", "raw://audit", phase="audit"))
    manager.register(ContextBlock("noise", "unrelated historical note", "raw://noise"))
    return manager


def _run(mode: str) -> dict:
    manager = _manager(minimum_residency_steps=1 if mode == "refresh_hysteresis" else 0)
    if mode in {"static", "refresh", "refresh_hysteresis"}:
        manager.rebuild("deploy", phase="deploy")
    before = tuple(block.block_id for block in manager.resident())
    hits = 0
    faults = 0
    replacements = 0
    revisions = 0
    snapshots = []
    for phase, revision in EVENTS:
        update = ()
        if phase == "deploy" and revision == 2:
            update = (ContextBlock("deploy", "deploy phase current plan revised", "raw://deploy-v2",
                                   revision=2, phase="deploy"),)
            revisions += 1
        if mode != "static":
            resident = manager.refresh(phase, updates=update, phase=phase)
        else:
            resident = manager.resident()
        current = tuple(block.block_id for block in resident)
        replacements += int(current != before)
        before = current
        try:
            manager.require(phase, expected_revision=revision)
        except ContextFault:
            faults += 1
        else:
            hits += 1
        snapshots.append({"phase": phase, "revision": revision, "resident_ids": list(current)})
    return {"mode": mode, "phase_hit_rate": hits / len(EVENTS), "cold_faults": faults,
            "replacement_count": replacements, "revision_updates": revisions,
            "max_nonpinned_resident": max(sum(not b.pinned for b in manager.resident()) for _ in [0]),
            "snapshots": snapshots}


def run_suite() -> dict:
    rows = [_run(mode) for mode in ("static", "refresh", "refresh_hysteresis")]
    return {"experiment": "context-realtime-refresh-4-events", "config": {"events": EVENTS, "max_working": 2},
            "rows": rows,
            "limitations": ["Synthetic phase stream, not a live Jev latency result.",
                            "Lexical candidate scoring is a baseline; no vector/RAG retriever.",
                            "Runtime refresh does not claim Jev backend cache behavior."]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run_suite()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["rows"], ensure_ascii=False))


if __name__ == "__main__":
    main()
