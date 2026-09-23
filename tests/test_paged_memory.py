import unittest

from jev_agent.paged_memory import MemoryPage, PagedMemoryIndex, StaleMemoryPage


class PagedMemoryTests(unittest.TestCase):
    def setUp(self):
        self.index = PagedMemoryIndex(max_pages=2)
        self.index.upsert(MemoryPage("mem_01", "Friday departure plan", "leave Friday", revision=2))
        self.index.upsert(MemoryPage("mem_02", "TCP transport choice", "use TCP", revision=1))

    def test_prefilter_exposes_summary_but_not_content(self):
        candidates = self.index.select_pages("Which departure plan is current?", limit=1)
        self.assertEqual([item.page_id for item in candidates], ["mem_01"])
        self.assertNotIn("leave Friday", candidates[0].summary)

    def test_explicit_read_is_bounded_and_checks_revision(self):
        pages = self.index.read_selected(["mem_01"], expected_revisions={"mem_01": 2})
        self.assertEqual(pages[0].content, "leave Friday")
        with self.assertRaises(StaleMemoryPage):
            self.index.read_selected(["mem_01"], expected_revisions={"mem_01": 1})

    def test_stale_pages_are_removed_from_prefilter(self):
        self.index.mark_stale("mem_01")
        self.assertEqual(self.index.select_pages("Friday plan"), [])

    def test_capacity_is_hard_bounded(self):
        with self.assertRaises(ValueError):
            self.index.upsert(MemoryPage("mem_03", "extra", "too many"))


if __name__ == "__main__":
    unittest.main()
