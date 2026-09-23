from __future__ import annotations

import json
import ast
import argparse
from pathlib import Path
from statistics import mean

from jev_agent.agent import Agent, ToolDefinition
from jev_agent.models import Candidate, ChoiceOption, ChoiceResult, TaskState
from jev_agent.topk import LogitsState, TokenProposal, TopKBuilder
from jev_agent.validation import validate_json_schema


ROOT = Path(__file__).resolve().parent
SCENARIOS = json.loads((ROOT / "scenarios.json").read_text(encoding="utf-8"))


class OracleChooser:
    """Scripted controller; knows labels solely to test routing and mechanics."""

    def __init__(self, gold: str, *, facts_available: bool, always_topk: bool = False) -> None:
        self.gold = gold
        self.facts_available = facts_available
        self.always_topk = always_topk

    def choose(self, *, state: str, instructions: str, options: list[ChoiceOption]) -> ChoiceResult:
        by_id = {option.option_id: option for option in options}
        if "Current exact prefix: " in state:
            current_prefix = ast.literal_eval(state.split("Current exact prefix: ", 1)[1])
        else:
            current_prefix = None
        exact_draft = next(
            (
                option
                for option in options
                if isinstance(option.payload, Candidate)
                and option.payload.arguments.get("query") == self.gold
            ),
            None,
        )
        if "Current exact prefix: " in state and not self.facts_available and "CLARIFY" in by_id:
            selected = "CLARIFY"
        elif current_prefix == self.gold and "FINISH" in by_id:
            selected = "FINISH"
        elif exact_draft is not None:
            selected = exact_draft.option_id
        else:
            selected = ""
            for option in options:
                payload = option.payload
                if isinstance(payload, TokenProposal):
                    prefix = current_prefix or ""
                    if self.gold.startswith(prefix + payload.text) and payload.text:
                        selected = option.option_id
                        break
            if not selected:
                if "EXPAND_K" in by_id:
                    selected = "EXPAND_K"
                elif "FALLBACK_TOPK" in by_id and self.facts_available:
                    selected = "FALLBACK_TOPK"
                elif "CLARIFY" in by_id:
                    selected = "CLARIFY"
                elif "STOP_UNRESOLVED" in by_id:
                    selected = "STOP_UNRESOLVED"
            if not selected and self.always_topk and "FALLBACK_TOPK" in by_id:
                selected = "FALLBACK_TOPK"
        if not selected:
            selected = next(iter(by_id))
        return ChoiceResult(selected, {selected: 1.0}, 1.0, "scripted-oracle", latency_ms=0.1)


class GoldLogits:
    """Returns the gold next character at rank 2 to exercise EXPAND_K."""

    def __init__(self, gold: str) -> None:
        self.gold = gold

    def start(self, *, context: str, prefix: str) -> LogitsState:
        return LogitsState(prefix)

    def next_top_k(self, *, state: LogitsState, k: int) -> list[TokenProposal]:
        prefix = state.value
        if not self.gold.startswith(prefix):
            return []
        if len(prefix) == len(self.gold):
            return [TokenProposal(-1, "", 0.0, is_eos=True)]
        target = self.gold[len(prefix)]
        distractor = "~" if target != "~" else "^"
        ranked = [
            TokenProposal(ord(distractor), distractor, 2.0),
            TokenProposal(ord(target), target, 1.0),
        ]
        return ranked[: max(1, min(k, len(ranked)))]

    def append_token(self, *, state: LogitsState, token: TokenProposal) -> LogitsState:
        return LogitsState(state.value + token.text, state.token_ids + (token.token_id,))


