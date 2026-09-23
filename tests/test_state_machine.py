import unittest

from jev_agent.state_machine import DecisionTraceGraph, ErrorSummaryQueue


class StateMachineTests(unittest.TestCase):
    def test_mermaid_graph_and_conservative_compilation(self):
        graph = DecisionTraceGraph()
        for _ in range(3):
            graph.record(source="Ready", target="Done", label="execute", tool_name="file.read", success=True)
        graph.record(source="Ready", target="Retry", label="execute", tool_name="file.read", success=False, error="stale")
        mermaid = graph.to_mermaid()
        self.assertIn("stateDiagram-v2", mermaid)
        self.assertIn("file.read", mermaid)
        # The failed target contributes to the same (source, tool, label)
        # denominator; it cannot be hidden in a separate edge.
        self.assertEqual(len(graph.compile_stable()), 0)
        candidates = graph.compile_stable(min_success_rate=0.7)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].observations, 4)
        self.assertAlmostEqual(candidates[0].success_rate, 0.75)
        self.assertTrue(candidates[0].advisory)
        self.assertFalse(candidates[0].executable)

    def test_multiple_success_targets_are_not_a_deterministic_rule(self):
        graph = DecisionTraceGraph()
        for target in ("Done", "Retry"):
            for _ in range(3):
                graph.record(source="Ready", target=target, label="execute", tool_name="file.read", success=True)
        self.assertEqual(graph.compile_stable(min_success_rate=0.0), ())

    def test_schema_and_dependency_drift_is_not_exported_as_one_rule(self):
        graph = DecisionTraceGraph()
        for _ in range(3):
            graph.record(
                source="Ready",
                target="Done",
                label="execute",
                tool_name="file.read",
                schema_version="v1",
                dependency_versions={"workspace": 1},
                guard="revision == 1",
                success=True,
            )
        graph.record(
            source="Ready",
            target="Done",
            label="execute",
            tool_name="file.read",
            schema_version="v2",
            dependency_versions={"workspace": 2},
            guard="revision == 2",
            success=True,
        )
        self.assertEqual(graph.compile_stable(min_success_rate=0.0), ())

    def test_mermaid_uses_stable_ids_and_escapes_user_labels(self):
        graph = DecisionTraceGraph()
        graph.record(
            source='Ready\n"; dangerous',
            target="Done:next",
            label='run\n"; DROP',
            tool_name="tool:read",
            success=True,
        )
        mermaid = graph.to_mermaid()
        self.assertNotIn('Ready\n"; dangerous -->', mermaid)
        self.assertIn('\\n', mermaid)
        self.assertIn('\\"', mermaid)
        self.assertNotIn('state "Ready\n"; dangerous"', mermaid)

    def test_error_summary_runs_off_path_and_is_keyed(self):
        queue = ErrorSummaryQueue()
        future = queue.submit(key=("Ready", "file.read", "v1", "stale"), error="revision changed", summarizer=lambda value: f"summary:{value}")
        future.result()  # deterministic test wait; main path remains asynchronous in production
        summaries = queue.drain()
        self.assertEqual(summaries[0].text, "summary:revision changed")
        self.assertEqual(queue.for_node_or_tool(node="Ready", tool_name="file.read")[0].count, 1)
        failed = queue.submit(key=("Ready", "file.read", "v2", "stale"), error="new schema", summarizer=lambda value: (_ for _ in ()).throw(RuntimeError("broken")))
        with self.assertRaises(RuntimeError):
            failed.result()
        queue.submit(key=("Other", "other", "v1", "stale"), error="other", summarizer=lambda value: "other summary").result()
        summaries = queue.drain()
        self.assertEqual(len(summaries), 3)
        self.assertEqual(len(queue.for_node_or_tool(node="Ready", tool_name="file.read", schema_version="v1")), 1)
        self.assertEqual(len(queue.for_node_or_tool(node="Ready", tool_name="file.read", schema_version="v2")), 1)
        queue.close()


if __name__ == "__main__":
    unittest.main()
