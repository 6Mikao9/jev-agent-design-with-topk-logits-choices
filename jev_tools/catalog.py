from __future__ import annotations

import json
import hashlib
import os
import tempfile
import subprocess
import threading
import signal
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from jev_agent.agent import ToolDefinition
from jev_agent.models import ChoiceOption
from jev_agent.validation import validate_json_schema


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
        validate_json_schema(arguments, spec.parameters_schema)
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
        path = _safe_write_path(root, args["path"])
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
        path = _safe_write_path(root, args["path"])
        encoded = json.dumps(args["value"], ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
        if len(encoded) > 1_000_000:
            raise ValueError("JSON content exceeds 1 MB")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(encoded)
        return {"path": args["path"], "bytes_written": len(encoded)}
    return execute


def _shell(root: Path, allowed_commands: tuple[str, ...], *, timeout_seconds: int,
           output_limit_bytes: int) -> Executor:
    allowed = {Path(name).name.casefold(): Path(name).name for name in allowed_commands}

    def execute(args: dict[str, Any]) -> dict[str, Any]:
        argv = args["argv"]
        if not argv or not isinstance(argv, list) or not all(isinstance(x, str) for x in argv):
            raise ValueError("argv must be a non-empty string array")
        if len(argv) > 64 or any(len(x) > 8192 for x in argv):
            raise ValueError("argv exceeds argument limits")
        executable = Path(argv[0]).name.casefold()
        if executable not in allowed or Path(argv[0]).name != argv[0]:
            raise PermissionError("executable is not in the command allowlist")
        # Git is the sole built-in command and only its read-only subcommands are
        # exposed. Custom allowlists are an explicit integrator security decision.
        if executable in {"git", "git.exe"} and (len(argv) < 2 or argv[1] not in {
            "status", "diff", "log", "show", "rev-parse"
        }):
            raise PermissionError("git subcommand is not in the read-only allowlist")
        if executable in {"git", "git.exe"} and any(
            a.split("=", 1)[0] in {"--output", "--ext-diff", "--textconv", "--no-index"}
            for a in argv[2:]
        ):
            raise PermissionError("git write/external execution flags are not allowed")
        timeout = min(max(args.get("timeout_seconds", timeout_seconds), 1), timeout_seconds)
        cwd = _workspace_path(root, args.get("cwd", "."))
        if not cwd.is_dir():
            raise NotADirectoryError(args.get("cwd", "."))
        # Drain both pipes concurrently while retaining only a bounded prefix.
        # This caps memory even when an allowed process emits excessive output.
        proc = subprocess.Popen(
            [allowed[executable], *argv[1:]], cwd=cwd, shell=False,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env={"PATH": os.environ.get("PATH", ""), "LANG": "C.UTF-8"},
            start_new_session=os.name != "nt",
        )
        buffers: dict[str, bytearray] = {"stdout": bytearray(), "stderr": bytearray()}
        sizes = {"stdout": 0, "stderr": 0}

        def drain(name: str, stream: Any) -> None:
            while True:
                chunk = stream.read(8192)
                if not chunk:
                    return
                sizes[name] += len(chunk)
                room = max(0, output_limit_bytes - len(buffers[name]))
                if room:
                    buffers[name].extend(chunk[:room])

        readers = [threading.Thread(target=drain, args=("stdout", proc.stdout), daemon=True),
                   threading.Thread(target=drain, args=("stderr", proc.stderr), daemon=True)]
        for reader in readers:
            reader.start()
        def kill_group() -> None:
            pid = getattr(proc, "pid", None)
            if os.name != "nt" and pid is not None:
                try:
                    os.killpg(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

        timed_out = False
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            if os.name != "nt" and getattr(proc, "pid", None) is not None:
                kill_group()
            else:
                proc.kill()
            proc.wait()
        # A child may exit while its descendants still hold a pipe open. Bound
        # collection too; in Linux Docker kill the owned process group.
        kill_group()
        for reader in readers:
            reader.join(timeout=1)
        collection_incomplete = any(reader.is_alive() for reader in readers)
        if not collection_incomplete:
            proc.stdout.close()
            proc.stderr.close()
        return {"status": "timed_out" if timed_out else "completed",
                "returncode": proc.returncode,
                "output_collection_incomplete": collection_incomplete,
                "stdout": bytes(buffers["stdout"]).decode("utf-8", errors="replace"),
                "stderr": bytes(buffers["stderr"]).decode("utf-8", errors="replace"),
                "stdout_bytes": sizes["stdout"], "stderr_bytes": sizes["stderr"],
                "stdout_truncated": sizes["stdout"] > len(buffers["stdout"]),
                "stderr_truncated": sizes["stderr"] > len(buffers["stderr"])}
    return execute


def _safe_write_path(root: Path, relative: str) -> Path:
    target = _workspace_path(root, relative)
    base = root.resolve()
    current = base
    for part in Path(relative).parts:
        current = current / part
        if current.exists() and current.is_symlink():
            raise ValueError("symlink paths are not allowed for writes")
    return target


def _mkdir(root: Path) -> Executor:
    def execute(args: dict[str, Any]) -> dict[str, Any]:
        path = _safe_write_path(root, args["path"])
        path.mkdir(parents=True, exist_ok=args.get("exist_ok", True))
        return {"path": args["path"], "created": True}
    return execute


def _search(root: Path) -> Executor:
    def execute(args: dict[str, Any]) -> dict[str, Any]:
        needle = args["text"]
        if not needle:
            raise ValueError("search text must not be empty")
        start = _safe_write_path(root, args.get("path", "."))
        if not start.exists():
            raise FileNotFoundError(args.get("path", "."))
        max_files = min(max(1, args.get("max_files", 200)), 2000)
        max_bytes = min(max(1, args.get("max_bytes", 2_000_000)), 20_000_000)
        max_matches = min(max(1, args.get("max_matches", 200)), 2000)
        case_sensitive = args.get("case_sensitive", True)
        query = needle if case_sensitive else needle.casefold()
        results: list[dict[str, Any]] = []
        files_scanned = bytes_scanned = 0
        truncated = False
        candidates: list[Path] = []
        if start.is_file() and not start.is_symlink():
            candidates = [start]
        elif start.is_dir():
            for directory, dirs, files in os.walk(start, followlinks=False):
                dirs[:] = sorted(d for d in dirs if not (Path(directory) / d).is_symlink())
                for filename in sorted(files):
                    item = Path(directory) / filename
                    if not item.is_symlink() and item.is_file():
                        candidates.append(item)
                        if len(candidates) >= max_files + 1:
                            break
                if len(candidates) >= max_files + 1:
                    break
        else:
            raise ValueError("search path must be a file or directory")
        for item in candidates:
            if files_scanned >= max_files or bytes_scanned >= max_bytes or len(results) >= max_matches:
                truncated = True
                break
            allowance = max_bytes - bytes_scanned
            with item.open("rb") as stream:
                data = stream.read(allowance + 1)
            files_scanned += 1
            bytes_scanned += min(len(data), allowance)
            if len(data) > allowance:
                truncated = True
                data = data[:allowance]
            if b"\x00" in data:
                continue
            content = data.decode("utf-8", errors="replace")
            for line_no, line in enumerate(content.splitlines(), 1):
                haystack = line if case_sensitive else line.casefold()
                if query in haystack:
                    results.append({"path": item.relative_to(root).as_posix(), "line": line_no,
                                    "text": line[:500]})
                    if len(results) >= max_matches:
                        truncated = True
                        break
        return {"matches": results, "files_scanned": files_scanned,
                "bytes_scanned": bytes_scanned, "truncated": truncated}
    return execute


_REPLACE_LOCKS: dict[str, threading.Lock] = {}
_REPLACE_LOCKS_GUARD = threading.Lock()


def _replace_text(root: Path) -> Executor:
    def execute(args: dict[str, Any]) -> dict[str, Any]:
        path = _safe_write_path(root, args["path"])
        expected_text = args.get("expected_text")
        expected_sha256 = args.get("expected_sha256")
        if (expected_text is None) == (expected_sha256 is None):
            raise ValueError("provide exactly one of expected_text or expected_sha256")
        old = args["old_text"]
        if not old:
            raise ValueError("old_text must not be empty")
        with _REPLACE_LOCKS_GUARD:
            lock = _REPLACE_LOCKS.setdefault(str(path), threading.Lock())
        with lock:
            if path.stat().st_size > 1_000_000:
                raise ValueError("file exceeds 1 MB")
            raw = path.read_bytes()
            try:
                original = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError("file must be UTF-8 text") from exc
            digest = hashlib.sha256(raw).hexdigest()
            if expected_text is not None and original != expected_text:
                raise ValueError("expected_text does not match current file")
            if expected_sha256 is not None and digest.casefold() != expected_sha256.casefold():
                raise ValueError("expected_sha256 does not match current file")
            count = original.count(old)
            if count != args["expected_count"]:
                raise ValueError(f"expected {args['expected_count']} occurrences, found {count}")
            updated = original.replace(old, args["replacement"])
            encoded = updated.encode("utf-8")
            if len(encoded) > 1_000_000:
                raise ValueError("updated file exceeds 1 MB")
            # Recheck just before atomic replacement to catch cooperating/external
            # edits during preparation. The final OS-level race window is documented.
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError("file changed during replacement")
            temp_name: str | None = None
            try:
                with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as tmp:
                    temp_name = tmp.name
                    tmp.write(encoded)
                    tmp.flush()
                    os.fsync(tmp.fileno())
                os.replace(temp_name, path)
            finally:
                if temp_name and os.path.exists(temp_name):
                    os.unlink(temp_name)
            return {"path": args["path"], "replacements": count,
                    "sha256": hashlib.sha256(encoded).hexdigest()}
    return execute


def build_local_catalog(
    workspace: str | Path,
    *,
    allowed_commands: tuple[str, ...] = ("git",),
    command_timeout_seconds: int = 10,
    command_output_limit_bytes: int = 32_000,
) -> ToolCatalog:
    """Build the opt-in local catalog. Commands default to read-only Git only."""
    root = Path(workspace).resolve()
    if not root.is_dir():
        raise NotADirectoryError(root)
    if not allowed_commands or any(not isinstance(name, str) or not name or Path(name).name != name
                                   for name in allowed_commands):
        raise ValueError("allowed_commands must contain executable basenames")
    forbidden_shells = {"sh", "bash", "zsh", "fish", "cmd", "cmd.exe", "powershell",
                        "powershell.exe", "pwsh", "pwsh.exe"}
    if any(Path(name).name.casefold() in forbidden_shells for name in allowed_commands):
        raise ValueError("shell interpreters cannot be added to allowed_commands")
    command_timeout_seconds = min(max(int(command_timeout_seconds), 1), 30)
    command_output_limit_bytes = min(max(int(command_output_limit_bytes), 1), 1_000_000)
    specs = [
        ToolSpec("file.read", "Read UTF-8 text inside the workspace.", "1", _schema({
            "path": {"type": "string", "minLength": 1},
            "max_bytes": {"type": "integer", "minimum": 1, "maximum": 1000000}}, ["path"]),
            "Workspace-relative paths only; traversal/symlink escape denied; 1 MB cap.", True, _read_file(root)),
        ToolSpec("file.write", "Write UTF-8 text inside the workspace.", "1", _schema({
            "path": {"type": "string", "minLength": 1}, "text": {"type": "string"}}, ["path", "text"]),
            "Workspace-relative path; symlink writes denied; 1 MB cap.", True, _write_file(root)),
        ToolSpec("file.list", "List one workspace directory, sorted by name.", "1", _schema({
            "path": {"type": "string", "minLength": 1}, "limit": {"type": "integer", "minimum": 1, "maximum": 500}}, []),
            "Workspace-relative paths only; one level; max 500 entries.", True, _list_files(root)),
        ToolSpec("file.search", "Search literal text in bounded UTF-8 workspace files.", "1", _schema({
            "text": {"type": "string", "minLength": 1, "maxLength": 4096},
            "path": {"type": "string", "minLength": 1},
            "case_sensitive": {"type": "boolean"},
            "max_files": {"type": "integer", "minimum": 1, "maximum": 2000},
            "max_bytes": {"type": "integer", "minimum": 1, "maximum": 20000000},
            "max_matches": {"type": "integer", "minimum": 1, "maximum": 2000}}, ["text"]),
            "Workspace only; does not descend symlink directories or read symlink files; bounded files/bytes/results.", True, _search(root)),
        ToolSpec("file.replace_text", "Replace exact text after checking current file content and occurrence count.", "1", _schema({
            "path": {"type": "string", "minLength": 1}, "old_text": {"type": "string", "minLength": 1},
            "replacement": {"type": "string"}, "expected_text": {"type": "string"},
            "expected_sha256": {"type": "string", "minLength": 64, "maxLength": 64},
            "expected_count": {"type": "integer", "minimum": 1}}, ["path", "old_text", "replacement", "expected_count"]),
            "Requires exactly one full-content guard (expected_text or SHA-256), exact count, <=1 MB; temp-file atomic replace.", True, _replace_text(root)),
        ToolSpec("directory.create", "Create a directory inside the workspace.", "1", _schema({
            "path": {"type": "string", "minLength": 1}, "exist_ok": {"type": "boolean"}}, ["path"]),
            "Workspace-relative path; symlinks denied; recursive parent creation.", True, _mkdir(root)),
        ToolSpec("json.read", "Read and parse a JSON file in the workspace.", "1", _schema({
            "path": {"type": "string", "minLength": 1}}, ["path"]),
            "Workspace-relative paths only; 1 MB cap.", True, _json_read(root)),
        ToolSpec("json.write", "Serialize a JSON value to a workspace file.", "1", _schema({
            "path": {"type": "string", "minLength": 1}, "value": {}}, ["path", "value"]),
            "Workspace-relative paths only; 1 MB cap.", True, _json_write(root)),
        ToolSpec("shell.run", "Run one allowlisted executable without shell parsing.", "1", _schema({
            "argv": {"type": "array", "minItems": 1, "maxItems": 32, "items": {"type": "string", "maxLength": 4096}},
            "cwd": {"type": "string", "minLength": 1},
            "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": command_timeout_seconds}}, ["argv"]),
            f"No shell=True; executable allowlist={','.join(allowed_commands)}; cwd in workspace; timeout <= {command_timeout_seconds}s; each output capped at {command_output_limit_bytes} bytes.", True,
            _shell(root, allowed_commands, timeout_seconds=command_timeout_seconds,
                   output_limit_bytes=command_output_limit_bytes)),
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
