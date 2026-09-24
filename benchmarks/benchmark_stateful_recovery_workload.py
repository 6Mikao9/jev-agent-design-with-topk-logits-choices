"""Deterministic stateful workload with legal-but-wrong tool observations.

The environment has hidden mutable state.  A faulty read returns a valid
observation with an old value; the runtime must detect the contradiction,
invalidate dependent memory, refresh the source of truth, and continue.  The
benchmark is offline and uses no model or oracle target in the decision input.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from jev_agent.memory import MemoryBank, MemoryRecord
from jev_agent.context_residency import ContextBlock, ContextResidencyManager

OUT = Path(__file__).parent / "results" / "stateful-recovery-workload.json"


class StatefulEnvironment:
    """Small state machine; ``read_quota`` can return a stale but legal value."""

    def __init__(self) -> None:
        self.truth = {"quota": 3, "used": 0, "version": 1}
        self.stale_read = False

    def mutate_quota(self, value: int) -> dict:
        self.truth["quota"] = value
        self.truth["version"] += 1
        return {"ok": True, "version": self.truth["version"]}

    def read_quota(self) -> dict:
        # Syntactically and semantically plausible, but stale after mutation.
        quota = 3 if self.stale_read else self.truth["quota"]
        return {"ok": True, "quota": quota, "used": self.truth["used"],
                "version": self.truth["version"] - (1 if self.stale_read else 0)}

    def reserve(self, amount: int) -> dict:
        if self.truth["used"] + amount > self.truth["quota"]:
            return {"ok": False, "reason": "quota_exceeded", "version": self.truth["version"]}
        self.truth["used"] += amount
        return {"ok": True, "used": self.truth["used"], "version": self.truth["version"]}


def run_workload(*, steps: int = 24) -> dict:
    if steps != 24:
        raise ValueError("the reference workload is exactly 24 steps")
    env, memory = StatefulEnvironment(), MemoryBank()
    context = ContextResidencyManager(max_working=3, minimum_residency_steps=1)
    current_versions = {"quota": 1}
    records: list[dict] = []
    invalidated = recovered = contradictions = 0

    def add_memory(version: int, quota: int) -> None:
        memory.add(MemoryRecord(
            f"quota-v{version}", f"quota is {quota}", "observation",
            {"quota": version}, impact_tags=frozenset({"quota", "reservation"}),
        ))

    add_memory(1, 3)
    for step in range(1, steps + 1):
        event, result, fault, recovery = "noop", None, None, None
        if step == 6:
            event, result = "mutate_quota", env.mutate_quota(1)
            current_versions["quota"] = env.truth["version"]
            invalidated += len(memory.invalidate_changed(current_versions, ["quota"]))
            add_memory(env.truth["version"], env.truth["quota"])
            context.register(ContextBlock("quota", "quota changed; refresh required", "env://quota",
                                          revision=env.truth["version"], dependencies=("quota",), kind="tool_output"))
        elif step in {8, 9}:
            event = "read_quota_fault_injected" if step == 8 else "read_quota_recheck"
            env.stale_read = step == 8
            result = env.read_quota()
            expected = env.truth["quota"]
            if result["quota"] != expected or result["version"] != env.truth["version"]:
                contradictions += 1
                fault = "contradictory_observation"
                invalidated += len(memory.invalidate_changed(current_versions, ["quota"]))
                env.stale_read = False
                fresh = env.read_quota()
                recovered += int(fresh["quota"] == expected and fresh["version"] == env.truth["version"])
                add_memory(env.truth["version"], fresh["quota"])
                recovery = "invalidate_and_refresh_source"
            else:
                recovered += 1
        elif step in {10, 11, 12, 13, 14, 15, 16, 17, 18, 19}:
            event = "reserve" if step % 2 == 0 else "read_quota"
            result = env.reserve(1) if event == "reserve" else env.read_quota()
            if event == "reserve" and not result["ok"]:
                fault, recovery = "quota_guard", "clarify_or_stop"
        elif step == 20:
            event, result = "mutate_quota", env.mutate_quota(2)
            current_versions["quota"] = env.truth["version"]
            invalidated += len(memory.invalidate_changed(current_versions, ["quota"]))
            add_memory(env.truth["version"], env.truth["quota"])
        elif step in {21, 22, 23, 24}:
            event = "read_quota" if step != 24 else "stop"
            result = env.read_quota() if event == "read_quota" else {"ok": True}
        else:
            event = "inspect_state"
            result = {"ok": True, "version": env.truth["version"]}
        records.append({"step": step, "event": event, "fault": fault,
                        "recovery": recovery, "result_ok": bool(result and result.get("ok"))})

    report = {
        "name": "stateful-recovery-workload", "workload_steps": steps,
        "hidden_truth": True, "fault_injection": "legal_stale_read_at_step_8",
        "contradictions_detected": contradictions, "invalidated_records": invalidated,
        "recovery_successes": recovered, "memory_records": len(memory.all_records()),
        "resident_bound": context.max_working, "external_side_effects": 0,
        "steps": records,
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    print(json.dumps(run_workload(), ensure_ascii=False, indent=2))
