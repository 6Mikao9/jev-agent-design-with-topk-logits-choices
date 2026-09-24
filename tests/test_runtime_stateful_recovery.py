import unittest

from benchmarks.benchmark_runtime_stateful_recovery import run_workload


class RuntimeStatefulRecoveryBenchmarkTests(unittest.TestCase):
    def test_24_step_runtime_closed_loop_recovers_stale_read(self):
        report = run_workload()
        self.assertEqual(report["workload_steps"], 24)
        self.assertEqual(report["page_recoveries"], 1)
        self.assertGreaterEqual(report["commits"], 1)
        self.assertEqual(report["contradictions"], 1)
        self.assertGreaterEqual(report["invalidations"], 1)
        self.assertEqual(report["recovery_successes"], 1)
        self.assertTrue(report["post_refresh_correct"])
        self.assertLessEqual(report["resident_peak"], report["resident_bound"])
        self.assertGreater(report["external_side_effects"], 0)
        self.assertEqual(len(report["steps"]), 24)


if __name__ == "__main__":
    unittest.main()
