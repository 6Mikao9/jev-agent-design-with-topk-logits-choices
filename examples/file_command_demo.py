"""Project-local file/command vertical slice; stages are a fixed demonstration.

python -m examples.file_command_demo --workspace benchmarks/results/file-demo
Add --live for actual Jev decisions, --key-stdin to receive the API key via stdin.
This is not an autonomous-planning benchmark or a measured small-model result.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys

from jev_agent import Agent, ArgumentField, ArgumentInput, ChoiceResult, TaskState, ValueProposal
from jev_agent.jev_client import TypeSafeJevChooser
from jev_tools import build_local_catalog


class ScriptedChooser:
    def choose(self, *, state, instructions, options):
        option = next((o for o in options if o.option_id == "VALUE_0"), options[0])
        return ChoiceResult(option.option_id, {option.option_id: 1.0}, 1.0, "scripted-demo")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True,
                        help="A new, empty directory reserved for this demo")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--key-stdin", action="store_true")
    args = parser.parse_args()
    root = args.workspace.resolve()
    if root.exists() and any(root.iterdir()):
        raise SystemExit("Demo workspace must be empty; refusing to overwrite files")
    root.mkdir(parents=True, exist_ok=True)
    (root / "settings.txt").write_text("MODE = 'draft'\n", encoding="utf-8")
    (root / "verify.py").write_text(
        "from pathlib import Path\n"
        "value = Path('settings.txt').read_text(encoding='utf-8')\n"
        "assert value == \"MODE = 'ready'\\n\", repr(value)\n"
        "print('verified: MODE is ready')\n", encoding="utf-8")
    # Only this fixed demo enables Python. File paths alone are not an OS sandbox.
    executable = Path(sys.executable).name
    os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")
    catalog = build_local_catalog(root, allowed_commands=(executable,))
    key = sys.stdin.readline().strip() if args.live and args.key_stdin else None
    factory = (lambda _: TypeSafeJevChooser(api_key=key, timeout_seconds=20)) if args.live else (lambda _: ScriptedChooser())
    state = TaskState("file-demo", "Find the MODE setting, change only draft to ready, then run the provided verify.py with Python -I.",
                      constraints=["All operations in the demo workspace; do not modify verify.py."])
    report = {"backend": "live Jev" if args.live else "scripted-demo", "stages": [],
              "limitations": ["Fixed four-stage plan, no autonomous tool discovery or paging.",
                              "Task/observation grounded candidate fixtures; no neural helper used.",
                              "Separate field decisions plus final call decision; tiny smoke case, not accuracy evidence."]}

    def save():
        (root / "trace.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def run(tool_name, values, facts=()):
        tool = catalog.get(tool_name).as_tool_definition()
        inputter = ArgumentInput(chooser_factory=factory,
            proposer=lambda ctx: [ValueProposal(value, "demo task/observation candidate",
                ("current-observation",) if ctx.name in facts else ()) for value in values[ctx.name]],
            parallel_fields=2, max_choice_calls=20)
        prepared = inputter.build(state=state, tool=tool,
            fields=[ArgumentField(name, allow_construct=False, require_evidence=name in facts) for name in values])
        row = {"tool": tool_name, "preparation": asdict(prepared)}
        report["stages"].append(row)
        save()
        if prepared.status != "ready":
            report["success"] = False
            save()
            raise SystemExit(f"Stopped at {tool_name}: {prepared.status}; trace saved")
        committed = Agent(factory("COMMIT")).run(state=state, tool=tool, drafts=[prepared.candidate])
        row["commit"] = asdict(committed)
        save()
        if committed.status != "executed":
            report["success"] = False
            save()
            raise SystemExit(f"Stopped at {tool_name}: {committed.status}; trace saved")
        state.revise("workspace", json.dumps(committed.tool_result, ensure_ascii=False))
        return committed.tool_result

    run("file.search", {"text": ["MODE", "TIMEOUT"], "path": ["."]})
    read = run("file.read", {"path": ["settings.txt", "verify.py"]}, facts=("path",))
    run("file.replace_text", {"path": [read["path"]], "old_text": ["draft", "MODE"],
        "replacement": ["ready", "debug"], "expected_text": [read["text"]], "expected_count": [1]},
        facts=("path", "old_text", "expected_text"))
    executed = run("shell.run", {"argv": [[executable, "-I", "verify.py"], [executable, "--version"]]})
    report["success"] = (executed["returncode"] == 0 and "verified: MODE is ready" in executed["stdout"]
                         and (root / "settings.txt").read_text(encoding="utf-8") == "MODE = 'ready'\n")
    report["field_choice_calls"] = sum(s["preparation"]["choice_calls"] for s in report["stages"])
    report["commit_choice_calls"] = sum(s.get("commit", {}).get("choice_calls", 0) for s in report["stages"])
    save()
    print(json.dumps({"success": report["success"], "trace": str(root / "trace.json"),
                      "field_choice_calls": report["field_choice_calls"],
                      "commit_choice_calls": report["commit_choice_calls"]}))


if __name__ == "__main__":
    main()
