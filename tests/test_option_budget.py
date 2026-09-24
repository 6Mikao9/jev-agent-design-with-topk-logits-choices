import unittest

from jev_agent.option_budget import JEV_MAX_OPTIONS, OptionPageBudget


class OptionPageBudgetTests(unittest.TestCase):
    def test_catalog_can_align_to_wire_ceiling_without_filling_a_call(self):
        budget = OptionPageBudget()
        pages = budget.catalog_pages(range(510))
        self.assertEqual([len(page) for page in pages], [255, 255])
        self.assertEqual(budget.max_action_options, 249)
        calls = budget.decision_calls(range(40), controls=("PAGE", "REFINE", "CLARIFY", "STOP"))
        self.assertEqual([len(call.candidates) for call in calls], [16, 16, 8])
        self.assertTrue(all(call.wire_count <= JEV_MAX_OPTIONS for call in calls))

    def test_controls_are_reserved_on_every_call(self):
        budget = OptionPageBudget(control_reserve=3, decision_target=250)
        calls = budget.decision_calls(("a", "b"), controls=("PAGE", "STOP"))
        self.assertEqual(calls[0].wire_count, 4)
        with self.assertRaises(ValueError):
            budget.decision_calls(("a",), controls=("PAGE", "STOP", "REFINE", "CLARIFY"))

    def test_empty_candidate_call_keeps_control_exits(self):
        budget = OptionPageBudget()
        calls = budget.decision_calls((), controls=("PAGE", "CLARIFY", "STOP"))
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].candidates, ())
        self.assertEqual(calls[0].controls, ("PAGE", "CLARIFY", "STOP"))


if __name__ == "__main__":
    unittest.main()

