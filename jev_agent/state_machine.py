from __future__ import annotations

"""Trace graph, asynchronous error summaries, and conservative rule compilation."""

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Iterable


@dataclass
class TraceEdge:
    source: str
    target: str
    label: str
    tool_name: str | None = None
    success_count: int = 0
    failure_count: int = 0
    last_error: str = ""

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


@dataclass(frozen=True)
class ErrorSummary:
    key: tuple[str, str, str, str]
    text: str
    count: int = 1


class ErrorSummaryQueue:
    """Run small-model error summarizers off the main decision path."""

    def __init__(self, *, max_workers: int = 1) -> None:
        self._pool = ThreadPoolExecutor(max_workers=max_workers)
        self._pending: list[Future[ErrorSummary]] = []
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
        self._pending.append(future)
        return future

    def drain(self) -> tuple[ErrorSummary, ...]:
        remaining: list[Future[ErrorSummary]] = []
        for future in self._pending:
            if not future.done():
                remaining.append(future)
                continue
            summary = future.result()
            previous = self._summaries.get(summary.key)
            self._summaries[summary.key] = ErrorSummary(
                summary.key, summary.text, (previous.count if previous else 0) + 1
            )
        self._pending = remaining
        return tuple(self._summaries.values())

    def for_node_or_tool(self, *, node: str, tool_name: str) -> tuple[ErrorSummary, ...]:
        return tuple(
            summary
            for summary in self._summaries.values()
            if summary.key[0] == node or summary.key[1] == tool_name
        )

    def close(self) -> None:
        self._pool.shutdown(wait=True)


class DecisionTraceGraph:
    def __init__(self) -> None:
        self._edges: dict[tuple[str, str, str], TraceEdge] = {}

    def record(
        self,
        *,
        source: str,
        target: str,
        label: str,
        tool_name: str | None = None,
        success: bool,
        error: str = "",
    ) -> TraceEdge:
        key = (source, target, label)
        edge = self._edges.setdefault(key, TraceEdge(source, target, label, tool_name))
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
        for edge in self._edges.values():
            label = edge.label.replace('"', "'")
            if edge.tool_name:
                label = f"{edge.tool_name}: {label}"
            if include_errors and edge.failure_count:
                label += f" (ok {edge.success_count}/fail {edge.failure_count})"
            lines.append(f'    {edge.source} --> {edge.target}: {label}')
        return "\n".join(lines) + "\n"

    def compile_stable(
        self, *, min_observations: int = 3, min_success_rate: float = 0.99
    ) -> tuple[CompiledDecisionRule, ...]:
        """Compile only well-observed, nearly error-free edges."""
        if min_observations < 1 or not 0.0 <= min_success_rate <= 1.0:
            raise ValueError("invalid compilation thresholds")
        return tuple(
            CompiledDecisionRule(
                edge.source,
                edge.target,
                edge.tool_name,
                edge.label,
                edge.success_rate,
                edge.total_count,
            )
            for edge in self._edges.values()
            if edge.total_count >= min_observations and edge.success_rate >= min_success_rate
        )
