from __future__ import annotations

"""Trace graph, asynchronous error summaries, and conservative rule compilation."""

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, Callable, Iterable, Mapping


@dataclass
class TraceEdge:
    source: str
    target: str
    label: str
    tool_name: str | None = None
    success_count: int = 0
    failure_count: int = 0
    last_error: str = ""
    schema_version: str | None = None
    dependency_versions: tuple[tuple[str, Any], ...] = ()
    guard: str | None = None

    @property
    def total_count(self) -> int:
        return self.success_count + self.failure_count

    @property
    def success_rate(self) -> float:
        return self.success_count / self.total_count if self.total_count else 0.0


@dataclass(frozen=True)
class CompiledDecisionRule:
    source: str
    target: str
    tool_name: str | None
    label: str
    success_rate: float
    observations: int
    # A compiled trace is a candidate for review.  It is not safe to execute
    # without an explicit guard and the versions it was observed against.
    schema_version: str | None = None
    dependency_versions: dict[str, Any] = field(default_factory=dict)
    guard: str | None = None
    executable: bool = False
    advisory: bool = True


@dataclass(frozen=True)
class ErrorSummary:
    key: tuple[str, str, str, str]
    text: str
    count: int = 1


class ErrorSummaryQueue:
    """Run small-model error summarizers off the main decision path."""

    def __init__(self, *, max_workers: int = 1) -> None:
        self._pool = ThreadPoolExecutor(max_workers=max_workers)
        self._pending: list[tuple[Future[ErrorSummary], tuple[str, str, str, str], str]] = []
        self._summaries: dict[tuple[str, str, str, str], ErrorSummary] = {}

    def submit(
        self,
        *,
        key: tuple[str, str, str, str],
        error: str,
        summarizer: Callable[[str], str],
    ) -> Future[ErrorSummary]:
        def work() -> ErrorSummary:
            return ErrorSummary(key, summarizer(error).strip() or error)

        future = self._pool.submit(work)
        self._pending.append((future, key, error))
        return future

    def drain(self) -> tuple[ErrorSummary, ...]:
        remaining: list[tuple[Future[ErrorSummary], tuple[str, str, str, str], str]] = []
        for future, key, error in self._pending:
            if not future.done():
                remaining.append((future, key, error))
                continue
            try:
                summary = future.result()
            except Exception:
                # A malformed/custom Future must not prevent other completed
                # summaries from being merged during this drain.
                summary = ErrorSummary(key, error)
            previous = self._summaries.get(summary.key)
            self._summaries[summary.key] = ErrorSummary(
                summary.key, summary.text, (previous.count if previous else 0) + 1
            )
        self._pending = remaining
        return tuple(self._summaries.values())

    def for_node_or_tool(
        self,
        *,
        node: str,
        tool_name: str,
        schema_version: str | None = None,
    ) -> tuple[ErrorSummary, ...]:
        return tuple(
            summary
            for summary in self._summaries.values()
            if (summary.key[0] == node or summary.key[1] == tool_name)
            and (schema_version is None or summary.key[2] == schema_version)
        )

    def close(self) -> None:
        self._pool.shutdown(wait=True)


class DecisionTraceGraph:
    def __init__(self) -> None:
        self._edges: dict[
            tuple[
                str,
                str,
                str,
                str | None,
                str | None,
                tuple[tuple[str, Any], ...],
                str | None,
            ],
            TraceEdge,
        ] = {}

    def record(
        self,
        *,
        source: str,
        target: str,
        label: str,
        tool_name: str | None = None,
        success: bool,
        error: str = "",
        schema_version: str | None = None,
        dependency_versions: Mapping[str, Any] | None = None,
        guard: str | None = None,
    ) -> TraceEdge:
        dependencies = tuple(sorted((dependency_versions or {}).items(), key=lambda item: item[0]))
        # Keep trace edges distinct when the tool or schema changes.  Stable
        # compilation below deliberately aggregates these edges by
        # (source, tool, label), so a failed target cannot hide in its own edge.
        key = (source, target, label, tool_name, schema_version, dependencies, guard)
        edge = self._edges.setdefault(
            key,
            TraceEdge(
                source,
                target,
                label,
                tool_name,
                schema_version=schema_version,
                dependency_versions=dependencies,
                guard=guard,
            ),
        )
        if success:
            edge.success_count += 1
        else:
            edge.failure_count += 1
            edge.last_error = error
        return edge

    def edges(self) -> tuple[TraceEdge, ...]:
        return tuple(self._edges.values())

    def to_mermaid(self, *, include_errors: bool = True) -> str:
        lines = ["stateDiagram-v2"]
        node_names = sorted({name for edge in self._edges.values() for name in (edge.source, edge.target)})
        node_ids = {
            name: "n_" + sha256(name.encode("utf-8")).hexdigest()[:12]
            for name in node_names
        }
        for name in node_names:
            lines.append(f'    state "{_mermaid_escape(name)}" as {node_ids[name]}')
        for edge in self._edges.values():
            label = edge.label
            if edge.tool_name:
                label = f"{edge.tool_name}: {label}"
            if include_errors and edge.failure_count:
                label += f" (ok {edge.success_count}/fail {edge.failure_count})"
            lines.append(
                f'    {node_ids[edge.source]} --> {node_ids[edge.target]}: "{_mermaid_escape(label)}"'
            )
        return "\n".join(lines) + "\n"

    def compile_stable(
        self, *, min_observations: int = 3, min_success_rate: float = 0.99
    ) -> tuple[CompiledDecisionRule, ...]:
        """Return advisory candidates aggregated across every target.

        Results are grouped by ``(source, tool, label)``.  A candidate is only
        emitted when that action has one unambiguous successful target; all
        targets and failures still contribute to its denominator.  The result
        carries version/dependency/guard metadata but is never executable by
        itself (``executable`` remains false unless a caller explicitly wraps
        it with its own guard and validation).
        """
        if min_observations < 1 or not 0.0 <= min_success_rate <= 1.0:
            raise ValueError("invalid compilation thresholds")
        grouped: dict[tuple[str, str | None, str], list[TraceEdge]] = {}
        for edge in self._edges.values():
            grouped.setdefault((edge.source, edge.tool_name, edge.label), []).append(edge)

        candidates: list[CompiledDecisionRule] = []
        for (source, tool_name, label), edges in grouped.items():
            observations = sum(edge.total_count for edge in edges)
            successes = sum(edge.success_count for edge in edges)
            if observations < min_observations or successes / observations < min_success_rate:
                continue
            metadata = [
                (edge.schema_version, edge.dependency_versions, edge.guard)
                for edge in edges
            ]
            if any(item != metadata[0] for item in metadata[1:]):
                # Version or dependency drift must be reviewed before a
                # candidate can be associated with one execution context.
                continue
            successful_targets = {edge.target for edge in edges if edge.success_count}
            if len(successful_targets) != 1:
                # A rule with two successful destinations is ambiguous even
                # when its aggregate success rate is 100%.
                continue
            target = next(iter(successful_targets))
            winning = next(edge for edge in edges if edge.target == target and edge.success_count)
            candidates.append(
                CompiledDecisionRule(
                    source,
                    target,
                    tool_name,
                    label,
                    successes / observations,
                    observations,
                    winning.schema_version,
                    dict(winning.dependency_versions),
                    winning.guard,
                )
            )
        return tuple(candidates)


def _mermaid_escape(value: str) -> str:
    """Escape user-controlled Mermaid labels without allowing new syntax."""
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", "\\r")
        .replace("\n", "\\n")
    )
