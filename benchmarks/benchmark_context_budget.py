"""Proxy benchmark for partitioned context-frame packing."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jev_agent.context_budget import ContextBudget, ContextBudgetController, ContextBudgetExceeded, ContextSlice


def run() -> dict:
    controller = ContextBudgetController(ContextBudget())
    packed = controller.pack((
        ContextSlice("pinned", "safety", "Never execute without current approval.", required=True),
        ContextSlice("recent", "event-1", "user changed release target", priority=2),
        ContextSlice("recent", "event-2", "old unrelated event", priority=0),
        ContextSlice("working", "deploy", "Current deployment plan and revision.", priority=2),
        ContextSlice("working", "history", "Long historical branch " + "x" * 7000, priority=0),
        ContextSlice("evidence", "approval", "source=approval-service; version=3", priority=3),
        ContextSlice("options", "file.write", "file.write(path,text)", priority=1),
        ContextSlice("trace", "fault-1", "previous evidence gap", priority=1),
    ))
    overflow_status = "not_attempted"
    try:
        controller.pack((ContextSlice("pinned", "too-large", "z" * 4000, required=True),))
    except ContextBudgetExceeded:
        overflow_status = "pinned_rejected"
    return {
        "experiment": "partitioned-context-budget-proxy",
        "budget": {"pinned": 3072, "recent": 4096, "working": 6144,
                    "evidence": 6144, "options": 3072, "trace": 2048,
                    "total": 24576},
        "usage": packed.usage,
        "dropped_ids": list(packed.dropped_ids),
        "total_bytes": packed.total_bytes,
        "overflow_status": overflow_status,
        "limitations": [
            "Deterministic packing only; no Jev quality or retrieval claim.",
            "Working/context selection happens before this packer; it does not learn utility.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"usage": report["usage"], "dropped_ids": report["dropped_ids"],
                      "overflow_status": report["overflow_status"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
