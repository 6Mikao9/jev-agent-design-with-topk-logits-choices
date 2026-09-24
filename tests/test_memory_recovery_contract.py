import unittest

from benchmarks.benchmark_memory_p2_multineedle import run_case


class MemoryRecoveryContractTests(unittest.TestCase):
    def test_scan_budget_miss_is_not_reported_as_recovered(self):
        row = run_case("target_last", "content")
        self.assertIn(row["fallback_status"], {"no_match", "contract_unsatisfied"})
        self.assertFalse(row["answer_correct"])


if __name__ == "__main__":
    unittest.main()
