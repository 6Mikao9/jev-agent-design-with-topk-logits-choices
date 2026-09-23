"""Small composition layer for the Jev tool, memory and trace primitives.

This is deliberately a replayable vertical slice: page retrieval runs before
the existing ``Agent`` tool decision, selected page content is injected into a
copied task state, and every transition is recorded.  It does not claim to be
a full planner or a replacement for a production workflow engine.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable, Sequence

from .agent import Agent, AgentResult, ToolDefinition
from .memory_selection import MemorySelectionResult, TwoStageMemorySelector
from .models import Candidate, ChoiceBackend, TaskState
from .paged_memory import PagedMemoryIndex
from .state_machine import DecisionTraceGraph, ErrorSummary, ErrorSummaryQueue


@dataclass
class OrchestratorResult:
    status: str
    agent: AgentResult
    memory: MemorySelectionResult | None
    trace: DecisionTraceGraph
    error_summaries: tuple[ErrorSummary, ...] = ()


class JevAgentOrchestrator:
    """Compose two-stage memory, tool execution and conservative tracing."""

    def __init__(
        self,
        chooser: ChoiceBackend,
        *,
        memory_index: PagedMemoryIndex | None = None,
        memory_selector: TwoStageMemorySelector | None = None,
        trace: DecisionTraceGraph | None = None,
        error_queue: ErrorSummaryQueue | None = None,
        error_summarizer: Callable[[str], str] | None = None,
    ) -> None:
        self.chooser = chooser
        self.memory_index = memory_index
        self.memory_selector = memory_selector or (
            TwoStageMemorySelector(chooser) if memory_index is not None else None
        )
        self.trace = trace or DecisionTraceGraph()
        self.error_queue = error_queue or ErrorSummaryQueue()
        self.error_summarizer = error_summarizer or (lambda error: error)

    def run(
        self,
        *,
        state: TaskState,
        tool: ToolDefinition,
        drafts: Sequence[Candidate],
        memory_context: str = "",
        fallback_field: Sequence[str] = (),
        fallback_prefix: str = "",
        fallback_complete=None,
        fallback_prefix_valid=lambda _value: True,
        base_arguments=None,
        helper=None,
        decision_dependencies: Sequence[str] = (),
        impact_tags: Sequence[str] = (),
        fallback_dependencies: Sequence[str] = (),
    ) -> OrchestratorResult:
        memory_result: MemorySelectionResult | None = None
        effective_state = state
        if self.memory_index is not None:
            if self.memory_selector is None:
                raise RuntimeError("memory_index requires a memory_selector")
            memory_result = self.memory_selector.retrieve(
                self.memory_index, context=memory_context or state.goal
            )
            if memory_result.status == "read_complete":
                evidence = [
                    f"[{page.page_id}@r{page.revision}] {page.content}"
                    for page in memory_result.pages
                ]
                effective_state = replace(
                    state, observations=[*state.observations, *evidence]
                )
                self.trace.record(
                    source="memory",
                    target="read_complete",
                    label="read",
                    tool_name="memory.page",
                    success=True,
                )
            else:
                self.trace.record(
                    source="memory",
                    target=memory_result.status,
                    label="read",
                    tool_name="memory.page",
                    success=memory_result.status in {"no_candidates", "no_memory", "stopped"},
                    error=memory_result.reason,
                )
            if memory_result.status in {
                "clarification_required",
                "stopped",
                "context_budget_exceeded",
                "invalid_distribution",
                "read_budget_exceeded",
                "stale_selection",
                "read_denied",
            }:
                blocked_status = (
                    "clarification_required"
                    if memory_result.status == "clarification_required"
                    else "unresolved"
                )
                blocked = AgentResult(
                    blocked_status,
                    recovery=f"memory gate: {memory_result.status} {memory_result.reason}".strip(),
                )
                self.trace.record(
                    source="tool.select",
                    target=blocked_status,
                    label="blocked_by_memory",
                    tool_name=tool.name,
                    success=False,
                    error=blocked.recovery,
                    schema_version=tool.schema_version,
                    dependency_versions=effective_state.dependency_versions,
                    guard=f"task_revision == {effective_state.revision}",
                )
                return OrchestratorResult(
                    status=blocked.status,
                    agent=blocked,
                    memory=memory_result,
                    trace=self.trace,
                    error_summaries=self.error_queue.drain(),
                )

        agent_result = Agent(self.chooser).run(
            state=effective_state,
            tool=tool,
            drafts=drafts,
            fallback_field=fallback_field,
            fallback_prefix=fallback_prefix,
            fallback_complete=fallback_complete,
            fallback_prefix_valid=fallback_prefix_valid,
            base_arguments=base_arguments,
            helper=helper,
            decision_dependencies=decision_dependencies,
            impact_tags=impact_tags,
            fallback_dependencies=fallback_dependencies,
        )
        success = agent_result.status == "executed"
        self.trace.record(
            source="tool.select",
            target=agent_result.status,
            label="execute",
            tool_name=tool.name,
            success=success,
            error=agent_result.recovery if not success else "",
            schema_version=tool.schema_version,
            dependency_versions=effective_state.dependency_versions,
            guard=f"task_revision == {effective_state.revision}",
        )
        if agent_result.status == "execution_failed":
            key = ("tool.select", tool.name, tool.schema_version, agent_result.recovery)
            self.error_queue.submit(
                key=key,
                error=agent_result.recovery,
                summarizer=self.error_summarizer,
            )
        summaries = self.error_queue.drain()
        return OrchestratorResult(
            status=agent_result.status,
            agent=agent_result,
            memory=memory_result,
            trace=self.trace,
            error_summaries=summaries,
        )

    def close(self) -> None:
        self.error_queue.close()
