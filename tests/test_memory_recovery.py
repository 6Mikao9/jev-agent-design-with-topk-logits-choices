import unittest

from benchmarks.benchmark_memory_p1_gap import run_episode


class MemoryRecoveryTests(unittest.TestCase):
    def test_conflict_gap_recovers_current_primary_page(self):
        meta = {"position": "middle", "omission": "none", "state": "conflict"}
        baseline = run_episode(meta, fallback=False)
        recovered = run_episode(meta, fallback=True)
        self.assertFalse(baseline["answer_correct"])
        self.assertTrue(recovered["answer_correct"])
        self.assertEqual(recovered["fallback_status"], "recovered")
        self.assertIn(recovered["target_page"], recovered["recovered_ids"])

    def test_stale_selection_does_not_scan_or_bypass_guard(self):
        row = run_episode({"position": "head", "omission": "none", "state": "stale"}, fallback=True)
        self.assertEqual(row["initial_status"], "stale_selection")
        self.assertEqual(row["fallback_status"], "not_attempted")
        self.assertTrue(row["guard_safe"])
        self.assertFalse(row["answer_correct"])

    def test_fresh_case_does_not_need_fallback(self):
        row = run_episode({"position": "tail", "omission": "negation", "state": "fresh"}, fallback=True)
        self.assertEqual(row["fallback_status"], "not_needed")
        self.assertTrue(row["answer_correct"])


if __name__ == "__main__":
    unittest.main()
