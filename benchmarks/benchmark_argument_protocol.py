"""Controlled argument-input protocol benchmark.

The cases exercise proposal acceptance, REFINE construction, REPROPOSE recovery,
parallel fields, and an evidence-required stop.  Tool execution is only counted
after an explicit Candidate selection by the outer Agent.
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

from jev_agent.agent import Agent, ToolDefinition
from jev_agent.arguments import ArgumentField, ArgumentInput, ValueProposal
from jev_agent.models import ChoiceResult, TaskState
from jev_agent.topk import LogitsState, TokenProposal


class ScriptedChooser:
    def __init__(self, *choices: str):
        self.choices = iter(choices)
        self.calls = 0

    def choose(self, *, state, instructions, options):
        choice = next(self.choices)
        if choice not in {option.option_id for option in options}:
            raise AssertionError(f"scripted choice {choice} not offered: {[o.option_id for o in options]}")
        self.calls += 1
        probabilities = {option.option_id: (1.0 if option.option_id == choice else 0.0) for option in options}
        return ChoiceResult(choice, probabilities, 1.0, "scripted-protocol")


class LetterHelper:
    def start(self, *, context, prefix):
        return LogitsState(prefix)

    def next_top_k(self, *, state, k):
        return [TokenProposal(1, "x", 1.0), TokenProposal(2, "y", 0.5)][:k]

    def append_token(self, *, state, token):
        return LogitsState(state.value + token.text, state.token_ids + (token.token_id,))


def _tool(calls: list[dict]) -> ToolDefinition:
    return ToolDefinition(
        "file.write", "write a bounded file", "v1",
        {"type": "object", "properties": {"text": {"type": "string", "minLength": 1}},
         "required": ["text"], "additionalProperties": False},
        lambda arguments: calls.append(arguments),
    )


def run_case(name: str) -> dict:
    calls: list[dict] = []
    tool = _tool(calls)
    state = TaskState(f"protocol-{name}", f"run {name}")
    proposer_calls = []

    def proposer(context):
        proposer_calls.append(context.attempt)
        if name == "repropose":
            return [ValueProposal("old" if context.attempt == 1 else "fresh")]
        if name == "missing_evidence":
            return [ValueProposal("guessed")]
        return [ValueProposal("proposal")]

    scripts = {
        "direct": ("VALUE_0",),
        "refine": ("REFINE", "token_1", "END_FIELD"),
        "repropose": ("REPROPOSE", "VALUE_0"),
        "missing_evidence": (),
    }
    chooser = ScriptedChooser(*scripts[name])
    input_result = ArgumentInput(
        chooser_factory=lambda _: chooser,
        proposer=proposer,
        helper_factory=lambda _: LetterHelper(),
        proposal_rounds=2,
        parallel_fields=2,
        max_choice_calls=16,
    ).build(
        state=state,
        tool=tool,
        fields=[ArgumentField("text", require_evidence=name == "missing_evidence")],
    )
    committed = None
    if input_result.candidate is not None:
        committed = Agent(ScriptedChooser(input_result.candidate.candidate_id)).run(
            state=state, tool=tool, drafts=[input_result.candidate]
        )
    return {
        "case": name,
        "input_status": input_result.status,
        "candidate_ready": input_result.candidate is not None,
        "commit_status": committed.status if committed else "not_attempted",
        "tool_calls": len(calls),
        "choice_calls": input_result.choice_calls,
        "helper_calls": input_result.fields["text"].helper_calls,
        "proposal_rounds": input_result.fields["text"].proposal_rounds,
        "proposer_attempts": proposer_calls,
        "reason": input_result.reason or input_result.fields["text"].reason,
    }


def run_suite() -> dict:
    started = perf_counter()
    rows = [run_case(name) for name in ("direct", "refine", "repropose", "missing_evidence")]
    return {
        "experiment": "argument-input-protocol-4-cases",
        "rows": rows,
        "summary": {
            "cases": len(rows),
            "ready_rate": sum(row["candidate_ready"] for row in rows) / len(rows),
            "commit_success_rate": sum(row["commit_status"] == "executed" for row in rows) / len(rows),
            "unsafe_tool_calls": sum(row["tool_calls"] for row in rows if row["case"] == "missing_evidence"),
            "elapsed_ms": round((perf_counter() - started) * 1000, 3),
        },
        "limitations": ["Scripted chooser/helper proxy, not live Jev quality or latency.",
                        "The benchmark checks protocol transitions and execution gating only."]
    }


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
