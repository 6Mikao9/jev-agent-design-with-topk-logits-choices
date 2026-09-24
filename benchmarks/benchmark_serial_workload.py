"""Small serial A/B/C workload that composes the runtime primitives."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jev_agent.agent import Agent, ToolDefinition
from jev_agent.arguments import ArgumentField, ArgumentInput, ValueProposal
from jev_agent.context_residency import ContextBlock, ContextFault, ContextResidencyManager
from jev_agent.memory_recovery import RawEvidenceFallback
from jev_agent.memory_selection import TwoStageMemorySelector
from jev_agent.models import ChoiceResult, TaskState
from jev_agent.paged_memory import MemoryPage, PagedMemoryIndex

from benchmarks.benchmark_memory_p0 import SummaryChooser


STEPS = (("deploy", 1, False), ("rollback", 1, True), ("audit", 1, False), ("deploy", 2, False))


class ScriptedChooser:
    def __init__(self, *choices: str):
        self.choices = iter(choices)

    def choose(self, *, state, instructions, options):
        choice = next(self.choices)
        if choice not in {option.option_id for option in options}:
            raise AssertionError(f"choice {choice} not offered")
        return ChoiceResult(choice, {option.option_id: float(option.option_id == choice) for option in options},
                            1.0, "serial-script")


def _add_memory(index: PagedMemoryIndex, *, step: int, phase: str, revision: int, conflict: bool) -> tuple[str, str | None, str]:
    token = f"step-{step}-{phase}"
    # Stable logical page ID lets the final deploy event exercise revision
    # replacement instead of creating an unrelated duplicate page.
    target = f"primary-{phase}"
    contradiction = f"history-{token}" if conflict else None
    if conflict:
        index.upsert(MemoryPage(contradiction, f"phase {phase} historical conflict",  # type: ignore[arg-type]
                                f"source=historical-record {token}; approved=no", revision=1))
    index.upsert(MemoryPage(target, f"phase {phase} current state revision {revision}",
                            f"source=primary-record {token}; approved=yes", revision=revision))
    query = f"phase {phase} current" + (" compare conflict" if conflict else "")
    return target, contradiction, query


def run_workload() -> dict:
    index = PagedMemoryIndex(max_pages=64)
    selector = None
    context = ContextResidencyManager(max_working=1, hysteresis=0.05)
    context.register(ContextBlock("goal", "global safety constraint", "raw://goal",
                                  kind="constraint", pinned=True))
    tool_calls: list[dict] = []
    tool = ToolDefinition(
        "state.record", "record a validated phase state", "v1",
        {"type": "object", "properties": {"text": {"type": "string", "minLength": 1}},
         "required": ["text"], "additionalProperties": False},
        lambda arguments: tool_calls.append(arguments),
    )
    rows = []
    previous_resident: tuple[str, ...] = ()
    for step, (phase, revision, conflict) in enumerate(STEPS):
        target, contradiction, query = _add_memory(index, step=step, phase=phase,
                                                    revision=revision, conflict=conflict)
        if revision == 1:
            block = ContextBlock(phase, f"{phase} current working state", f"raw://{phase}",
                                 revision=revision, phase=phase)
        else:
            block = ContextBlock(phase, f"{phase} current working state revised", f"raw://{phase}-v2",
                                 revision=revision, phase=phase)
        resident = context.refresh(phase, updates=(block,), phase=phase)
        resident_ids = tuple(item.block_id for item in resident)
        context_hit = True
        try:
            context.require(phase, expected_revision=revision)
        except ContextFault:
            context_hit = False

        # Memory stage: summary choice first; only conflict invokes bounded raw fallback.
        chooser = SummaryChooser(query)
        selector = TwoStageMemorySelector(chooser, max_candidates=16, max_pages=2,
                                          max_read_bytes=16_384, max_page_bytes=8_192)
        initial = selector.retrieve(index, context=query)
        recovery = None
        if conflict:
            recovery = RawEvidenceFallback(
                required_markers=(f"source=primary-record step-{step}-{phase}",),
                max_candidates=8, max_pages=2, max_read_bytes=16_384,
                max_page_bytes=8_192, max_scan_bytes=65_536, retrieval="hybrid",
            ).recover(index, context=query, initial=initial)
            pages = recovery.pages
            memory_status = recovery.status
        else:
            pages = initial.pages
            memory_status = initial.status
        selected_ids = {page.page_id for page in pages}
        memory_ok = target in selected_ids and (not conflict or contradiction in selected_ids)

        # Argument stage: a validated candidate must be explicitly committed.
        state = TaskState(f"serial-{step}", f"record {phase} state")
        argument = ArgumentInput(
            chooser_factory=lambda _: ScriptedChooser("VALUE_0"),
            proposer=lambda _: [ValueProposal(f"{phase}:revision={revision}")],
        ).build(state=state, tool=tool, fields=[ArgumentField("text")])
        committed = None
        if argument.candidate is not None:
            committed = Agent(ScriptedChooser(argument.candidate.candidate_id)).run(
                state=state, tool=tool, drafts=[argument.candidate]
            )
        rows.append({
            "step": step, "phase": phase, "revision": revision, "conflict": conflict,
            "context_hit": context_hit, "resident_ids": list(resident_ids),
            "resident_replaced": resident_ids != previous_resident,
            "memory_initial_status": initial.status, "memory_status": memory_status,
            "memory_selected_ids": sorted(selected_ids), "memory_ok": memory_ok,
            "argument_status": argument.status,
            "tool_status": committed.status if committed else "not_attempted",
        })
        previous_resident = resident_ids
    return {
        "experiment": "serial-a-b-c-workload-4-steps", "steps": rows,
        "summary": {
            "steps": len(rows), "context_hit_rate": sum(row["context_hit"] for row in rows) / len(rows),
            "memory_ok_rate": sum(row["memory_ok"] for row in rows) / len(rows),
            "argument_ready_rate": sum(row["argument_status"] == "ready" for row in rows) / len(rows),
            "tool_commit_rate": sum(row["tool_status"] == "executed" for row in rows) / len(rows),
            "tool_calls": len(tool_calls),
            "resident_bound_ok": all(len([x for x in row["resident_ids"] if x != "goal"]) <= 1 for row in rows),
        },
        "limitations": ["Scripted chooser/helper proxy, not live Jev quality.",
                        "Four-step synthetic trajectory; no network latency or tool failure injection.",
                        "Memory evidence marker is a verifier contract, not a Jev probability."]
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run_workload()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
