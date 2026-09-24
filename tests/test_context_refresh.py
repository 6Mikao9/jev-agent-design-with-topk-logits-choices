import unittest

from jev_agent.context_refresh import ContextRefreshCoordinator, ContextVerification
from jev_agent.context_residency import ContextBlock, ContextFault, ContextResidencyManager


class ContextRefreshCoordinatorTests(unittest.TestCase):
    def _manager(self):
        manager = ContextResidencyManager(max_working=1)
        manager.register(ContextBlock("goal", "global safety constraint", "raw://goal", pinned=True))
        manager.register(ContextBlock("deploy", "deploy phase current plan", "raw://deploy", phase="deploy"))
        manager.register(ContextBlock("rollback", "rollback phase recovery plan", "raw://rollback", phase="rollback"))
        return manager

    @staticmethod
    def _verifier(target):
        def verify(block, _query, _epoch):
            return ContextVerification(block.block_id, block.block_id == target,
                                       0.9 if block.block_id == target else 0.1,
                                       "synthetic")
        return verify

    def test_parallel_verification_commits_bounded_set(self):
        manager = self._manager()
        coordinator = ContextRefreshCoordinator(manager, cooldown_steps=0)
        result = coordinator.refresh("rollback", phase="rollback",
                                     verifier=self._verifier("rollback"), top_m=2, load_k=1)
        self.assertEqual(result.status, "committed")
        self.assertEqual(result.selected_ids, ("rollback",))
        self.assertEqual(manager.require("rollback").block_id, "rollback")
        self.assertEqual(len([b for b in manager.resident() if not b.pinned]), 1)

    def test_cooldown_and_phase_budget_suppress_refresh_storm(self):
        manager = self._manager()
        coordinator = ContextRefreshCoordinator(manager, cooldown_steps=2,
                                                max_refreshes_per_phase=1)
        first = coordinator.refresh("deploy", phase="deploy",
                                    verifier=self._verifier("deploy"), top_m=1, load_k=1)
        self.assertEqual(first.status, "committed")
        second = coordinator.refresh("rollback", phase="deploy",
                                     verifier=self._verifier("rollback"), top_m=1, load_k=1)
        self.assertEqual(second.status, "suppressed")
        coordinator.refresh("rollback", phase="other",
                            verifier=self._verifier("rollback"), top_m=1, load_k=1)
        third = coordinator.refresh("deploy", phase="deploy",
                                    verifier=self._verifier("deploy"), top_m=1, load_k=1)
        self.assertEqual(third.status, "suppressed")

    def test_epoch_change_rejects_verifier_results(self):
        manager = self._manager()
        coordinator = ContextRefreshCoordinator(manager, cooldown_steps=0)

        def stale_verifier(block, _query, _epoch):
            coordinator.notify_state_change()
            return ContextVerification(block.block_id, True, 1.0, "late")

        result = coordinator.refresh("deploy", phase="deploy", verifier=stale_verifier,
                                     top_m=1, load_k=1)
        self.assertEqual(result.status, "stale_epoch")
        with self.assertRaises(ContextFault):
            manager.require("deploy")

    def test_invalid_verifier_is_rejected_as_no_support(self):
        manager = self._manager()
        coordinator = ContextRefreshCoordinator(manager, cooldown_steps=0)

        def bad_verifier(block, _query, _epoch):
            return ContextVerification(block.block_id, True, 2.0, "invalid")

        result = coordinator.refresh("deploy", phase="deploy", verifier=bad_verifier,
                                     top_m=1, load_k=1)
        self.assertEqual(result.status, "no_supported_block")
        self.assertEqual(result.verifications[0].confidence, 0.0)


if __name__ == "__main__":
    unittest.main()
