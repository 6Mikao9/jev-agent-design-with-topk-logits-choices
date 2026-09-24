import unittest

from benchmarks.benchmark_context_realtime import _run


class ContextRealtimeTests(unittest.TestCase):
    def test_static_context_misses_later_phase_blocks(self):
        row = _run("static")
        self.assertLess(row["phase_hit_rate"], 1.0)
        self.assertGreater(row["cold_faults"], 0)

    def test_refresh_replaces_context_and_keeps_revision_guard(self):
        row = _run("refresh")
        self.assertEqual(row["phase_hit_rate"], 1.0)
        self.assertEqual(row["cold_faults"], 0)
        self.assertEqual(row["revision_updates"], 1)

    def test_refresh_respects_working_bound(self):
        row = _run("refresh_hysteresis")
        self.assertEqual(row["phase_hit_rate"], 1.0)
        for snapshot in row["snapshots"]:
            self.assertLessEqual(len([item for item in snapshot["resident_ids"] if item != "goal"]), 2)


if __name__ == "__main__":
    unittest.main()
