import unittest

from jev_agent.option_space import OptionSpace, OptionSpaceRegistry, SpaceOption


class OptionSpaceTests(unittest.TestCase):
    def test_budget_ladder_and_pagination_are_stable(self):
        space = OptionSpace(
            "ToolSpace",
            [SpaceOption(f"tool_{i}", f"tool {i}", source="history") for i in range(1, 10)],
        )
        self.assertEqual([item.option_id for item in space.visible()], ["tool_1", "tool_2"])
        self.assertEqual([item.option_id for item in space.visible(limit=4, page=1)], ["tool_5", "tool_6", "tool_7", "tool_8"])
        self.assertEqual(space.expand_limit(2), 4)
        self.assertEqual(space.expand_limit(8), None)
        self.assertEqual(space.page_count(limit=4), 3)

    def test_registry_keeps_spaces_separate(self):
        registry = OptionSpaceRegistry()
        registry.register(OptionSpace("ToolSpace"))
        registry.register(OptionSpace("MemorySpace"))
        registry.register(OptionSpace("PredictionSpace"))
        self.assertEqual(registry.ids(), ("ToolSpace", "MemorySpace", "PredictionSpace"))
        with self.assertRaises(ValueError):
            registry.register(OptionSpace("ToolSpace"))

    def test_duplicate_option_ids_are_rejected(self):
        space = OptionSpace("MemorySpace")
        space.add(SpaceOption("mem_1", "one"))
        with self.assertRaises(ValueError):
            space.add(SpaceOption("mem_1", "duplicate"))


if __name__ == "__main__":
    unittest.main()
