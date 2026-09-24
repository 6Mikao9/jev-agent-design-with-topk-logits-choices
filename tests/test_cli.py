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
            self.assertTrue((workspace / ".jev_trace.json").exists())
            self.assertIn("note.txt", output.getvalue())

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


if __name__ == "__main__":
    unittest.main()
