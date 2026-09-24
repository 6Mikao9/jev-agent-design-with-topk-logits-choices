import unittest

from jev_agent.decision_model import OracleDecisionModel, ReplayDecisionModel
from jev_agent.models import ChoiceResult, TaskState
from jev_agent.runtime import DecisionRuntime
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


if __name__ == "__main__":
    unittest.main()
