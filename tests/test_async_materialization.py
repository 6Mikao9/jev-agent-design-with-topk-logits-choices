import unittest

from benchmarks.benchmark_async_materialization import run_suite
from jev_agent.speculation import SpeculationBuffer
from jev_agent.virtual_option import VirtualOption, VirtualOptionManager


class AsyncMaterializationTests(unittest.TestCase):
    def test_async_pages_stay_shadow_until_collected(self):
        manager = VirtualOptionManager(max_resident=1)
        manager.register_page("p", [VirtualOption("p:0", "P", page_id="p")])
        shadow = SpeculationBuffer(max_pages=1)
        shadow.prefetch_async(manager, ["p"], base_revision=1)
        self.assertEqual(manager.resident_options(), ())
        self.assertEqual(shadow.pending_count, 1)
        shadow.await_materialization(timeout_seconds=1)
        self.assertEqual(manager.resident_options(), ())
        shadow.promote(manager, "p", current_revision=1)
        self.assertEqual([option.option_id for option in manager.resident_options()], ["p:0"])

    def test_benchmark_reports_stale_rejection(self):
        report = run_suite()
        self.assertEqual(report["stale_status"], "StaleVirtualOption")
        self.assertLess(report["async_total_ms"], report["sequential_ms"] + 30)


if __name__ == "__main__":
    unittest.main()
