import asyncio
import unittest

from jev_agent.diffusion import ParallelCandidateGenerator
from jev_agent.overlap import RevisionPrefetch, run_prefetch_and_tool


class OverlapDiffusionTests(unittest.TestCase):
    def test_overlap_starts_both_operations_without_serial_wait(self):
        async def run():
            started = []
            both_started = asyncio.Event()

            async def delayed(value):
                started.append(value)
                if len(started) == 2:
                    both_started.set()
                await both_started.wait()
                return value

            result = await run_prefetch_and_tool(
                prefetch=lambda: delayed("tokens"),
                tool_call=lambda: delayed("tool"),
                revision=3,
            )
            return result, started

        result, started = asyncio.run(run())
        self.assertEqual(result.prefetch, "tokens")
        self.assertEqual(result.tool, "tool")
        self.assertEqual(result.revision, 3)
        self.assertEqual(set(started), {"tokens", "tool"})

    def test_revision_prefetch_discards_stale_result(self):
        async def run():
            cache = RevisionPrefetch[str]()
            cache.start(lambda: asyncio.sleep(0, result="old"), revision=1)
            self.assertIsNone(await cache.take(revision=2))
            await cache.cancel()

        asyncio.run(run())

    def test_parallel_candidates_keep_order_and_apply_acceptance(self):
        class FakeDiffusion:
            def generate(self, *, prompt, seed, parameters):
                return f"{prompt}:{seed}:{parameters['temperature']}"

        generator = ParallelCandidateGenerator(FakeDiffusion(), max_workers=2)
        result = generator.generate(
            prompt="p",
            seeds=[1, 2, 3],
            parameter_sets=[{"temperature": 0.2}, {"temperature": 0.8}, {"temperature": 1.1}],
            accept=lambda item: item.seed != 2,
        )
        self.assertEqual([item.seed for item in result], [1, 3])
        self.assertEqual(result[0].value, "p:1:0.2")


if __name__ == "__main__":
    unittest.main()
