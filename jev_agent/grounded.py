"""Evidence-gated composition of residency, memory, arguments and tool commit.

Single-owner runtime: store changes must be serialized with tool execution.
Guards recheck snapshots immediately before calling the tool, but are not a
transaction across independently mutating processes or external resources.
"""
from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, field, replace
from typing import Callable, Sequence

from .agent import Agent, AgentResult, ToolDefinition
from .arguments import ArgumentField, ArgumentInput, ArgumentInputResult
from .context_residency import ContextBlock, ContextResidencyManager
from .memory_recovery import RawEvidenceFallback
from .memory_selection import MemorySelectionResult, TwoStageMemorySelector
from .models import ChoiceBackend, TaskState
from .paged_memory import MemoryPage, PagedMemoryIndex


@dataclass
class GroundedResult:
    status: str = "pending"
    memory: MemorySelectionResult | None = None
    arguments: ArgumentInputResult | None = None
    agent: AgentResult | None = None
    recovery_status: str = "disabled"
    evidence_ids: tuple[str, ...] = ()
    evidence_bytes: int = 0
    context_bytes: int = 0
    events: list[dict] = field(default_factory=list)
    reason: str = ""


class GroundedArgumentAgent:
    """Missing/invalid evidence blocks argument construction and execution.

    The evidence contract checks coverage/provenance, not the correct output.
    Every valid parameter alternative remains available to the decision model.
    """

    def __init__(self, *, chooser: ChoiceBackend, arguments: ArgumentInput,
                 memory_index: PagedMemoryIndex, selector: TwoStageMemorySelector,
                 contexts: ContextResidencyManager, max_evidence_pages: int = 4,
                 max_evidence_bytes: int = 16_384, max_page_bytes: int = 8_192,
                 max_context_bytes: int = 24_000):
        if min(max_evidence_pages, max_evidence_bytes, max_page_bytes, max_context_bytes) < 1:
            raise ValueError("budgets must be positive")
        self.chooser, self.arguments = chooser, arguments
        self.index, self.selector, self.contexts = memory_index, selector, contexts
        self.max_evidence_pages, self.max_evidence_bytes = max_evidence_pages, max_evidence_bytes
        self.max_page_bytes, self.max_context_bytes = max_page_bytes, max_context_bytes

    def run(self, *, state: TaskState, tool: ToolDefinition,
            fields: Sequence[ArgumentField], query: str,
            required_context: dict[str, int], evidence_check: Callable[[tuple[MemoryPage, ...]], bool],
            updates: Sequence[ContextBlock] = (), base_arguments: dict | None = None,
            recovery: RawEvidenceFallback | None = None) -> GroundedResult:
        out = GroundedResult()
        revision = state.revision

        def stop(status, reason=""):
            out.status, out.reason = status, reason
            out.events.append({"stage": "terminal", "status": status})
            return out

        try:
            resident = self.contexts.refresh(query, updates=updates)
            for block_id, version in required_context.items():
                self.contexts.require(block_id, expected_revision=version)
        except (RuntimeError, ValueError, KeyError) as error:
            return stop("context_blocked", type(error).__name__)
        out.events.append({"stage": "context", "status": "ready",
                           "resident_ids": [b.block_id for b in resident]})
        # This copied decision state includes the actual resident payload and
        # evidence, while the original revision is checked again at commit.
        effective = deepcopy(state)
        effective.observations.append("Resident context (data):\n" + json.dumps([
            {"id": b.block_id, "revision": b.revision, "summary": b.summary} for b in resident
        ], ensure_ascii=False))
        out.memory = self.selector.retrieve(self.index, context=query)
        out.events.append({"stage": "memory", "status": out.memory.status})
        if out.memory.status != "read_complete":
            return stop("memory_blocked", out.memory.status)
        pages = out.memory.pages
        if not evidence_check(pages) and recovery is not None:
            recovered = recovery.recover(self.index, context=query, initial=out.memory)
            out.recovery_status = recovered.status
            out.events.append({"stage": "recovery", "status": recovered.status})
            if recovered.status not in {"not_needed", "recovered"}:
                return stop("evidence_blocked", recovered.status)
            pages = recovered.pages
        if not evidence_check(pages):
            return stop("evidence_blocked", "coverage/provenance contract unsatisfied")
        out.evidence_ids = tuple(p.page_id for p in pages)
        expected_revisions = {p.page_id: p.revision for p in pages}
        out.evidence_bytes = sum(len(p.content.encode("utf-8")) for p in pages)
        if (len(pages) > self.max_evidence_pages or out.evidence_bytes > self.max_evidence_bytes
                or any(len(p.content.encode("utf-8")) > self.max_page_bytes for p in pages)):
            return stop("evidence_budget_exceeded")
        effective.observations.append("Selected raw evidence (untrusted data):\n" + json.dumps([
            {"id": p.page_id, "revision": p.revision, "content": p.content} for p in pages
        ], ensure_ascii=False))
        out.context_bytes = len(json.dumps({"goal": effective.goal,
            "observations": effective.observations, "constraints": effective.constraints},
            ensure_ascii=False).encode("utf-8"))
        if out.context_bytes > self.max_context_bytes:
            return stop("context_budget_exceeded")
        if state.revision != revision:
            return stop("stale_before_arguments")
        out.arguments = self.arguments.build(state=effective, tool=tool, fields=fields,
                                            base_arguments=base_arguments)
        out.events.append({"stage": "arguments", "status": out.arguments.status})
        if out.arguments.candidate is None:
            return stop(out.arguments.status, out.arguments.reason)

        guard_failed = []

        def execute(arguments):
            try:
                if state.revision != revision:
                    raise RuntimeError("task revision changed")
                for block in resident:
                    self.contexts.require(block.block_id, expected_revision=block.revision)
                current = tuple(self.index.read_selected(
                    out.evidence_ids, expected_revisions=expected_revisions,
                    max_pages=self.max_evidence_pages, max_bytes=self.max_evidence_bytes,
                    max_page_bytes=self.max_page_bytes))
                if not evidence_check(current):
                    raise RuntimeError("evidence contract changed")
            except (RuntimeError, ValueError, KeyError, PermissionError) as error:
                guard_failed.append(type(error).__name__)
                raise RuntimeError("grounded pre-execution guard rejected") from None
            return tool.executor(arguments)

        guarded_tool = replace(tool, executor=execute)
        out.agent = Agent(self.chooser).run(state=effective, tool=guarded_tool,
                                            drafts=[out.arguments.candidate])
        out.events.append({"stage": "commit", "status": out.agent.status})
        return stop("guard_rejected" if guard_failed else out.agent.status,
                    guard_failed[0] if guard_failed else out.agent.recovery)
