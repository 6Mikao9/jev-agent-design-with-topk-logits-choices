import unittest

from benchmarks.benchmark_memory_p0 import run_episode, run_suite


class MemoryP0Tests(unittest.TestCase):
    def test_suite_has_48_episodes_and_separates_metrics(self):
        report = run_suite()
        self.assertEqual(report["summary"]["episodes"], 48)
        self.assertEqual(len(report["rows"]), 48)
        self.assertIn("needle_evidence_recall", report["summary"])
        self.assertIn("answer_correct_rate", report["summary"])

    def test_stale_case_is_rejected_safely(self):
        row = run_episode({"position": "head", "omission": "none", "state": "stale"})
        self.assertEqual(row["status"], "stale_selection")
        self.assertTrue(row["guard_safe"])
        self.assertFalse(row["answer_correct"])

    def test_conflict_case_exposes_prefix_ranking_failure(self):
        row = run_episode({"position": "middle", "omission": "none", "state": "conflict"})
        # The lexical summary-only baseline can spend TOP_2 on a conflict page
        # and a decoy, leaving the current primary page cold. This is a useful
        # negative control for the later evidence-bundle policy.
        self.assertFalse(row["target_read"])
        self.assertFalse(row["answer_correct"])


if __name__ == "__main__":
    unittest.main()
