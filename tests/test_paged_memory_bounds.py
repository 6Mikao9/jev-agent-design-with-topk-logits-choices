import time
from datetime import datetime, timezone
import unittest

from jev_agent.paged_memory import (
    MemoryPage,
    MemoryReadBudgetExceeded,
    PagedMemoryIndex,
    StaleMemoryPage,
)


class PagedMemoryBoundsTests(unittest.TestCase):
    def _index(self):
        index = PagedMemoryIndex()
        index.upsert(MemoryPage("one", "one", "α"))
        index.upsert(MemoryPage("two", "two", "second"))
        return index

    def test_page_count_is_hard_limit(self):
        with self.assertRaises(MemoryReadBudgetExceeded):
            self._index().read_selected(["one", "two"], max_pages=1)

    def test_per_page_and_total_byte_limits_raise_instead_of_truncating(self):
        index = self._index()
        with self.assertRaises(MemoryReadBudgetExceeded):
            index.read_selected(["one"], max_page_bytes=1)
        with self.assertRaises(MemoryReadBudgetExceeded):
            index.read_selected(["one", "two"], max_bytes=2)

    def test_later_stale_page_does_not_touch_earlier_page(self):
        index = self._index()
        before = index._pages["one"].last_accessed
        time.sleep(0.001)
        index.mark_stale("two")
        with self.assertRaises(StaleMemoryPage):
            index.read_selected(["one", "two"])
        self.assertEqual(index._pages["one"].last_accessed, before)

    def test_sensitive_pages_are_hidden_and_denied_by_default(self):
        index = PagedMemoryIndex()
        index.upsert(MemoryPage("secret", "secret summary", "secret", sensitive=True))
        self.assertEqual(index.select_pages("secret"), [])
        self.assertEqual([c.page_id for c in index.select_pages("secret", allow_sensitive=True)], ["secret"])
        with self.assertRaises(PermissionError):
            index.read_selected(["secret"])
        self.assertEqual(index.read_selected(["secret"], allow_sensitive=True)[0].content, "secret")

    def test_dependency_versions_are_checked_before_access_updates(self):
        index = PagedMemoryIndex()
        index.upsert(MemoryPage("one", "one", "value", dependency_versions={"db": 2}))
        before = index._pages["one"].last_accessed
        with self.assertRaises(StaleMemoryPage):
            index.read_selected(["one"], expected_dependency_versions={"db": 1})
        self.assertEqual(index._pages["one"].last_accessed, before)

    def test_upsert_and_read_are_copy_isolated(self):
        source = MemoryPage("one", "one", "original", dependency_versions={"db": 1})
        index = PagedMemoryIndex()
        index.upsert(source)
        source.content = "changed outside"
        source.dependency_versions["db"] = 99
        self.assertEqual(index.read_selected(["one"])[0].content, "original")

        result = index.read_selected(["one"])[0]
        result.content = "changed result"
        result.dependency_versions["db"] = 88
        self.assertEqual(index.read_selected(["one"])[0].content, "original")

    def test_same_revision_payload_changes_are_rejected(self):
        index = PagedMemoryIndex()
        index.upsert(MemoryPage("one", "one", "original", revision=3))
        with self.assertRaises(ValueError):
            index.upsert(MemoryPage("one", "one", "changed", revision=3))
        with self.assertRaises(ValueError):
            index.upsert(MemoryPage("one", "new summary", "original", revision=3))
        with self.assertRaises(ValueError):
            index.upsert(MemoryPage("one", "one", "original", revision=3,
                                    dependency_versions={"db": 1}))

    def test_recency_tie_break_uses_age_not_absolute_timestamp(self):
        index = PagedMemoryIndex(recency_half_life_seconds=10.0)
        now = datetime.now(timezone.utc).timestamp()
        index.upsert(MemoryPage("old", "same topic", "old", last_accessed=now - 100.0))
        index.upsert(MemoryPage("new", "same topic", "new", last_accessed=now))
        self.assertEqual([item.page_id for item in index.select_pages("topic")], ["new", "old"])

    def test_large_early_page_does_not_hide_later_page_in_bounded_scan(self):
        index = PagedMemoryIndex()
        index.upsert(MemoryPage("large", "large", "x" * 100))
        index.upsert(MemoryPage("needle", "note", "needle marker"))
        found = index.search_content("needle", max_scan_bytes=32)
        self.assertEqual([item.page_id for item in found], ["needle"])


if __name__ == "__main__":
    unittest.main()
