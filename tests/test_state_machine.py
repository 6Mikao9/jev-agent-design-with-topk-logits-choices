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
        self.assertEqual(len(graph.compile_stable()), 1)
        self.assertEqual(len(graph.compile_stable(min_success_rate=0.7)), 1)

    def test_error_summary_runs_off_path_and_is_keyed(self):
        queue = ErrorSummaryQueue()
        future = queue.submit(key=("Ready", "file.read", "v1", "stale"), error="revision changed", summarizer=lambda value: f"summary:{value}")
        future.result()  # deterministic test wait; main path remains asynchronous in production
        summaries = queue.drain()
        self.assertEqual(summaries[0].text, "summary:revision changed")
        self.assertEqual(queue.for_node_or_tool(node="Ready", tool_name="file.read")[0].count, 1)
        queue.close()


if __name__ == "__main__":
    unittest.main()
