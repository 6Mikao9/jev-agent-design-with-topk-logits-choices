import unittest

from jev_agent.virtual_option import (
    OptionFault,
    RefineFault,
    StaleVirtualOption,
    VirtualOption,
    VirtualOptionManager,
)


def option(option_id, page_id, *, revision=1, kind="tool"):
    return VirtualOption(option_id, option_id, {"id": option_id}, page_id, revision, kind)


class VirtualOptionTests(unittest.TestCase):
    def test_page_in_resident_bound_and_lru_replacement(self):
        manager = VirtualOptionManager(max_resident=2)
        manager.register_page("tools-0", [option("read", "tools-0"), option("write", "tools-0")])
        manager.register_page("tools-1", [option("search", "tools-1")])
        manager.page_in("tools-0")
        manager.touch("write")
        loaded = manager.page_in("tools-1")
        self.assertEqual([item.option_id for item in loaded], ["search"])
        self.assertEqual([item.option_id for item in manager.resident_options()], ["write", "search"])
        with self.assertRaises(OptionFault):
            manager.resolve("read")

    def test_protected_lru_eviction_is_atomic(self):
        manager = VirtualOptionManager(max_resident=2)
        manager.register_page("p", [option("a", "p"), option("b", "p")])
        manager.page_in("p")
        with self.assertRaises(OptionFault):
            manager.evict_lru(2, protected_ids=("a",))
        self.assertEqual([item.option_id for item in manager.resident_options()], ["a", "b"])

    def test_revision_invalidation_and_stable_id(self):
        manager = VirtualOptionManager(max_resident=2)
        manager.register_page("p", [option("x", "p", revision=1)])
        manager.page_in("p")
        self.assertEqual(manager.resolve("x", expected_revision=1).option_id, "x")
        manager.invalidate_page("p")
        with self.assertRaises(StaleVirtualOption):
            manager.resolve("x")
        manager.register_page("p", [option("x", "p", revision=2)], revision=2)
        manager.page_in("p")
        with self.assertRaises(StaleVirtualOption):
            manager.resolve("x", expected_revision=1)
        self.assertEqual(manager.resolve("x", expected_revision=2).option_id, "x")

    def test_refine_creates_child_page_and_pages_it_in(self):
        manager = VirtualOptionManager(max_resident=2)
        manager.register_page("coarse", [option("search", "coarse")])
        manager.page_in("coarse")
        children = manager.refine(
            "search", [VirtualOption("q1", "query one"), VirtualOption("q2", "query two")], revision=3
        )
        self.assertEqual([item.option_id for item in children], ["q1", "q2"])
        self.assertEqual(children[0].page_id, "refine:search:r3")
        self.assertEqual(manager.resolve("q2").description, "query two")
        with self.assertRaises(RefineFault):
            manager.refine("search", [])


if __name__ == "__main__":
    unittest.main()
