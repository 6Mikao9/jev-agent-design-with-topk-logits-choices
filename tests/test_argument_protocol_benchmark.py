import unittest

from benchmarks.benchmark_argument_protocol import run_case, run_suite


class ArgumentProtocolBenchmarkTests(unittest.TestCase):
    def test_refine_and_repropose_reach_explicit_commit(self):
        for name in ("refine", "repropose"):
            row = run_case(name)
            self.assertEqual(row["input_status"], "ready")
            self.assertEqual(row["commit_status"], "executed")
            self.assertEqual(row["tool_calls"], 1)

    def test_missing_evidence_stops_without_tool_side_effect(self):
        row = run_case("missing_evidence")
        self.assertEqual(row["input_status"], "lookup_required")
        self.assertEqual(row["commit_status"], "not_attempted")
        self.assertEqual(row["tool_calls"], 0)

    def test_suite_reports_bounded_execution(self):
        summary = run_suite()["summary"]
        self.assertEqual(summary["cases"], 4)
        self.assertEqual(summary["unsafe_tool_calls"], 0)


if __name__ == "__main__":
    unittest.main()
