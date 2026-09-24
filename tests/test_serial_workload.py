import unittest

from benchmarks.benchmark_serial_workload import run_workload


class SerialWorkloadTests(unittest.TestCase):
    def test_serial_workload_connects_memory_context_and_tool_commit(self):
        report = run_workload()
        summary = report["summary"]
        self.assertEqual(summary["steps"], 4)
        self.assertEqual(summary["context_hit_rate"], 1.0)
        self.assertEqual(summary["memory_ok_rate"], 1.0)
        self.assertEqual(summary["argument_ready_rate"], 1.0)
        self.assertEqual(summary["tool_commit_rate"], 1.0)
        self.assertEqual(summary["tool_calls"], 4)
        self.assertTrue(summary["resident_bound_ok"])


if __name__ == "__main__":
    unittest.main()
