import unittest

from jev_agent.context_residency import ContextBlock, ContextResidencyManager
from jev_agent.decision_model import OracleDecisionModel, ReplayDecisionModel
from jev_agent.memory import MemoryBank, MemoryRecord
from jev_agent.models import ChoiceResult, TaskState
from jev_agent.runtime import DecisionRuntime, ExecutionVerdict
from jev_agent.virtual_option import VirtualOption, VirtualOptionManager


class DecisionRuntimeTests(unittest.TestCase):
    def test_page_then_commit_uses_one_shared_loop(self):
        manager = VirtualOptionManager(max_resident=2)
        manager.register_page("tools", [VirtualOption("run", "run tool", page_id="tools")])
        model = ReplayDecisionModel([
            ChoiceResult("PAGE:tools", {"PAGE:tools": 1.0, "CLARIFY": 0.0, "STOP": 0.0}, 1.0, "replay"),
            ChoiceResult("run", {"run": 1.0, "CLARIFY": 0.0, "STOP": 0.0}, 1.0, "replay"),
        ])
        runtime = DecisionRuntime(model, option_manager=manager)
        task = TaskState("t", "run the tool")
        first = runtime.step(task=task, instructions="choose", page_ids=("tools",))
        second = runtime.step(task=task, instructions="choose", page_ids=())
        self.assertEqual(first.status, "paged")
        self.assertEqual(second.status, "committed")
        self.assertEqual(second.option_id, "run")

    def test_refine_replaces_parent_before_commit(self):
        manager = VirtualOptionManager(max_resident=2)
        manager.register_page("coarse", [VirtualOption("coarse", "coarse", page_id="coarse")])
        manager.page_in("coarse")
        child = VirtualOption("child", "fine", page_id="child")
        model = ReplayDecisionModel([
            ChoiceResult("REFINE:coarse", {"coarse": 0.0, "REFINE:coarse": 1.0, "CLARIFY": 0.0, "STOP": 0.0}, 1.0, "replay"),
            ChoiceResult("child", {"child": 1.0, "CLARIFY": 0.0, "STOP": 0.0}, 1.0, "replay"),
        ])
        runtime = DecisionRuntime(model, option_manager=manager)
        task = TaskState("t", "choose fine option")
        first = runtime.step(task=task, instructions="choose", refinements={"coarse": (child,)})
        second = runtime.step(task=task, instructions="choose")
        self.assertEqual(first.status, "refined")
        self.assertEqual(second.status, "committed")
        self.assertEqual(second.option_id, "child")
        self.assertNotIn("coarse", [item.option_id for item in manager.resident_options()])

    def test_fully_resident_page_is_not_offered_again(self):
        manager = VirtualOptionManager(max_resident=2)
        manager.register_page("tools", [VirtualOption("run", "run tool", page_id="tools")])
        model = OracleDecisionModel(
            lambda request: "PAGE:tools" if "PAGE:tools" in {item.option_id for item in request.options} else "run"
        )
        runtime = DecisionRuntime(model, option_manager=manager)
        task = TaskState("t", "run the tool")
        first = runtime.step(task=task, instructions="choose", page_ids=("tools",))
        second = runtime.step(task=task, instructions="choose", page_ids=("tools",))
        self.assertEqual(first.status, "paged")
        self.assertEqual(second.status, "committed")
        self.assertEqual(second.option_id, "run")

    def test_page_failure_budget_is_scoped_to_task(self):
        model = OracleDecisionModel(
            lambda request: next(
                (item.option_id for item in request.options if item.option_id.startswith("PAGE:")),
                "CLARIFY",
            )
        )
        runtime = DecisionRuntime(model, max_page_attempts=1)
        first_task = TaskState("first", "find a missing page")
        second_task = TaskState("second", "find a missing page")
        first = runtime.step(task=first_task, instructions="choose", page_ids=("missing",))
        bounded = runtime.step(task=first_task, instructions="choose", page_ids=("missing",))
        independent = runtime.step(task=second_task, instructions="choose", page_ids=("missing",))
        self.assertEqual(first.status, "fault")
        self.assertEqual(bounded.status, "clarification_required")
        self.assertEqual(independent.status, "fault")

    def test_task_revision_is_not_option_revision(self):
        manager = VirtualOptionManager(max_resident=1)
        manager.register_page("tools", [VirtualOption("run", "run", page_id="tools", revision=1)])
        manager.page_in("tools")
        runtime = DecisionRuntime(
            OracleDecisionModel(lambda request: "run"), option_manager=manager
        )
        task = TaskState("t", "run")
        task.revise("quota", "state changed")
        result = runtime.step(task=task, instructions="choose")
        self.assertEqual(result.status, "committed")

    def test_legal_stale_tool_output_invalidates_and_requires_new_decision(self):
        manager = VirtualOptionManager(max_resident=2)
        manager.register_page("tools", [
            VirtualOption("read", "read quota", page_id="tools"),
            VirtualOption("refresh", "refresh source of truth", page_id="tools"),
        ])
        manager.page_in("tools")
        context = ContextResidencyManager(max_working=1)
        context.register(ContextBlock("quota", "trusted quota version 1", "env://quota",
                                      dependencies=("quota",), pinned=True))
        context.register(ContextBlock("stable", "stable task constraint", "env://stable",
                                      dependencies=("stable",), pinned=True))
        memory = MemoryBank()
        memory.add(MemoryRecord("quota-old", "quota version 1", "observation", {"quota": 1}))
        memory.add(MemoryRecord("stable", "stable constraint", "constraint", {"stable": 1}))
        task = TaskState("t", "use current quota")
        task.dependency_versions.update({"quota": 1, "stable": 1})
        model = OracleDecisionModel(
            lambda request: "refresh" if "inconsistent quota" in request.state else "read"
        )
        runtime = DecisionRuntime(model, option_manager=manager,
                                  context_manager=context, memory_bank=memory)
        calls = []

        def execute(option):
            calls.append(option.option_id)
            return {"ok": True, "version": 0 if option.option_id == "read" else 2}

        def validate(option, result, state):
            if result["version"] < state.dependency_versions["quota"]:
                return ExecutionVerdict(False, "stale but well-formed read",
                                        ("quota",), "inconsistent quota observation")
            return ExecutionVerdict(True)

        first = runtime.step(task=task, instructions="choose", query="quota",
                             execute=execute, validate_execution=validate)
        self.assertEqual(first.status, "execution_rejected")
        self.assertEqual(first.invalidated_memory_ids, ("quota-old",))
        self.assertEqual(first.invalidated_context_ids, ("quota",))
        self.assertEqual(first.revised_dependencies, ("quota",))
        self.assertEqual(task.revision, 2)
        self.assertEqual([item.block_id for item in context.resident()], ["stable"])
        self.assertEqual([item.record_id for item in memory.retrieve(
            dependency_ids=("stable",), current_versions=task.dependency_versions
        )], ["stable"])
        self.assertEqual(calls, ["read"])

        second = runtime.step(task=task, instructions="choose", query="quota",
                              execute=execute, validate_execution=validate)
        self.assertEqual(second.status, "executed")
        self.assertEqual(calls, ["read", "refresh"])


if __name__ == "__main__":
    unittest.main()
