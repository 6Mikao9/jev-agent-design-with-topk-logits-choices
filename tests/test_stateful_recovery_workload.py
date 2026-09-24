import unittest

from benchmarks.benchmark_stateful_recovery_workload import run_workload


class StatefulRecoveryWorkloadTests(unittest.TestCase):
    def test_legal_wrong_observation_is_invalidated_and_recovered(self):
        report = run_workload()
        self.assertEqual(report["workload_steps"], 24)
        self.assertTrue(report["hidden_truth"])
        self.assertEqual(report["contradictions_detected"], 1)
        self.assertGreaterEqual(report["invalidated_records"], 1)
        self.assertGreaterEqual(report["recovery_successes"], 1)
        self.assertEqual(report["external_side_effects"], 0)


if __name__ == "__main__":
    unittest.main()
