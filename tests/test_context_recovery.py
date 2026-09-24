import unittest

from jev_agent.context_materialization import ContextMaterializer
from jev_agent.context_recovery import ContextEvidenceFallback
from jev_agent.context_residency import ContextBlock, ContextResidencyManager


class ContextEvidenceRecoveryTests(unittest.TestCase):
    def _manager(self):
        manager = ContextResidencyManager(max_working=1)
        manager.register(ContextBlock("a", "approval summary", "raw://a", revision=2))
        manager.register(ContextBlock("b", "historical approval summary", "raw://b", revision=1))
        return manager

    def test_recovers_unique_complete_marker_contract(self):
        manager = self._manager()
        fallback = ContextEvidenceFallback(
            ContextMaterializer({"raw://a": "source=approval-service; version=2",
                                 "raw://b": "source=historical"}),
            required_markers=("source=approval-service", "version=2"),
        )
        result = fallback.recover(manager, ("b", "a"), expected_revisions={"a": 2, "b": 1})
        self.assertEqual(result.status, "recovered")
        self.assertEqual(result.recovered_ids, ("a",))

    def test_stale_revision_does_not_recover(self):
        manager = self._manager()
        fallback = ContextEvidenceFallback(
            ContextMaterializer({"raw://a": "source=approval-service; version=2"}),
            required_markers=("source=approval-service",),
        )
        result = fallback.recover(manager, ("a",), expected_revisions={"a": 3})
        self.assertEqual(result.status, "no_match")
        self.assertIn("StaleContextMaterialization", result.reason)

    def test_multiple_matches_are_ambiguous(self):
        manager = self._manager()
        fallback = ContextEvidenceFallback(
            ContextMaterializer({"raw://a": "source=approval-service",
                                 "raw://b": "source=approval-service"}),
            required_markers=("source=approval-service",),
        )
        result = fallback.recover(manager, ("a", "b"))
        self.assertEqual(result.status, "ambiguous")
        self.assertEqual(set(result.recovered_ids), {"a", "b"})


if __name__ == "__main__":
    unittest.main()
