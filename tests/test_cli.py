import io
import json
import tempfile
import unittest
from pathlib import Path

from jev_agent.cli import InteractiveAgent, ScriptedChooser, parse_plan_line, repl
from jev_tools import build_local_catalog


class CliTests(unittest.TestCase):
    def test_plan_parser_requires_json_object(self):
        self.assertEqual(parse_plan_line(':plan file.read {"path":"a.txt"}'),
                         ("file.read", {"path": "a.txt"}))
        with self.assertRaises(ValueError):
            parse_plan_line(':plan file.read ["a.txt"]')

    def test_repl_requires_explicit_approve_and_writes_trace(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / "note.txt").write_text("hello", encoding="utf-8")
            agent = InteractiveAgent(workspace=workspace,
                                     catalog=build_local_catalog(workspace),
                                     chooser=ScriptedChooser())
            output = io.StringIO()
            repl(agent, input_stream=io.StringIO(
                ':plan file.read {"path":"note.txt"}\n:approve\n:trace\n:quit\n'),
                output_stream=output)
            events = agent.trace
            self.assertEqual([e["event"] for e in events], ["plan", "approve"])
            self.assertEqual(events[0]["status"], "ready")
            self.assertEqual(events[1]["status"], "executed")
            self.assertTrue(agent.trace_path.exists())
            self.assertTrue(agent.trace_path.parent.name == ".jev_traces")
            self.assertIn("note.txt", output.getvalue())
            self.assertIn("hello", output.getvalue())

    def test_write_plan_does_not_execute_before_approve(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            agent = InteractiveAgent(workspace=workspace,
                                     catalog=build_local_catalog(workspace), chooser=ScriptedChooser())
            event = agent.plan("file.write", {"path": "new.txt", "text": "safe"})
            self.assertEqual(event["status"], "ready")
            self.assertFalse((workspace / "new.txt").exists())
            agent.approve()
            self.assertEqual((workspace / "new.txt").read_text(encoding="utf-8"), "safe")

    def test_goal_and_observation_revision_clear_pending(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            agent = InteractiveAgent(workspace=workspace, catalog=build_local_catalog(workspace), chooser=ScriptedChooser())
            agent.plan("file.write", {"path": "new.txt", "text": "safe"})
            revision = agent.state.revision
            repl(agent, input_stream=io.StringIO(":goal new goal\n"), output_stream=io.StringIO())
            self.assertEqual(agent.state.revision, revision + 1)
            with self.assertRaises(RuntimeError):
                agent.approve()
            agent.plan("file.write", {"path": "new.txt", "text": "safe"})
            revision = agent.state.revision
            repl(agent, input_stream=io.StringIO("new observation\n"), output_stream=io.StringIO())
            self.assertEqual(agent.state.revision, revision + 1)
            with self.assertRaises(RuntimeError):
                agent.approve()

    def test_failed_plan_cannot_approve_old_candidate_and_unknown_command_is_not_goal(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            agent = InteractiveAgent(workspace=workspace, catalog=build_local_catalog(workspace), chooser=ScriptedChooser())
            agent.plan("file.write", {"path": "new.txt", "text": "safe"})
            output = io.StringIO()
            repl(agent, input_stream=io.StringIO(":plan no.such {}\n:approve\n:wat\n"), output_stream=output)
            self.assertFalse((workspace / "new.txt").exists())
            self.assertNotIn("wat", [o for o in agent.state.observations])
            self.assertIn("unknown command", output.getvalue())

    def test_approve_consumes_pending_for_review_and_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            agent = InteractiveAgent(workspace=workspace, catalog=build_local_catalog(workspace), chooser=ScriptedChooser())
            agent.plan("human.review", {"summary": "check"})
            event = agent.approve()
            self.assertEqual(event["status"], "review_required")
            with self.assertRaises(RuntimeError):
                agent.approve()
            agent.plan("file.read", {"path": "missing.txt"})
            event = agent.approve()
            self.assertEqual(event["status"], "execution_failed")
            with self.assertRaises(RuntimeError):
                agent.approve()

    def test_trace_sessions_are_unique_and_results_are_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / "large.txt").write_text("x" * 12000, encoding="utf-8")
            a = InteractiveAgent(workspace=workspace, catalog=build_local_catalog(workspace), chooser=ScriptedChooser())
            b = InteractiveAgent(workspace=workspace, catalog=build_local_catalog(workspace), chooser=ScriptedChooser())
            self.assertNotEqual(a.trace_path, b.trace_path)
            a.plan("file.read", {"path": "large.txt"})
            event = a.approve()
            self.assertLessEqual(len(event["display_result"].encode("utf-8")), 8192)


if __name__ == "__main__":
    unittest.main()
