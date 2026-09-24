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
from uuid import uuid4
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
        self.workspace = workspace.resolve()
        self.catalog = catalog
        self.chooser = chooser
        self.state = TaskState("interactive", "No task has been assigned yet")
        self.pending: Candidate | None = None
        self.pending_tool: ToolDefinition | None = None
        self.trace: list[dict[str, Any]] = []
        self.backend = getattr(chooser, "model", "scripted-cli")
        trace_dir = self.workspace / ".jev_traces"
        if trace_dir.exists() and trace_dir.is_symlink():
            raise ValueError("trace directory must not be a symlink")
        trace_dir.mkdir(parents=True, exist_ok=True)
        self.trace_path = trace_dir / f"session-{uuid4().hex}.json"

    def clear_pending(self) -> None:
        self.pending, self.pending_tool = None, None

    def _record_revision(self, dependency_id: str, observation: str) -> None:
        self.clear_pending()
        self.state.revise(dependency_id, observation)

    def _save(self) -> None:
        if self.trace_path.is_symlink() or self.trace_path.parent.is_symlink():
            raise ValueError("trace path must not be a symlink")
        root = self.workspace.resolve()
        target = self.trace_path.resolve(strict=False)
        if target != root and root not in target.parents:
            raise ValueError("trace path resolves outside workspace")
        self.trace_path.write_text(json.dumps({"task_revision": self.state.revision,
            "events": self.trace}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def tools_text(self) -> str:
        return "\n".join(f"{s.name}: {s.description} [{s.safety}]"
                         for s in self.catalog.specs() if s.available)

    def plan(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        # A failed/unknown plan must never leave an older candidate approvable.
        self.clear_pending()
        spec = self.catalog.get(tool_name)
        if not spec.available:
            raise PermissionError(f"tool is unavailable: {tool_name}")
        tool = spec.as_tool_definition()
        fields = [ArgumentField(name) for name in arguments]
        prepared = ArgumentInput(
            chooser_factory=lambda _field: self.chooser,
            proposer=_make_proposer(arguments),
            parallel_fields=1,
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
        pending_tool = self.pending_tool
        try:
            result = Agent(self.chooser).run(state=self.state, tool=pending_tool, drafts=[self.pending])
        except Exception as exc:
            event = {"event": "approve", "tool": pending_tool.name,
                     "status": "provider_error", "choice_calls": 0,
                     "recovery": type(exc).__name__, "result": None}
            self.trace.append(event)
            self._save()
            return event
        finally:
            # Every attempt consumes the candidate, including failures and review/stop signals.
            self.clear_pending()
        tool_status = result.tool_result.get("status") if isinstance(result.tool_result, dict) else None
        status = ("review_required" if tool_status == "review_required" else
                  "stopped" if tool_status == "stopped" else result.status)
        event = {"event": "approve", "tool": pending_tool.name, "status": status,
                 "choice_calls": result.choice_calls, "recovery": result.recovery,
                 "result": summarize_result(result.tool_result) if result.tool_result is not None else None}
        self.trace.append(event)
        if result.status == "executed" and status == "executed":
            self.state.revise(f"tool:{pending_tool.name}", json.dumps(summarize_result(result.tool_result), sort_keys=True))
        self._save()
        return {**event, "display_result": bounded_result(result.tool_result) if result.tool_result is not None else None}

    def stop(self) -> dict[str, Any]:
        self.clear_pending()
        event = {"event": "stop", "status": "stopped"}
        self.trace.append(event)
        self._save()
        return event


def bounded_result(value: Any, max_bytes: int = 8192) -> str:
    """Render a complete result when small, otherwise a bounded readable prefix."""
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    suffix = "…[truncated]"
    room = max(0, max_bytes - len(suffix.encode("utf-8")))
    return encoded[:room].decode("utf-8", errors="ignore") + suffix


def repl(agent: InteractiveAgent, *, input_stream=sys.stdin, output_stream=sys.stdout) -> None:
    print(f"Jev agent prototype (backend={agent.backend}). Tools are workspace-local; {len([s for s in agent.catalog.specs() if s.available])} available. :help for commands.", file=output_stream)
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
                agent._record_revision("user_goal", goal)
                agent.state.goal = goal
                agent.trace.append({"event": "goal", "status": "recorded", "revision": agent.state.revision})
                agent._save()
                print(json.dumps({"event": "goal", "status": "recorded", "revision": agent.state.revision}, ensure_ascii=False), file=output_stream)
            elif line.startswith(":plan"):
                agent.clear_pending()
                tool, arguments = parse_plan_line(line)
                print(json.dumps(agent.plan(tool, arguments), ensure_ascii=False), file=output_stream)
            elif line == ":approve":
                print(json.dumps(agent.approve(), ensure_ascii=False), file=output_stream)
            elif line == ":stop":
                print(json.dumps(agent.stop(), ensure_ascii=False), file=output_stream)
            elif line == ":trace":
                print(json.dumps({"trace": str(agent.trace_path), "events": agent.trace}, ensure_ascii=False), file=output_stream)
            else:
                if line.startswith(":"):
                    raise ValueError(f"unknown command: {line.split()[0]}")
                agent._record_revision("user_observation", line)
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
