import unittest

from jev_agent.models import Candidate, ChoiceResult, TaskState
from jev_agent.orchestrator import JevAgentOrchestrator
from jev_agent.paged_memory import MemoryPage, PagedMemoryIndex
from jev_agent.agent import ToolDefinition


class OrchestratorChooser:
    def __init__(self):
        self.states = []

    def choose(self, *, state, instructions, options):
        self.states.append(state)
        if any(option.option_id.startswith("PAGE_") for option in options):
            choice = next(option.option_id for option in options if option.option_id.startswith("PAGE_"))
        elif any(option.option_id.startswith("TOP_") for option in options):
            choice = next(option.option_id for option in options if option.option_id.startswith("TOP_"))
        else:
            choice = "draft"
        probabilities = {option.option_id: (1.0 if option.option_id == choice else 0.0) for option in options}
        return ChoiceResult(choice, probabilities, 1.0, "replay")


class OrchestratorTests(unittest.TestCase):
    def test_memory_evidence_is_injected_before_tool_choice_and_traced(self):
        index = PagedMemoryIndex()
        index.upsert(MemoryPage("plan", "Friday departure plan", "leave at 08:00"))
        seen = {}

        def execute(arguments):
            seen["arguments"] = arguments
            return {"ok": True}

        tool = ToolDefinition(
            "file.write", "write", "1",
            {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"], "additionalProperties": False},
            execute,
        )
        state = TaskState("task-1", "follow the departure plan")
        draft = Candidate("draft", "file.write", {"path": "notes.txt"}, "replay", 1, "1")
        chooser = OrchestratorChooser()
        runtime = JevAgentOrchestrator(chooser, memory_index=index)
        try:
            result = runtime.run(state=state, tool=tool, drafts=[draft], memory_context="Friday departure")
        finally:
            runtime.close()
        self.assertEqual(result.status, "executed")
        self.assertEqual(seen["arguments"], {"path": "notes.txt"})
        self.assertEqual(result.memory.selected_ids, ("plan",))
        self.assertEqual(len(result.trace.edges()), 2)
        self.assertIn("leave at 08:00", chooser.states[-1])


if __name__ == "__main__":
    unittest.main()
