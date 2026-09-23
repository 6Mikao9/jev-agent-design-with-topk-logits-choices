import unittest

from jev_agent.context_residency import ContextBlock, ContextFault, ContextResidencyManager


class ContextResidencyTests(unittest.TestCase):
    def test_pinned_working_and_cold_blocks(self):
        manager = ContextResidencyManager(max_working=2)
        manager.register(ContextBlock("goal", "hard goal", "raw://goal", kind="constraint", pinned=True))
        manager.register(ContextBlock("a", "deploy plan", "raw://a"))
        manager.register(ContextBlock("b", "deploy rollback", "raw://b"))
        manager.register(ContextBlock("c", "unrelated note", "raw://c"))
        resident = manager.rebuild("deploy")
        self.assertIn("goal", [block.block_id for block in resident])
        self.assertEqual(len([block for block in resident if not block.pinned]), 2)
        self.assertEqual(manager.require("goal").block_id, "goal")
        self.assertIn("c", [block.block_id for block in manager.cold()])

    def test_context_fault_and_hysteresis_keep_working_block(self):
        manager = ContextResidencyManager(max_working=1, hysteresis=0.5, minimum_residency_steps=2)
        manager.register(ContextBlock("a", "deploy plan", "raw://a"))
        manager.register(ContextBlock("b", "rollback plan", "raw://b"))
        manager.rebuild("deploy")
        with self.assertRaises(ContextFault):
            manager.require("b")
        manager.rebuild("rollback")
        self.assertEqual(manager.require("a").block_id, "a")
        manager.rebuild("rollback")
        self.assertEqual(manager.require("b").block_id, "b")

    def test_utility_reward_and_invalidation(self):
        manager = ContextResidencyManager(max_working=1)
        manager.register(ContextBlock("a", "deploy plan", "raw://a"))
        manager.rebuild("deploy")
        manager.mark_useful("a", 1.0)
        self.assertGreater(manager.blocks()[0].utility_score, 0)
        manager.invalidate("a")
        with self.assertRaises(ContextFault):
            manager.require("a")


if __name__ == "__main__":
    unittest.main()
