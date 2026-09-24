"""Real file writes driven by selected evidence and optional live Jev decisions.

Fixtures and enum proposals are synthetic; Jev controls memory rank/count,
parameter choice and final commit. The scorer is only used after each run.
No GPU, model weights, arbitrary commands or external side effects are used.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jev_agent.arguments import ArgumentField, ArgumentInput, ValueProposal
from jev_agent.context_residency import ContextBlock, ContextResidencyManager
from jev_agent.grounded import GroundedArgumentAgent
from jev_agent.jev_client import TypeSafeJevChooser
from jev_agent.memory_recovery import RawEvidenceFallback
from jev_agent.memory_selection import TwoStageMemorySelector
from jev_agent.models import ChoiceResult, TaskState
from jev_agent.paged_memory import MemoryPage, PagedMemoryIndex
from jev_tools import build_local_catalog


class RecordingChooser:
    def __init__(self, delegate, limit=18):
        self.delegate, self.limit = delegate, limit
        self.calls = []

    def choose(self, *, state, instructions, options):
        if len(self.calls) >= self.limit:
            raise RuntimeError("benchmark call limit")
        row = {"option_ids": [o.option_id for o in options], "state_bytes": len(state.encode("utf-8"))}
        self.calls.append(row)
        started = perf_counter()
        try:
            decision = self.delegate.choose(state=state, instructions=instructions, options=options)
        except Exception as error:
            row["error_type"] = type(error).__name__
            # TypeSafe adapter's HTTP status is safe; never serialize arbitrary
            # provider text, request headers, or credentials.
            match = re.search(r"HTTP (\d{3})", str(error))
            if match:
                row["http_status"] = int(match[1])
            raise
        else:
            row.update({"choice": decision.choice, "probabilities": decision.probabilities,
                        "model": decision.model, "input_tokens": decision.input_tokens,
                        "output_tokens": decision.output_tokens})
            return decision
        finally:
            row["latency_ms"] = round((perf_counter() - started) * 1000, 3)


class ReplayChooser:
    """Transparent fixture replay, not Jev-quality evidence."""
    def __init__(self):
        self.value = ""

    def choose(self, *, state, instructions, options):
        ids = {o.option_id for o in options}
        if "PAGE_000" in ids:
            chosen = "PAGE_000"
        elif "TOP_2" in ids:
            chosen = "TOP_2"
        elif any(i.startswith("VALUE_") for i in ids):
            chosen = next(o.option_id for o in options if getattr(o.payload, "value", None) == self.value)
        else:
            chosen = next(o.option_id for o in options if o.payload is not None)
        return ChoiceResult(chosen, {o.option_id: float(o.option_id == chosen) for o in options}, 1, "fixture-replay")


def coverage(pages, *, revision):
    """Validate public entity/revision/provenance; never compare route values."""
    return any(p.revision == revision and "authoritative" in p.tags and
               f"entity=Atlas; version={revision};" in p.content for p in pages)


def run_suite(backend, *, output: Path, seed=23, label="replay"):
    output.parent.mkdir(parents=True, exist_ok=True)
    output = output.resolve()
    recorder = RecordingChooser(backend)
    index = PagedMemoryIndex()
    contexts = ContextResidencyManager(max_working=1)
    contexts.register(ContextBlock("policy", "Copy the route from the current authoritative approval. "
        "Ignore historical and unrelated records. Do not invent missing approvals.",
        "policy://record-route", kind="constraint", pinned=True))
    rows = []
    index.upsert(MemoryPage("p-42", "Atlas release historical approval, version 1", 
        "entity=Atlas; version=1; route=hold; source=historical", tags=("historical",)))
    index.upsert(MemoryPage("p-17", "Atlas budget for another department", "budget=500"))
    state = TaskState("grounded", "Record approved route")
    with TemporaryDirectory(prefix="grounded-", dir=output.parent) as temp:
        workspace = Path(temp)
        catalog = build_local_catalog(workspace=workspace)
        for step, (revision, expected) in enumerate(((1, "canary"), (2, "stable"), (3, None))):
            # These are environment events, not answers supplied to the model.
            # The evaluator retains expected solely to score the output file.
            if expected is not None:
                index.upsert(MemoryPage("p-91", f"Atlas current authoritative approval version {revision}",
                    f"entity=Atlas; version={revision}; route={expected}; source=approval-service",
                    revision=revision, tags=("authoritative",)))
            query = f"Atlas release approval version {revision}"
            filename = f"route-{revision}.txt"
            state.revise("approval", f"approval version {revision} requested")
            state.goal = (f"Record only the approved route for Atlas version {revision} in {filename}. "
                          "Use selected current authoritative evidence. If unavailable, request lookup.")
            if isinstance(backend, ReplayChooser):
                backend.value = expected or ""
            values = ["canary", "hold", "stable"]
            random.Random(seed + step).shuffle(values)
            inputs = ArgumentInput(chooser_factory=lambda _: recorder,
                proposer=lambda _: [ValueProposal(v, source="schema-enum") for v in values],
                parallel_fields=1, proposal_rounds=1, time_budget_seconds=90)
            runner = GroundedArgumentAgent(chooser=recorder, arguments=inputs,
                memory_index=index, selector=TwoStageMemorySelector(recorder, max_pages=2), contexts=contexts)
            start_call = len(recorder.calls)
            started = perf_counter()
            try:
                result = runner.run(state=state, tool=catalog.get("file.write").as_tool_definition(),
                    fields=[ArgumentField("text")], base_arguments={"path": filename}, query=query,
                    required_context={"phase": revision}, updates=[ContextBlock(
                        "phase", f"Atlas current requested approval version {revision}",
                        f"approval://Atlas/{revision}", revision=revision, kind="task_state")],
                    evidence_check=lambda pages: coverage(pages, revision=revision),
                    # Provenance marker distinguishes the current approval from
                    # a historical page that repeats the same entity/version.
                    recovery=RawEvidenceFallback(required_markers=(
                        f"entity=Atlas; version={revision};", "source=approval-service")))
                row = {"status": result.status, "reason": result.reason, "events": result.events,
                       "recovery_status": result.recovery_status, "evidence_ids": result.evidence_ids,
                       "evidence_bytes": result.evidence_bytes, "context_bytes": result.context_bytes}
            except Exception as error:
                row = {"status": "provider_error", "error_type": type(error).__name__}
            actual = (workspace / filename).read_text(encoding="utf-8") if (workspace / filename).exists() else None
            expected_ok = (actual == expected) if expected is not None else (
                actual is None and row["status"] in {"evidence_blocked", "memory_blocked"})
            row.update({"step": step, "required_revision": revision,
                        "case": "current" if expected is not None else "missing",
                        "file_written": actual is not None, "actual": actual, "expected": expected,
                        "correct": expected_ok,
                        "choice_calls": len(recorder.calls) - start_call,
                        "elapsed_ms": round((perf_counter() - started) * 1000, 3)})
            rows.append(row)
            report = {"experiment": "grounded-file-agent-v1", "backend": label,
                "seed": seed, "rows": rows, "calls": recorder.calls,
                "limits": {"max_calls": recorder.limit, "working_blocks": 1, "evidence_pages": 4},
                "limitations": ["3 synthetic environment events; not a general natural-language planner.",
                    "Finite enum proposals; no Qwen, token REFINE or tool-space PAGE in this experiment.",
                    "Missing-version contract supplied by the environment; no learned fault detector."]}
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps({k: row[k] for k in ("step", "status", "correct", "choice_calls")}), flush=True)
            # Don't spend further calls on a failing transport/credential.
            if any("error_type" in c for c in recorder.calls[start_call:]):
                break
    report["summary"] = {"completed_events": len(rows), "planned_events": 3,
        "correct_events": sum(r["correct"] for r in rows),
        "current_file_correct": sum(r["correct"] for r in rows if r["case"] == "current"),
        "current_file_cases": sum(r["case"] == "current" for r in rows),
        "missing_evidence_writes": sum(r["file_written"] for r in rows if r["case"] == "missing"),
        "model_calls": len(recorder.calls),
        "model_ms": round(sum(c["latency_ms"] for c in recorder.calls), 3)}
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--key-stdin", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    backend = TypeSafeJevChooser(api_key=sys.stdin.readline().strip() if args.key_stdin else None,
                                timeout_seconds=30) if args.live else ReplayChooser()
    report = run_suite(backend, output=args.output, label="typesafe-live" if args.live else "fixture-replay")
    print(json.dumps(report["summary"]), flush=True)


if __name__ == "__main__":
    main()
