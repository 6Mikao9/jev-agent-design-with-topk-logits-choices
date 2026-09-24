import unittest

from jev_agent.speculation import SpeculationBuffer, rank_pages
from jev_agent.virtual_option import StaleVirtualOption, VirtualOption, VirtualOptionManager


def manager():
    runtime = VirtualOptionManager(max_resident=2)
    runtime.register_page("p1", [VirtualOption("a", "A", page_id="p1")], revision=1)
    runtime.register_page("p2", [VirtualOption("b", "B", page_id="p2")], revision=1)
    runtime.register_page("p3", [VirtualOption("c", "C", page_id="p3")], revision=1)
    return runtime


class SpeculationTests(unittest.TestCase):
    def test_shadow_prefetch_does_not_pollute_resident_set(self):
        runtime = manager()
        shadow = SpeculationBuffer(max_pages=2)
        prepared = shadow.prefetch(runtime, rank_pages([("p2", .9), ("p3", .8)], top_b=2), base_revision=1)
        self.assertEqual([p.page_id for p in prepared], ["p2", "p3"])
        self.assertEqual(runtime.resident_options(), ())
        promoted = shadow.promote(runtime, "p2", current_revision=1)
        self.assertEqual([o.option_id for o in promoted], ["b"])
        self.assertEqual([o.option_id for o in runtime.resident_options()], ["b"])

    def test_state_revision_discards_without_page_in(self):
        runtime = manager()
        shadow = SpeculationBuffer()
        shadow.prefetch(runtime, ["p1"], base_revision=2)
        with self.assertRaises(StaleVirtualOption):
            shadow.promote(runtime, "p1", current_revision=3)
        self.assertEqual(runtime.resident_options(), ())
        self.assertEqual(shadow.prepared(), ())
        self.assertEqual(shadow.events[-1].reason, "state_revision_changed")

    def test_page_revision_discards_without_page_in(self):
        runtime = manager()
        shadow = SpeculationBuffer()
        shadow.prefetch(runtime, ["p1"], base_revision=1)
        runtime.register_page("p1", [VirtualOption("a2", "A2", page_id="p1")], revision=2)
        with self.assertRaises(StaleVirtualOption):
            shadow.promote(runtime, "p1", current_revision=1)
        self.assertEqual(runtime.resident_options(), ())

    def test_replace_and_cancel_are_bounded_and_audited(self):
        runtime = manager()
        shadow = SpeculationBuffer(max_pages=1)
        shadow.prefetch(runtime, ["p1", "p2"], base_revision=1)
        self.assertEqual([p.page_id for p in shadow.prepared()], ["p1"])
        self.assertEqual(shadow.events[-1].reason, "")
        shadow.clear()
        self.assertEqual(shadow.prepared(), ())
        self.assertEqual(shadow.events[-1].event, "discard")

    def test_rank_is_deterministic_and_not_probability_claim(self):
        self.assertEqual(rank_pages([("p2", .8), ("p1", .8), ("p3", .2)], top_b=2), ("p1", "p2"))
        with self.assertRaises(ValueError):
            rank_pages([], top_b=0)


if __name__ == "__main__":
    unittest.main()
