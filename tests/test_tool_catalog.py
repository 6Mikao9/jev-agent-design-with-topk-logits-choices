from __future__ import annotations

import json
import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
        self.assertEqual(options[-1].option_id, "tool_14")
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
        descriptors = self.catalog.mcp_descriptors()
        self.assertIn("file.read", {item["name"] for item in descriptors})
        self.assertNotIn("http.request", {item["name"] for item in descriptors})

    def test_protocol_adapter_dispatches_only_available_tools(self):
        self.catalog.get("file.write").executor({"path": "x.txt", "text": "ok"})
        self.assertEqual(self.catalog.call("file.read", {"path": "x.txt"})["text"], "ok")
        with self.assertRaises(PermissionError):
            self.catalog.call("http.request", {"method": "GET", "url": "https://example.com"})

    def test_bounded_literal_search_and_no_symlink_traversal(self):
        (self.root / "a.txt").write_text("needle here\nother\nneedle again\n", encoding="utf-8")
        (self.root / "sub").mkdir()
        (self.root / "sub" / "b.txt").write_text("Needle\n", encoding="utf-8")
        result = self.catalog.get("file.search").executor({"text": "needle", "max_matches": 1})
        self.assertEqual(len(result["matches"]), 1)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["files_scanned"], 1)
        with tempfile.TemporaryDirectory() as external:
            outside = Path(external) / "secret.txt"
            outside.write_text("needle", encoding="utf-8")
            try:
                (self.root / "outside-link.txt").symlink_to(outside)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation is unavailable")
            result = self.catalog.get("file.search").executor({"text": "needle"})
            self.assertNotIn("outside-link.txt", {m["path"] for m in result["matches"]})

    def test_guarded_replace_directory_create_and_atomic_result(self):
        create = self.catalog.get("directory.create").executor
        self.assertTrue(create({"path": "nested/new"})["created"])
        target = self.root / "nested" / "new" / "note.txt"
        target.write_text("before target after", encoding="utf-8")
        replace = self.catalog.get("file.replace_text").executor
        result = replace({"path": "nested/new/note.txt", "old_text": "target",
                          "replacement": "updated", "expected_text": "before target after",
                          "expected_count": 1})
        self.assertEqual(result["replacements"], 1)
        self.assertEqual(target.read_text(encoding="utf-8"), "before updated after")
        self.assertEqual(result["sha256"], hashlib.sha256(target.read_bytes()).hexdigest())
        with self.assertRaises(ValueError):
            replace({"path": "nested/new/note.txt", "old_text": "before",
                     "replacement": "x", "expected_sha256": "0" * 64,
                     "expected_count": 1})
        with self.assertRaises(ValueError):
            create({"path": "../escape"})

    def test_allowlisted_command_output_is_bounded(self):
        catalog = build_local_catalog(self.root, allowed_commands=("python",),
                                      command_timeout_seconds=2, command_output_limit_bytes=4)

        class FakeProcess:
            def __init__(self, *_args, **_kwargs):
                self.stdout = io.BytesIO(b"abcdefgh")
                self.stderr = io.BytesIO(b"errormsg")
                self.returncode = 0
            def wait(self, timeout=None):
                return self.returncode
            def kill(self):
                self.returncode = -9

        with patch("jev_tools.catalog.subprocess.Popen", FakeProcess):
            result = catalog.get("shell.run").executor({"argv": ["python", "-c", "print(1)"]})
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["stdout"], "abcd")
        self.assertTrue(result["stdout_truncated"])
        self.assertEqual(result["stdout_bytes"], 8)
        with self.assertRaises(PermissionError):
            self.catalog.get("shell.run").executor({"argv": ["python", "-c", "print(1)"]})

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
