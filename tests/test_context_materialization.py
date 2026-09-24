import unittest

from jev_agent.context_materialization import (
    ContextMaterializationBudgetExceeded,
    ContextMaterializer,
    ContextSourceNotFound,
    StaleContextMaterialization,
)
from jev_agent.context_residency import ContextBlock


class ContextMaterializationTests(unittest.TestCase):
    def test_loads_body_with_hash_and_revision(self):
        block = ContextBlock("b", "short summary", "raw://b", revision=3)
        materialized = ContextMaterializer({"raw://b": "source=approval; version=3"}).materialize(
            block, expected_revision=3
        )
        self.assertEqual(materialized.block_id, "b")
        self.assertEqual(materialized.revision, 3)
        self.assertIn("source=approval", materialized.content)
        self.assertEqual(materialized.byte_count, len(materialized.content.encode("utf-8")))
        self.assertEqual(len(materialized.sha256), 64)

    def test_rejects_stale_revision_and_oversized_body(self):
        block = ContextBlock("b", "short summary", "raw://b", revision=1)
        with self.assertRaises(StaleContextMaterialization):
            ContextMaterializer({"raw://b": "body"}).materialize(block, expected_revision=2)
        with self.assertRaises(ContextMaterializationBudgetExceeded):
            ContextMaterializer({"raw://b": "0123456789"}, max_bytes=4).materialize(block)

    def test_missing_source_is_bounded_failure(self):
        block = ContextBlock("b", "short summary", "raw://missing")
        with self.assertRaises(ContextSourceNotFound):
            ContextMaterializer({}).materialize(block)

    def test_callable_source_accepts_utf8_bytes(self):
        block = ContextBlock("b", "summary", "raw://b")
        materialized = ContextMaterializer(lambda ref: "中文".encode("utf-8")).materialize(block)
        self.assertEqual(materialized.content, "中文")


if __name__ == "__main__":
    unittest.main()