def _run_one(scenario: dict, strategy: str) -> dict:
    state = TaskState(
        task_id=scenario["id"],
        goal=scenario["goal"],
        revision=2 if scenario.get("stale_drafts") else 1,
        dependency_versions=dict(scenario["dependencies"]),
    )
    chooser = OracleChooser(
        scenario["gold"],
        facts_available=scenario["facts_available"],
        always_topk=strategy == "always_topk",
    )
    helper = GoldLogits(scenario["gold"])
    topk = TopKBuilder(helper=helper, chooser=chooser, initial_k=1, max_k=2, max_tokens=128)
    schema = {
        "type": "object",
        "properties": {
            "service": {"type": "string", "enum": ["staging", "payments"]},
            "query": {"type": "string", "minLength": 1, "maxLength": 512},
            "time_range": {"type": "string", "enum": ["last_30_minutes"]},
        },
        "required": ["service", "query", "time_range"],
        "additionalProperties": False,
    }
    calls: list[dict] = []
    tool = ToolDefinition("search_logs", "Search service logs", "logs-v2", schema, lambda args: calls.append(args) or {"rows": 3})
    drafts = []
    for index, query in enumerate(scenario["drafts"]):
        if strategy == "explicit_topk" and query != scenario["gold"]:
            # The first choice must see the full drafts and recovery option;
            # the oracle will choose fallback if no exact proposal exists.
            pass
        drafts.append(
            Candidate(
                candidate_id=f"{scenario['id']}-draft-{index}",
                tool_name="search_logs",
                arguments={"service": "staging", "query": query, "time_range": "last_30_minutes"},
                source="fixture",
                task_revision=1 if scenario.get("stale_drafts") else state.revision,
                schema_version="logs-v2",
                dependency_versions=dict(scenario["dependencies"]),
            )
        )
    if strategy == "proposal_only":
        # This baseline cannot enter the construction path.
        class ProposalOnly(OracleChooser):
            def choose(self, *, state: str, instructions: str, options: list[ChoiceOption]) -> ChoiceResult:
                existing = next((item for item in options if item.payload and item.payload.arguments.get("query") == self.gold), None)
                if existing:
                    chosen = existing.option_id
                elif not self.facts_available and "CLARIFY" in {x.option_id for x in options}:
                    chosen = "CLARIFY"
                else:
                    chosen = "STOP_UNRESOLVED" if "STOP_UNRESOLVED" in {x.option_id for x in options} else options[-1].option_id
                return ChoiceResult(chosen, {chosen: 1.0}, 1.0, "scripted-proposal-only", latency_ms=0.1)
        chooser = ProposalOnly(scenario["gold"], facts_available=scenario["facts_available"])
        topk = None
    elif strategy == "always_topk":
        class AlwaysFallback(OracleChooser):
            def choose(self, *, state: str, instructions: str, options: list[ChoiceOption]) -> ChoiceResult:
                ids = {x.option_id for x in options}
                if "FALLBACK_TOPK" in ids:
                    chosen = "FALLBACK_TOPK"
                else:
                    chosen = super().choose(state=state, instructions=instructions, options=options).choice
                return ChoiceResult(chosen, {chosen: 1.0}, 1.0, "scripted-always-topk", latency_ms=0.1)
        chooser = AlwaysFallback(scenario["gold"], facts_available=scenario["facts_available"], always_topk=True)
        topk = TopKBuilder(helper=helper, chooser=chooser, initial_k=1, max_k=2, max_tokens=128)
    else:
        # Rebind the top-k chooser to the same deterministic controller.
        topk = TopKBuilder(helper=helper, chooser=chooser, initial_k=1, max_k=2, max_tokens=128)

    agent = Agent(chooser, topk=topk)
    result = agent.run(
        state=state,
        tool=tool,
        drafts=drafts,
        fallback_field=("query",),
        fallback_complete=lambda value: value == scenario["gold"],
        fallback_prefix="",
        base_arguments={"service": scenario.get("tool_service", "staging"), "time_range": "last_30_minutes"},
        helper=helper if strategy != "proposal_only" else None,
    )
    success = bool(calls) and calls[0]["query"] == scenario["gold"]
    if calls:
        validate_json_schema(calls[0], schema)
    return {
        "scenario": scenario["id"],
        "strategy": strategy,
        "gold_completed": success,
        "expected_action": "clarify" if not scenario["facts_available"] else "execute",
        "oracle_action_correct": (
            result.status == "clarification_required"
            if not scenario["facts_available"]
            else result.status == "executed"
        ),
        "status": result.status,
        "proposal_covered": scenario["gold"] in scenario["drafts"],
        "choice_calls": result.choice_calls,
        "helper_calls": result.helper_calls,
    }


def run() -> dict:
    rows = [
        _run_one(scenario, strategy)
        for scenario in SCENARIOS
        for strategy in ("proposal_only", "always_topk", "explicit_topk")
    ]
    summary = {}
    for strategy in ("proposal_only", "always_topk", "explicit_topk"):
        subset = [row for row in rows if row["strategy"] == strategy]
        summary[strategy] = {
            "tasks": len(subset),
            "oracle_gold_completion_rate": round(mean(row["gold_completed"] for row in subset), 4),
            "oracle_action_accuracy": round(mean(row["oracle_action_correct"] for row in subset), 4),
            "clarifications": sum(row["status"] == "clarification_required" for row in subset),
            "mean_choice_calls": round(mean(row["choice_calls"] for row in subset), 2),
            "mean_helper_calls": round(mean(row["helper_calls"] for row in subset), 2),
            "fallback_task_rate": round(mean(row["helper_calls"] > 0 for row in subset), 4),
        }
    return {
        "benchmark": "synthetic-control-flow-v1",
        "interpretation": "Scripted oracle only; not a live Jev/model quality benchmark.",
        "proposal_coverage": round(
            mean(row["proposal_covered"] for row in rows if row["strategy"] == "explicit_topk"), 4
        ),
        "summary": summary,
        "cases": rows,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the deterministic synthetic control-flow benchmark.")
    parser.add_argument("--output", type=Path, help="optional UTF-8 JSON result path")
    args = parser.parse_args()
    rendered = json.dumps(run(), ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
        print(f"Wrote {args.output}")
    else:
        print(rendered, end="")
