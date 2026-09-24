import unittest

from jev_agent.context_budget import (
    ContextBudget,
    ContextBudgetController,
    ContextBudgetExceeded,
    ContextSlice,
)


class ContextBudgetTests(unittest.TestCase):
    def test_default_frame_is_24k_and_regions_do_not_borrow(self):
        budget = ContextBudget()
        self.assertEqual(budget.total, 24 * 1024)
        controller = ContextBudgetController(budget)
        packed = controller.pack((
            ContextSlice("working", "low", "x" * 5000, priority=0),
            ContextSlice("working", "high", "y" * 2000, priority=1),
        ))
        self.assertEqual(packed.usage["working"], 2000)
        self.assertEqual(packed.dropped_ids, ("low",))

    def test_pinned_required_overflow_is_rejected(self):
        controller = ContextBudgetController(ContextBudget(pinned=8))
        with self.assertRaises(ContextBudgetExceeded):
            controller.pack((ContextSlice("pinned", "a", "12345", required=True),
                             ContextSlice("pinned", "b", "67890", required=True)))

    def test_priority_order_is_stable_and_sections_render(self):
        controller = ContextBudgetController(ContextBudget(recent=5))
        packed = controller.pack((
            ContextSlice("recent", "b", "bb", priority=1),
            ContextSlice("recent", "a", "aa", priority=1),
            ContextSlice("recent", "c", "cc", priority=0),
        ))
        self.assertEqual([item.item_id for item in packed.sections["recent"]], ["a", "b"])
        self.assertEqual(packed.as_prompt_sections()["recent"], "aa\nbb")

    def test_unknown_region_is_rejected(self):
        with self.assertRaises(ValueError):
            ContextBudgetController().pack((ContextSlice("unknown", "x", "data"),))


if __name__ == "__main__":
    unittest.main()
