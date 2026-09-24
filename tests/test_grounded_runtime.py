import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from benchmarks.benchmark_grounded_live import ReplayChooser, run_suite


class GroundedRuntimeTests(unittest.TestCase):
    def test_replay_current_events_execute_and_missing_version_is_blocked(self):
        with TemporaryDirectory() as directory:
            report = run_suite(ReplayChooser(), output=Path(directory) / "report.json")
        self.assertEqual(report["summary"]["current_file_correct"], 2)
        self.assertEqual(report["summary"]["missing_evidence_writes"], 0)
        self.assertEqual(report["summary"]["correct_events"], 3)
        self.assertEqual(report["rows"][-1]["status"], "evidence_blocked")


if __name__ == "__main__":
    unittest.main()
