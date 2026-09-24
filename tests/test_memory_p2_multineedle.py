import unittest

from benchmarks.benchmark_memory_p2_multineedle import run_case


class MemoryP2MultineedleTests(unittest.TestCase):
    def test_target_first_hybrid_recovers_both_needles(self):
        row = run_case("target_first", "hybrid")
        self.assertTrue(row["joint_recall"])
        self.assertTrue(row["answer_correct"])

    def test_target_last_exposes_scan_budget_order_sensitivity(self):
        row = run_case("target_last", "hybrid")
        self.assertFalse(row["joint_recall"])
        self.assertLess(row["needle_recall"], 1.0)

    def test_summary_baseline_does_not_claim_joint_recall(self):
        row = run_case("random", "summary")
        self.assertFalse(row["joint_recall"])


if __name__ == "__main__":
    unittest.main()
