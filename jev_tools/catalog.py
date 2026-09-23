from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from jev_agent.agent import ToolDefinition
from jev_agent.models import ChoiceOption


Executor = Callable[[dict[str, Any]], Any]


@dataclass(frozen=True)
class ToolSpec:
    """A Jev-visible tool contract with explicit safety metadata."""

    name: str
    description: str
    schema_version: str
    parameters_schema: dict[str, Any]
    safety: str
    available: bool
    executor: Executor

    def as_tool_definition(self) -> ToolDefinition:
        return ToolDefinition(
            self.name, self.description, self.schema_version,
            self.parameters_schema, self.executor,
        )

    def as_mcp_descriptor(self) -> dict[str, Any]:
        """Return the tool-shaped portion of an MCP ``tools/list`` result.

        This is only a data adapter. It does not open stdio/HTTP transport or
        imply that a remote MCP server is trusted.
        """
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.parameters_schema,
        }


class ToolCatalog:
    def __init__(self, specs: Iterable[ToolSpec] = ()) -> None:
        self._specs: dict[str, ToolSpec] = {}
        for spec in specs:
            self.register(spec)

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._specs:
            raise ValueError(f"duplicate tool: {spec.name}")
        self._specs[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        return self._specs[name]

    def specs(self) -> tuple[ToolSpec, ...]:
        return tuple(self._specs.values())

    def mcp_descriptors(self) -> list[dict[str, Any]]:
        """Export only executable local tools for a protocol adapter."""
        return [spec.as_mcp_descriptor() for spec in self._specs.values() if spec.available]

    def call(self, name: str, arguments: dict[str, Any]) -> Any:
        """Dispatch a local call; transport and authentication stay external."""
        spec = self.get(name)
        if not spec.available:
            raise PermissionError(f"tool is unavailable: {name}")
        return spec.executor(arguments)


def _schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object", "properties": properties,
        "required": required, "additionalProperties": False,
    }


def _stub(name: str) -> Executor:
    def unavailable(_args: dict[str, Any]) -> dict[str, str]:
        return {"status": "unavailable", "tool": name,
                "message": "No local adapter configured; no network or UI action was performed."}
    return unavailable


def _workspace_path(root: Path, relative: str) -> Path:
    # Reject absolute paths and traversal, then verify resolution to defend against
    # existing symlinks that point outside the workspace.
    raw = Path(relative)
    if raw.is_absolute() or not relative or ".." in raw.parts:
        raise ValueError("path must be a non-empty workspace-relative path without '..'")
    base = root.resolve()
    target = (base / raw).resolve(strict=False)
    if target != base and base not in target.parents:
        raise ValueError("path resolves outside workspace")
    return target


def _read_file(root: Path) -> Executor:
    def execute(args: dict[str, Any]) -> dict[str, Any]:
        path = _workspace_path(root, args["path"])
        limit = min(args.get("max_bytes", 65536), 1_000_000)
        if not path.is_file():
            raise FileNotFoundError(args["path"])
        with path.open("rb") as stream:
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError("file exceeds max_bytes")
        return {"path": args["path"], "text": data.decode("utf-8"), "bytes": len(data)}
    return execute


def _write_file(root: Path) -> Executor:
    def execute(args: dict[str, Any]) -> dict[str, Any]:
        path = _workspace_path(root, args["path"])
        data = args["text"].encode("utf-8")
        if len(data) > 1_000_000:
            raise ValueError("content exceeds 1 MB")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return {"path": args["path"], "bytes_written": len(data)}
    return execute


def _list_files(root: Path) -> Executor:
    def execute(args: dict[str, Any]) -> dict[str, Any]:
        path = _workspace_path(root, args.get("path", "."))
        if not path.is_dir():
            raise NotADirectoryError(args.get("path", "."))
        limit = min(args.get("limit", 100), 500)
        entries = []
        for item in sorted(path.iterdir(), key=lambda p: p.name.casefold()):
            entries.append({"name": item.name, "kind": "directory" if item.is_dir() else "file"})
            if len(entries) >= limit:
                break
        return {"path": args.get("path", "."), "entries": entries}
    return execute


def _json_read(root: Path) -> Executor:
    def execute(args: dict[str, Any]) -> dict[str, Any]:
        path = _workspace_path(root, args["path"])
        if path.stat().st_size > 1_000_000:
            raise ValueError("JSON file exceeds 1 MB")
        return {"path": args["path"], "value": json.loads(path.read_text(encoding="utf-8"))}
    return execute


