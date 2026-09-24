"""Small live-Jev value check for ContextRefreshCoordinator.

The expected target block is evaluator-only metadata and never appears in the
query, prompt, options, or verifier.  This is a semantic smoke test, not a
general Jev accuracy estimate.  The script reads a key from stdin only when
``--key-stdin`` is supplied and writes no credentials to the report.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import threading
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jev_agent.context_refresh import ContextRefreshCoordinator, JevContextVerifier
from jev_agent.context_residency import ContextBlock, ContextFault, ContextResidencyManager
from jev_agent.jev_client import TypeSafeJevChooser


CASES = (
    {
        "name": "missing_current_deploy",
        "query": "What is the current Atlas production rollout plan?",
        "initial_query": "unrelated historical note",
        "target": "b17",
    },
    {
        "name": "missing_rollback",
        "query": "Which rollback plan should be used after a failed Atlas deployment?",
        "initial_query": "unrelated historical note",
        "target": "b63",
    },
    {
        "name": "missing_audit_evidence",
        "query": "Find the current approval evidence needed for the Atlas audit.",
        "initial_query": "unrelated historical note",
        "target": "b88",
    },
    {
        "name": "already_resident",
        "query": "Use the current Atlas production rollout plan.",
        "initial_query": "Use the current Atlas production rollout plan.",
        "target": "b17",
    },
    {
        "name": "ambiguous_atlas_plan",
        "query": "Which Atlas plan should be used?",
        "initial_query": "unrelated historical note",
        "target": None,
    },
)


class RecordingChooser:
    def __init__(self, delegate, *, max_calls: int = 32):
        self.delegate = delegate
        self.max_calls = max_calls
        self.calls: list[dict] = []
        self._lock = threading.Lock()

    def choose(self, *, state, instructions, options):
        with self._lock:
            if len(self.calls) >= self.max_calls:
                raise RuntimeError("live call budget exhausted")
            row = {"option_ids": [option.option_id for option in options],
                   "state_bytes": len(state.encode("utf-8"))}
            self.calls.append(row)
        started = perf_counter()
        try:
            result = self.delegate.choose(state=state, instructions=instructions, options=options)
        except Exception as error:
            with self._lock:
                row.update({"error_type": type(error).__name__,
                            "http_status": int(re.search(r"HTTP (\d{3})", str(error))[1])
                            if re.search(r"HTTP (\d{3})", str(error)) else None})
            raise
        else:
            with self._lock:
                row.update({"choice": result.choice, "confidence": result.confidence,
                            "probabilities": result.probabilities, "model": result.model,
                            "input_tokens": result.input_tokens, "output_tokens": result.output_tokens})
            return result
        finally:
            with self._lock:
                row["latency_ms"] = round((perf_counter() - started) * 1000, 3)


def build_manager() -> ContextResidencyManager:
    manager = ContextResidencyManager(max_working=1, hysteresis=0.05)
    manager.register(ContextBlock("goal", "Global safety and provenance constraints.",
                                  "raw://goal", kind="constraint", pinned=True))
    manager.register(ContextBlock(
        "b17",
        "Current Atlas production deployment rollout: canary then stable after approval.",
        "raw://deploy-current", phase="deploy", kind="task_state"))
    manager.register(ContextBlock(
        "b42",
        "Historical Atlas deployment rollout from a superseded release.",
        "raw://deploy-history", phase="deploy", kind="observation"))
    manager.register(ContextBlock(
        "b63",
        "Atlas rollback procedure: restore the last stable release after a failed deployment.",
        "raw://rollback", phase="rollback", kind="task_state"))
    manager.register(ContextBlock(
        "b88",
        "Current Atlas approval evidence and provenance for the production audit.",
        "raw://audit-current", phase="audit", kind="task_state"))
    manager.register(ContextBlock(
        "b91",
        "Historical Atlas audit notes from a prior approval cycle.",
        "raw://audit-history", phase="audit", kind="observation"))
    manager.register(ContextBlock("b05", "Unrelated historical note about another project.",
                                  "raw://noise", kind="observation"))
    return manager


def resident_hit(manager: ContextResidencyManager, target: str) -> bool:
    if target is None:
        return False
    try:
        manager.require(target)
    except ContextFault:
        return False
    return True


def run(chooser: RecordingChooser, *, max_cases: int = 4) -> dict:
    rows = []
    for case in CASES[:max_cases]:
        baseline_manager = build_manager()
        baseline_manager.rebuild(case["initial_query"])
        baseline_hit = resident_hit(baseline_manager, case["target"])

        manager = build_manager()
        manager.rebuild(case["initial_query"])
        coordinator = ContextRefreshCoordinator(manager, max_verifiers=4,
                                                 max_refreshes_per_phase=4,
                                                 cooldown_steps=0, max_workers=4)
        started = perf_counter()
        result = coordinator.refresh(
            case["query"], phase=case["name"], verifier=JevContextVerifier(chooser),
            top_m=4, load_k=1, reason="controlled_context_fault",
        )
        elapsed_ms = round((perf_counter() - started) * 1000, 3)
        gold_in_directory = case["target"] is not None and case["target"] in result.candidate_ids
        rows.append({
            "case": case["name"],
            "status": result.status,
            "candidate_ids": list(result.candidate_ids),
            "selected_ids": list(result.selected_ids),
            "baseline_hit": baseline_hit,
            "refresh_hit": resident_hit(manager, case["target"]),
            "target_selected": case["target"] in result.selected_ids,
            "gold_in_directory": gold_in_directory,
            "false_refresh": case["target"] is None and bool(result.selected_ids),
            "no_evidence": any(item.reason == "NO_EVIDENCE" for item in result.verifications),
            "elapsed_ms": elapsed_ms,
            "stage_ms": result.stage_ms,
            "verifications": [{"block_id": item.block_id, "supported": item.supported,
                                "confidence": item.confidence, "reason": item.reason}
                               for item in result.verifications],
        })
    return {"experiment": "live-context-refresh-value-smoke",
            "backend": "typesafe-live",
            "config": {"top_m": 4, "load_k": 1, "max_workers": 4,
                       "cases": len(rows), "target_ids_are_evaluator_only": True},
            "rows": rows,
            "summary": {
                "baseline_hits": sum(row["baseline_hit"] for row in rows),
                "refresh_hits": sum(row["refresh_hit"] for row in rows),
                "target_selected": sum(row["target_selected"] for row in rows),
                "directory_hits": sum(row["gold_in_directory"] for row in rows),
                "false_refreshes": sum(row["false_refresh"] for row in rows),
                "no_evidence_results": sum(row["no_evidence"] for row in rows),
                "committed": sum(row["status"] == "committed" for row in rows),
                "no_gain": sum(row["status"] == "no_gain" for row in rows),
                "model_calls": len(chooser.calls),
                "model_latency_ms": round(sum(row.get("latency_ms", 0) for row in chooser.calls), 3),
            },
            "calls": chooser.calls,
            "limitations": [
                "Five controlled cases are a semantic smoke test, not a general Jev accuracy estimate.",
                "The lexical directory already limits candidates; this does not measure missed-directory recall.",
                "Summary-only block verification does not establish raw evidence correctness.",
                "Jev probabilities are reported as returned and are not calibration results.",
            ]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--key-stdin", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-cases", type=int, default=4)
    args = parser.parse_args()
    key = sys.stdin.readline().strip() if args.key_stdin else None
    chooser = RecordingChooser(TypeSafeJevChooser(api_key=key, timeout_seconds=30), max_calls=32)
    report = run(chooser, max_cases=args.max_cases)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
