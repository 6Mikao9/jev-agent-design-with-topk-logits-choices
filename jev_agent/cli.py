"""Small, explicit REPL for the Jev tool-agent prototype.

Start with ``python -m jev_agent.cli --workspace PATH``.  Natural language is
recorded as a goal only; side effects require ``:plan`` followed by ``:approve``.
Use ``--live`` to replace the scripted chooser with TypeSafe Jev.  This is a
workspace-local prototype, not a general computer-use shell.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
from typing import Any

from .agent import Agent, ToolDefinition
from .arguments import ArgumentField, ArgumentInput, ValueProposal
from .jev_client import TypeSafeJevChooser
from .models import ChoiceBackend, ChoiceOption, ChoiceResult, Candidate, TaskState
from jev_tools import ToolCatalog, build_local_catalog


class ScriptedChooser(ChoiceBackend):
    """Deterministic local chooser; it never pretends to be Jev."""

    def choose(self, *, state: str, instructions: str, options: list[ChoiceOption]) -> ChoiceResult:
        preferred = next((o for o in options if o.option_id.startswith("VALUE_")), None)
        preferred = preferred or next((o for o in options if o.payload is not None), None) or options[0]
        return ChoiceResult(preferred.option_id, {preferred.option_id: 1.0}, 1.0, "scripted-cli")


def parse_plan_line(line: str) -> tuple[str, dict[str, Any]]:
    """Parse ``:plan tool.name {json}`` without evaluating arbitrary text."""
    prefix, _, raw = line.partition(" ")
    if prefix != ":plan" or not raw.strip():
        raise ValueError("usage: :plan <tool.name> <JSON arguments>")
    tool, _, encoded = raw.strip().partition(" ")
    if not tool or not encoded.strip():
        raise ValueError("usage: :plan <tool.name> <JSON arguments>")
    value = json.loads(encoded)
    if not isinstance(value, dict):
        raise ValueError("tool arguments must be a JSON object")
    return tool, value


def summarize_result(value: Any) -> dict[str, Any]:
    """Keep trace files structural and avoid copying arbitrary command output."""
    if isinstance(value, dict):
        summary: dict[str, Any] = {"keys": sorted(value)}
        for key in ("status", "path", "bytes", "bytes_written", "returncode", "stdout_bytes", "stderr_bytes",
                    "stdout_truncated", "stderr_truncated", "timed_out", "replacements"):
            if key in value:
                summary[key] = value[key]
        if isinstance(value.get("entries"), list):
            summary["entry_count"] = len(value["entries"])
        if isinstance(value.get("matches"), list):
            summary["match_count"] = len(value["matches"])
        return summary
    return {"type": type(value).__name__}


def _make_proposer(arguments: dict[str, Any]):
    def propose(context):
        if context.name not in arguments:
            return []
        return [ValueProposal(arguments[context.name], source="user-plan")]
    return propose


class InteractiveAgent:
    def __init__(self, *, workspace: Path, catalog: ToolCatalog, chooser: ChoiceBackend) -> None:
        self.workspace = workspace
        self.catalog = catalog
        self.chooser = chooser
        self.state = TaskState("interactive", "No task has been assigned yet")
        self.pending: Candidate | None = None
        self.pending_tool: ToolDefinition | None = None
        self.trace: list[dict[str, Any]] = []
        self.trace_path = workspace / ".jev_trace.json"

    def _save(self) -> None:
        self.trace_path.write_text(json.dumps({"task_revision": self.state.revision,
            "events": self.trace}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def tools_text(self) -> str:
        return "\n".join(f"{s.name}: {s.description} [{s.safety}]"
                         for s in self.catalog.specs() if s.available)

    def plan(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        spec = self.catalog.get(tool_name)
        if not spec.available:
            raise PermissionError(f"tool is unavailable: {tool_name}")
        tool = spec.as_tool_definition()
        fields = [ArgumentField(name) for name in arguments]
        prepared = ArgumentInput(
            chooser_factory=lambda _field: self.chooser,
            proposer=_make_proposer(arguments),
            parallel_fields=2,
            max_choice_calls=32,
            time_budget_seconds=60,
        ).build(state=self.state, tool=tool, fields=fields)
        self.pending = prepared.candidate if prepared.status == "ready" else None
        self.pending_tool = tool if self.pending is not None else None
        event = {"event": "plan", "tool": tool_name, "status": prepared.status,
                 "choice_calls": prepared.choice_calls, "reason": prepared.reason,
                 "candidate": summarize_result(prepared.candidate.arguments) if prepared.candidate else None}
        self.trace.append(event)
        self._save()
        return event

    def approve(self) -> dict[str, Any]:
        if self.pending is None or self.pending_tool is None:
            raise RuntimeError("no prepared candidate; use :plan first")
        result = Agent(self.chooser).run(state=self.state, tool=self.pending_tool, drafts=[self.pending])
        tool_status = result.tool_result.get("status") if isinstance(result.tool_result, dict) else None
        status = ("review_required" if tool_status == "review_required" else
                  "stopped" if tool_status == "stopped" else result.status)
        event = {"event": "approve", "tool": self.pending_tool.name, "status": status,
                 "choice_calls": result.choice_calls, "recovery": result.recovery,
                 "result": summarize_result(result.tool_result) if result.tool_result is not None else None}
        self.trace.append(event)
        if result.status == "executed" and status == "executed":
            self.state.revise(f"tool:{self.pending_tool.name}", json.dumps(summarize_result(result.tool_result), sort_keys=True))
            self.pending = None
            self.pending_tool = None
        self._save()
        return event

    def stop(self) -> dict[str, Any]:
        self.pending, self.pending_tool = None, None
        event = {"event": "stop", "status": "stopped"}
        self.trace.append(event)
        self._save()
        return event


def repl(agent: InteractiveAgent, *, input_stream=sys.stdin, output_stream=sys.stdout) -> None:
    print("Jev agent prototype. :help for commands; side effects require :approve.", file=output_stream)
    for raw in input_stream:
        line = raw.strip()
        if not line:
            continue
        try:
            if line in {":quit", ":exit"}:
                print(json.dumps({"event": "quit", "status": "stopped"}, ensure_ascii=False), file=output_stream)
                return
            if line == ":help":
                print(":tools | :goal TEXT | :plan TOOL JSON | :approve | :stop | :trace | :quit", file=output_stream)
            elif line == ":tools":
                print(agent.tools_text(), file=output_stream)
            elif line.startswith(":goal "):
                goal = line[6:].strip()
                if not goal:
                    raise ValueError("goal must not be empty")
                agent.state.revise("user_goal", goal)
                agent.state.goal = goal
                agent.trace.append({"event": "goal", "status": "recorded", "revision": agent.state.revision})
                agent._save()
                print(json.dumps({"event": "goal", "status": "recorded", "revision": agent.state.revision}, ensure_ascii=False), file=output_stream)
            elif line.startswith(":plan"):
                tool, arguments = parse_plan_line(line)
                print(json.dumps(agent.plan(tool, arguments), ensure_ascii=False), file=output_stream)
            elif line == ":approve":
                print(json.dumps(agent.approve(), ensure_ascii=False), file=output_stream)
            elif line == ":stop":
                print(json.dumps(agent.stop(), ensure_ascii=False), file=output_stream)
            elif line == ":trace":
                print(json.dumps({"trace": str(agent.trace_path), "events": agent.trace}, ensure_ascii=False), file=output_stream)
            else:
                agent.state.observations.append(line)
                agent.trace.append({"event": "observation", "status": "recorded"})
                agent._save()
                print(json.dumps({"event": "observation", "status": "recorded",
                                  "message": "已记录。请用 :plan 明确工具和 JSON 参数。"}, ensure_ascii=False), file=output_stream)
        except Exception as exc:
            print(json.dumps({"event": "error", "status": type(exc).__name__, "message": str(exc)}, ensure_ascii=False), file=output_stream)
        output_stream.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description="Jev tool-agent interactive prototype")
    parser.add_argument("--workspace", type=Path, default=Path("agent_workspace"))
    parser.add_argument("--live", action="store_true", help="use TypeSafe Jev instead of scripted chooser")
    parser.add_argument("--key-stdin", action="store_true", help="read a live API key from stdin before the REPL")
    parser.add_argument("--allow-command", action="append", default=None,
                        help="explicit executable basename; repeat to add. Default: git only.")
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    if not workspace.is_dir():
        raise SystemExit("workspace must be a directory")
    allowed = tuple(args.allow_command or ("git",))
    catalog = build_local_catalog(workspace, allowed_commands=allowed)
    key = sys.stdin.readline().strip() if args.live and args.key_stdin else None
    chooser: ChoiceBackend = TypeSafeJevChooser(api_key=key, timeout_seconds=30) if args.live else ScriptedChooser()
    repl(InteractiveAgent(workspace=workspace, catalog=catalog, chooser=chooser))


if __name__ == "__main__":
    main()