def _json_write(root: Path) -> Executor:
    def execute(args: dict[str, Any]) -> dict[str, Any]:
        path = _workspace_path(root, args["path"])
        encoded = json.dumps(args["value"], ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
        if len(encoded) > 1_000_000:
            raise ValueError("JSON content exceeds 1 MB")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(encoded)
        return {"path": args["path"], "bytes_written": len(encoded)}
    return execute


def _shell(root: Path, allowed_commands: tuple[str, ...]) -> Executor:
    allowed = {name.casefold(): name for name in allowed_commands}

    def execute(args: dict[str, Any]) -> dict[str, Any]:
        argv = args["argv"]
        if not argv or not isinstance(argv, list) or not all(isinstance(x, str) for x in argv):
            raise ValueError("argv must be a non-empty string array")
        executable = Path(argv[0]).name.casefold()
        if executable not in allowed or Path(argv[0]).name != argv[0]:
            raise PermissionError("executable is not in the command allowlist")
        # Git is the sole built-in command and only its read-only subcommands are
        # exposed. Custom allowlists are an explicit integrator security decision.
        if executable == "git" and (len(argv) < 2 or argv[1] not in {
            "status", "diff", "log", "show", "rev-parse"
        }):
            raise PermissionError("git subcommand is not in the read-only allowlist")
        timeout = min(max(args.get("timeout_seconds", 5), 1), 15)
        cwd = _workspace_path(root, args.get("cwd", "."))
        if not cwd.is_dir():
            raise NotADirectoryError(args.get("cwd", "."))
        result = subprocess.run(
            [allowed[executable], *argv[1:]], cwd=cwd, shell=False,
            capture_output=True, text=True, timeout=timeout,
            env={"PATH": os.environ.get("PATH", ""), "LANG": "C.UTF-8"},
        )
        return {"returncode": result.returncode,
                "stdout": result.stdout[:16000], "stderr": result.stderr[:4000]}
    return execute


def build_local_catalog(
    workspace: str | Path,
    *,
    allowed_commands: tuple[str, ...] = ("git",),
) -> ToolCatalog:
    """Build the opt-in local catalog. Shell commands default to python/git only."""
    root = Path(workspace).resolve()
    if not root.is_dir():
        raise NotADirectoryError(root)
    specs = [
        ToolSpec("file.read", "Read UTF-8 text inside the workspace.", "1", _schema({
            "path": {"type": "string", "minLength": 1},
            "max_bytes": {"type": "integer", "minimum": 1, "maximum": 1000000}}, ["path"]),
            "Workspace-relative paths only; traversal/symlink escape denied; 1 MB cap.", True, _read_file(root)),
        ToolSpec("file.write", "Write UTF-8 text inside the workspace.", "1", _schema({
            "path": {"type": "string", "minLength": 1}, "text": {"type": "string"}}, ["path", "text"]),
            "Workspace-relative paths only; traversal/symlink escape denied; 1 MB cap.", True, _write_file(root)),
        ToolSpec("file.list", "List one workspace directory, sorted by name.", "1", _schema({
            "path": {"type": "string", "minLength": 1}, "limit": {"type": "integer", "minimum": 1, "maximum": 500}}, []),
            "Workspace-relative paths only; one level; max 500 entries.", True, _list_files(root)),
        ToolSpec("json.read", "Read and parse a JSON file in the workspace.", "1", _schema({
            "path": {"type": "string", "minLength": 1}}, ["path"]),
            "Workspace-relative paths only; 1 MB cap.", True, _json_read(root)),
        ToolSpec("json.write", "Serialize a JSON value to a workspace file.", "1", _schema({
            "path": {"type": "string", "minLength": 1}, "value": {}}, ["path", "value"]),
            "Workspace-relative paths only; 1 MB cap.", True, _json_write(root)),
        ToolSpec("shell.run", "Run one allowlisted executable without shell parsing.", "1", _schema({
            "argv": {"type": "array", "minItems": 1, "maxItems": 32, "items": {"type": "string", "maxLength": 4096}},
            "cwd": {"type": "string", "minLength": 1},
            "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 15}}, ["argv"]),
            f"No shell=True; argv-only; executable allowlist={','.join(allowed_commands)}; cwd in workspace; timeout <=15s.", True, _shell(root, allowed_commands)),
        ToolSpec("http.request", "HTTP request adapter placeholder; no request is sent.", "1", _schema({
            "method": {"type": "string", "enum": ["GET", "POST"]}, "url": {"type": "string", "minLength": 1},
            "headers": {"type": "object"}, "body": {"type": "string"}}, ["method", "url"]),
            "Unavailable placeholder; network disabled until explicit transport, host allowlist, and policy are configured.", False, _stub("http.request")),
        ToolSpec("browser.act", "Browser interaction abstraction placeholder; no browser is controlled.", "1", _schema({
            "action": {"type": "string", "enum": ["open", "click", "type", "snapshot"]}, "target": {"type": "string"}}, ["action"]),
            "Unavailable placeholder; requires an explicitly configured browser adapter and user-visible consent boundary.", False, _stub("browser.act")),
        ToolSpec("computer.use", "Computer-use abstraction placeholder; no desktop action is performed.", "1", _schema({
            "action": {"type": "string", "enum": ["observe", "click", "type", "key"]}, "target": {"type": "string"}}, ["action"]),
            "Unavailable placeholder; no native UI control.", False, _stub("computer.use")),
        ToolSpec("human.review", "Pause for human review of a proposed action.", "1", _schema({
            "summary": {"type": "string", "minLength": 1}, "risk": {"type": "string"}}, ["summary"]),
            "Always returns a review-required record; must not imply approval or execute downstream actions.", True,
            lambda a: {"status": "review_required", "summary": a["summary"], "risk": a.get("risk", "unspecified")} ),
        ToolSpec("control.stop", "Stop the current tool plan without side effects.", "1", _schema({
            "reason": {"type": "string", "minLength": 1}}, ["reason"]),
            "Local control signal only; executor has no external side effects.", True,
            lambda a: {"status": "stopped", "reason": a["reason"]}),
    ]
    return ToolCatalog(specs)


def catalog_as_choice_options(catalog: ToolCatalog) -> list[ChoiceOption]:
    """Stable, short option IDs help Jev's finite-token candidate selector."""
    return [ChoiceOption(
        f"tool_{index:02d}",
        f"{spec.name} — {spec.description} {'[可用]' if spec.available else '[占位/不可用]'}",
        spec,
    ) for index, spec in enumerate(catalog.specs(), start=1)]


def catalog_as_tool_definitions(catalog: ToolCatalog) -> list[ToolDefinition]:
    """Expose only locally executable contracts, omitting placeholders."""
    return [spec.as_tool_definition() for spec in catalog.specs() if spec.available]
