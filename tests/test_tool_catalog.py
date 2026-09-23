from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jev_agent.validation import SchemaError, validate_json_schema
from jev_tools import build_local_catalog, catalog_as_choice_options, catalog_as_tool_definitions


class ToolCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.catalog = build_local_catalog(self.root)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_candidate_schema_and_short_choice_ids(self):
        options = catalog_as_choice_options(self.catalog)
        self.assertEqual(options[0].option_id, "tool_01")
        self.assertEqual(options[-1].option_id, "tool_11")
        read = self.catalog.get("file.read")
        validate_json_schema({"path": "note.txt"}, read.parameters_schema)
        with self.assertRaises(SchemaError):
            validate_json_schema({"path": "note.txt", "extra": True}, read.parameters_schema)

    def test_workspace_file_and_json_tools(self):
        write = self.catalog.get("file.write").executor
        read = self.catalog.get("file.read").executor
        write({"path": "notes/a.txt", "text": "hello"})
        self.assertEqual(read({"path": "notes/a.txt"})["text"], "hello")
        self.catalog.get("json.write").executor({"path": "data.json", "value": {"x": 1}})
        self.assertEqual(self.catalog.get("json.read").executor({"path": "data.json"})["value"], {"x": 1})
        self.assertEqual(json.loads((self.root / "data.json").read_text()), {"x": 1})

    def test_rejects_path_traversal_and_shell_injection(self):
        with self.assertRaises(ValueError):
            self.catalog.get("file.read").executor({"path": "../outside.txt"})
        shell = self.catalog.get("shell.run").executor
        with self.assertRaises(PermissionError):
            shell({"argv": ["git", "commit", "-m", "bad"]})
        with self.assertRaises(PermissionError):
            shell({"argv": ["python", "-c", "print(1)"]})

    def test_network_ui_are_visible_but_unavailable(self):
        for name in ("http.request", "browser.act", "computer.use"):
            spec = self.catalog.get(name)
            self.assertFalse(spec.available)
            self.assertEqual(spec.executor({})["status"], "unavailable")
        exposed = {item.name for item in catalog_as_tool_definitions(self.catalog)}
        self.assertNotIn("http.request", exposed)

    def test_review_and_stop_are_explicit_non_execution_signals(self):
        self.assertEqual(
            self.catalog.get("human.review").executor({"summary": "delete draft"})["status"],
            "review_required",
        )
        self.assertEqual(
            self.catalog.get("control.stop").executor({"reason": "uncertain"})["status"],
            "stopped",
        )


if __name__ == "__main__":
    unittest.main()
