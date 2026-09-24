"""Measure raw context loading after summary-level selection.

This is a deterministic C-path benchmark: it demonstrates that a selected
block can recover an omitted marker from its bounded raw body, while stale and
oversized bodies are rejected.  It does not call Jev.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jev_agent.context_materialization import ContextMaterializer
from jev_agent.context_residency import ContextBlock


CASES = (
    ("audit_marker_omitted", ContextBlock("b17", "Current Atlas approval is available.",
                                           "raw://audit", revision=3),
     ("source=approval-service", "version=3"), "raw://audit"),
    ("negation_omitted", ContextBlock("b42", "Atlas deployment policy.",
                                       "raw://policy", revision=2),
     ("forbidden=false",), "raw://policy"),
    ("stale_revision", ContextBlock("b63", "Rollback plan.", "raw://rollback", revision=1),
     ("version=2",), "raw://rollback"),
    ("oversized_body", ContextBlock("b88", "Large trace summary.", "raw://large", revision=1),
     ("needle",), "raw://large"),
)


def run() -> dict:
    bodies = {
        "raw://audit": "entity=Atlas; version=3; source=approval-service; route=stable",
        "raw://policy": "entity=Atlas; forbidden=false; applies=current-release",
        "raw://rollback": "entity=Atlas; version=2; route=restore-stable",
        "raw://large": "x" * 1024,
    }
    rows = []
    for name, block, markers, ref in CASES:
        started = perf_counter()
        if name == "stale_revision":
            expected_revision = 2
            materializer = ContextMaterializer(bodies, max_bytes=128)
        elif name == "oversized_body":
            expected_revision = 1
            materializer = ContextMaterializer(bodies, max_bytes=32)
        else:
            expected_revision = block.revision
            materializer = ContextMaterializer(bodies, max_bytes=128)
        try:
            body = materializer.materialize(block, expected_revision=expected_revision)
        except Exception as error:
            rows.append({"case": name, "status": type(error).__name__,
                         "markers_found": [], "elapsed_ms": round((perf_counter() - started) * 1000, 3)})
            continue
        found = [marker for marker in markers if marker in body.content]
        rows.append({"case": name, "status": "materialized", "markers_found": found,
                     "sha256": body.sha256, "bytes": body.byte_count,
                     "elapsed_ms": round((perf_counter() - started) * 1000, 3)})
    return {
        "experiment": "context-raw-materialization-contract",
        "rows": rows,
        "summary": {
            "materialized": sum(row["status"] == "materialized" for row in rows),
            "marker_cases": sum(bool(row.get("markers_found")) for row in rows),
            "stale_or_budget_rejected": sum(row["status"] in {"StaleContextMaterialization", "ContextMaterializationBudgetExceeded"} for row in rows),
        },
        "limitations": [
            "Local mapping source only; no external filesystem or Jev call.",
            "Evidence markers are deterministic contracts, not semantic verification.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
