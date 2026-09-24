import unittest

from jev_agent.memory_selection import TwoStageMemorySelector
from jev_agent.models import ChoiceResult
from jev_agent.paged_memory import MemoryPage, PagedMemoryIndex


class ScriptedChooser:
    """Replay endpoint-shaped distributions for the two memory rounds."""

    def __init__(self, choices):
        self.choices = list(choices)
        self.calls = []

    def choose(self, *, state, instructions, options):
        self.calls.append((state, options))
        choice = self.choices.pop(0)
        probabilities = {option.option_id: 0.0 for option in options}
        probabilities[choice] = 1.0
        return ChoiceResult(choice, probabilities, 1.0, "scripted")


class MemorySelectionTests(unittest.TestCase):
    def _index(self):
        index = PagedMemoryIndex()
        index.upsert(MemoryPage("a", "deployment plan", "deploy at 10", tags=("deploy",)))
        index.upsert(MemoryPage("b", "deployment rollback", "rollback if unhealthy", tags=("deploy",)))
        return index

    def test_rank_then_top_n_reads_only_selected_prefix(self):
        # The recency tie-break keeps the page inserted last first; choose the
        # first returned entry so the ranking assertion exercises the full
        # probability path rather than relying on the old lexical-ID order.
        chooser = ScriptedChooser(["PAGE_000", "TOP_2"])
        result = TwoStageMemorySelector(chooser).retrieve(self._index(), context="deployment")
        self.assertEqual(result.status, "read_complete")
        self.assertEqual(result.ranked_ids[:2], ("b", "a"))
        self.assertEqual(result.selected_ids, ("b", "a"))
        self.assertEqual(result.requested_count, 2)
        self.assertEqual(len(chooser.calls), 2)
        self.assertEqual(len(result.choices), 2)
        self.assertGreater(result.request_bytes[0], 0)

    def test_control_choice_does_not_read_pages(self):
        chooser = ScriptedChooser(["NONE"])
        result = TwoStageMemorySelector(chooser).retrieve(self._index(), context="deployment")
        self.assertEqual(result.status, "no_memory")
        self.assertEqual(result.pages, ())
        self.assertEqual(len(chooser.calls), 1)

    def test_read_budget_failure_is_reported_without_partial_pages(self):
        chooser = ScriptedChooser(["PAGE_000", "TOP_2"])
        result = TwoStageMemorySelector(
            chooser, max_read_bytes=5, count_options=(2, 4, 8)
        ).retrieve(self._index(), context="deployment")
        self.assertEqual(result.status, "read_budget_exceeded")
        self.assertEqual(result.pages, ())
        self.assertEqual(result.selected_ids, ())


if __name__ == "__main__":
    unittest.main()
