"""Offline 24-step scripted Runtime.step() stateful recovery benchmark.

This is a mechanism experiment: a deterministic DecisionModel drives the shared
DecisionRuntime loop against mutable hidden state. It does not measure Jev
success rate or model quality.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jev_agent.context_residency import ContextBlock, ContextResidencyManager
from jev_agent.decision_model import DecisionRequest, OracleDecisionModel
from jev_agent.models import ChoiceResult, TaskState
from jev_agent.runtime import DecisionRuntime
from jev_agent.virtual_option import VirtualOption, VirtualOptionManager

OUT = Path(__file__).parent / "results" / "runtime-stateful-recovery.json"


class HiddenState:
    def __init__(self) -> None:
        self.quota, self.used, self.version = 3, 0, 1
        self.stale_once = False
        self.side_effects = 0

    def mutate(self, quota: int) -> dict[str, Any]:
        self.quota, self.version = quota, self.version + 1
        return {"ok": True, "quota": quota, "version": self.version}

    def read(self) -> dict[str, Any]:
        version = self.version - 1 if self.stale_once else self.version
        quota = 3 if self.stale_once else self.quota
        self.stale_once = False
        return {"ok": True, "quota": quota, "used": self.used, "version": version}

    def reserve(self, amount: int) -> dict[str, Any]:
        self.side_effects += 1
        if self.used + amount > self.quota:
            return {"ok": False, "reason": "quota_exceeded", "version": self.version}
        self.used += amount
        return {"ok": True, "used": self.used, "quota": self.quota, "version": self.version}


def run_workload(*, steps: int = 24) -> dict[str, Any]:
    if steps != 24:
        raise ValueError("reference workload is exactly 24 steps")
    env = HiddenState()
    task = TaskState("runtime-stateful", "maintain quota reservations from current facts")
    task.dependency_versions["quota"] = 1
    manager = VirtualOptionManager(max_resident=8)
    tools = [
        VirtualOption("mutate1", "set quota to one", page_id="tools"),
        VirtualOption("read", "read current quota", page_id="tools"),
        VirtualOption("reserve", "reserve one unit", page_id="tools"),
        VirtualOption("mutate2", "set quota to two", page_id="tools"),
    ]
    manager.register_page("tools", tools)
    context = ContextResidencyManager(max_working=3, minimum_residency_steps=1)
    context.register(ContextBlock("quota", "quota=3 used=0 version=1", "env://quota", revision=1, dependencies=("quota",), kind="tool_output", pinned=True))

    def select(request: DecisionRequest) -> str:
        ids = {item.option_id for item in request.options}
        if "PAGE:tools" in ids:
            return "PAGE:tools"
        # This scripted policy is stateful on purpose: each transition is
        # selected at most once, so the benchmark can expose repeated-action
        # bugs in the shared runtime rather than hide them behind a replay.
        if not mutate1_done and "mutate1" in ids:
            return "mutate1"
        if not stale_recovered and "read" in ids:
            return "read"
        if not mutate2_done and "mutate2" in ids:
            return "mutate2"
        if reserve_count < 2 and "reserve" in ids:
            return "reserve"
        if read_count < 4 and "read" in ids:
            return "read"
        return "STOP"

    runtime = DecisionRuntime(OracleDecisionModel(select), option_manager=manager, context_manager=context)
    records: list[dict[str, Any]] = []
    contradictions = invalidations = recoveries = commits = 0
    refreshed_dependency_step: int | None = None
    peak_resident = 0
    mutate1_done = False
    mutate2_done = False
    stale_recovered = False
    reserve_count = 0
    read_count = 0

    def execute(option: VirtualOption) -> dict[str, Any]:
        nonlocal contradictions, invalidations, recoveries, refreshed_dependency_step, commits
        nonlocal mutate1_done, mutate2_done, stale_recovered, reserve_count, read_count
        if option.option_id == "mutate1":
            mutate1_done = True
            result = env.mutate(1)
            task.revise("quota", f"quota changed to {env.quota} at v{env.version}")
            context.register(ContextBlock("quota", f"quota={env.quota} used={env.used} version={env.version}", "env://quota", revision=env.version, dependencies=("quota",), kind="tool_output", pinned=True))
            refreshed_dependency_step = runtime._step
            return result
        if option.option_id == "mutate2":
            mutate2_done = True
            result = env.mutate(2)
            task.revise("quota", f"quota changed to {env.quota} at v{env.version}")
            context.register(ContextBlock("quota", f"quota={env.quota} used={env.used} version={env.version}", "env://quota", revision=env.version, dependencies=("quota",), kind="tool_output", pinned=True))
            refreshed_dependency_step = runtime._step
            return result
        if option.option_id == "read":
            read_count += 1
            result = env.read()
            if result["version"] != env.version or result["quota"] != env.quota:
                stale_recovered = True
                contradictions += 1
                invalidations += 1
                task.revise("quota", "contradictory quota observation invalidated")
                fresh = env.read()
                context.register(ContextBlock("quota", f"quota={fresh['quota']} used={fresh['used']} version={fresh['version']}", "env://quota", revision=fresh["version"], dependencies=("quota",), kind="tool_output", pinned=True))
                recoveries += int(fresh["version"] == env.version and fresh["quota"] == env.quota)
                refreshed_dependency_step = runtime._step
                return {"stale": result, "fresh": fresh}
            return result
        reserve_count += 1
        commits += 1
        return env.reserve(1)

    for _ in range(steps):
        step_no = runtime._step + 1
        if step_no == 5:
            env.stale_once = True
        result = runtime.step(task=task, instructions="select next safe operation", query="quota reservation current version", page_ids=("tools",), execute=execute)
        peak_resident = max(peak_resident, len(result.resident_option_ids))
        records.append({"step": step_no, "status": result.status, "choice": result.choice, "option_id": result.option_id, "faults": list(result.faults), "tool_result": result.tool_result, "task_revision": task.revision})

    report = {
        "name": "runtime-stateful-recovery", "workload_steps": steps,
        "offline_scripted_mechanism_experiment": True,
        "hidden_mutable_state": True, "stale_read_step": 5,
        "page_recoveries": sum(r["status"] == "paged" for r in records),
        "commits": commits, "contradictions": contradictions,
        "invalidations": invalidations, "recovery_successes": recoveries,
        "post_refresh_correct": bool(refreshed_dependency_step and env.quota == 2 and env.used <= env.quota),
        "resident_peak": peak_resident, "resident_bound": manager.max_resident,
        "external_side_effects": env.side_effects, "final_truth": {"quota": env.quota, "used": env.used, "version": env.version},
        "steps": records,
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    print(json.dumps(run_workload(), ensure_ascii=False, indent=2))
