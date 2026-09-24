"""A small, synchronous DecisionModel runtime loop.

The older orchestrator remains available as a compatibility vertical slice.
This module is the first shared loop for option residency, context residency,
typed decision validation, execution, faults, revision guards, and trace.  It
is deliberately bounded and synchronous; asynchronous materialization and a
learned governor remain separate experiments.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Sequence

from .context_residency import ContextBlock, ContextFault, ContextResidencyManager
from .decision_model import DecisionModel, DecisionRequest
from .models import ChoiceOption, ChoiceResult, TaskState, validate_choice_result
from .state_machine import DecisionTraceGraph
from .virtual_option import (
    OptionFault,
    RefineFault,
    StaleVirtualOption,
    VirtualOption,
    VirtualOptionManager,
)


CONTROL_DESCRIPTIONS = {
    "CLARIFY": "The task is ambiguous; ask the user for clarification.",
    "STOP": "Stop without committing an option.",
    "CONTEXT_FAULT": "The current resident context is insufficient; refresh it.",
}


@dataclass
class RuntimeState:
    """Mutable state owned by one bounded runtime session."""

    task: TaskState
    option_manager: VirtualOptionManager
    context_manager: ContextResidencyManager | None = None
    trace: DecisionTraceGraph | None = None
    step: int = 0


@dataclass(frozen=True)
class RuntimeStepResult:
    step: int
    status: str
    choice: str
    decision: ChoiceResult | None = None
    option_id: str | None = None
    context_ids: tuple[str, ...] = ()
    resident_option_ids: tuple[str, ...] = ()
    faults: tuple[str, ...] = ()
    tool_result: Any = None
    reason: str = ""


class DecisionRuntime:
    """Coordinate one bounded DecisionModel step without hidden oracle state."""

    def __init__(
        self,
        decision_model: DecisionModel,
        *,
        option_manager: VirtualOptionManager | None = None,
        context_manager: ContextResidencyManager | None = None,
        trace: DecisionTraceGraph | None = None,
        max_options: int = 255,
        max_page_attempts: int = 2,
    ) -> None:
        if isinstance(max_options, bool) or max_options < 2:
            raise ValueError("max_options must be at least two")
        if isinstance(max_page_attempts, bool) or max_page_attempts < 1:
            raise ValueError("max_page_attempts must be positive")
        self.decision_model = decision_model
        self.option_manager = option_manager or VirtualOptionManager()
        self.context_manager = context_manager
        self.trace = trace or DecisionTraceGraph()
        self.max_options = max_options
        self.max_page_attempts = max_page_attempts
        self._page_attempts: dict[tuple[str, int, str, int], int] = {}
        self._step = 0

    @staticmethod
    def _state_text(task: TaskState, contexts: Sequence[ContextBlock]) -> str:
        observations = "\n".join(task.observations[-8:]) or "(none)"
        constraints = "\n".join(task.constraints[-8:]) or "(none)"
        context_text = "\n".join(
            f"[{block.block_id}@r{block.revision}] {block.summary}" for block in contexts
        ) or "(none)"
        return (
            f"Goal: {task.goal}\nTask revision: {task.revision}\n"
            f"Constraints:\n{constraints}\nObservations:\n{observations}\n"
            f"Resident context:\n{context_text}"
        )

    def _options(
        self,
        *,
        task: TaskState,
        page_ids: Iterable[str],
        refinements: Mapping[str, Sequence[VirtualOption]],
    ) -> list[ChoiceOption]:
        options = [
            ChoiceOption(item.option_id, item.description, item)
            for item in self.option_manager.resident_options()
        ]
        resident_ids = {item.option_id for item in self.option_manager.resident_options()}
        for page_id in dict.fromkeys(page_ids):
            page = self.option_manager.page(page_id)
            page_revision = page.revision if page is not None else 0
            if page is not None:
                # A page that is already fully resident is no longer a useful
                # recovery action.  Hiding it prevents deterministic or weak
                # backends from repeatedly paging the same page forever.
                if all(item.option_id in resident_ids for item in page.options):
                    continue
            attempts = self._page_attempts.get((task.task_id, task.revision, page_id, page_revision), 0)
            if attempts >= self.max_page_attempts:
                continue
            options.append(
                ChoiceOption(f"PAGE:{page_id}", f"Materialize virtual option page {page_id}.")
            )
        for parent_id in refinements:
            if parent_id in resident_ids:
                options.append(
                    ChoiceOption(f"REFINE:{parent_id}", f"Refine resident option {parent_id}.")
                )
        if self.context_manager is not None:
            options.append(ChoiceOption("CONTEXT_FAULT", CONTROL_DESCRIPTIONS["CONTEXT_FAULT"]))
        options.extend(ChoiceOption(key, value) for key, value in CONTROL_DESCRIPTIONS.items() if key != "CONTEXT_FAULT")
        if len(options) > self.max_options:
            raise OptionFault(f"runtime decision surface has {len(options)} options; max is {self.max_options}")
        return options

    def step(
        self,
        *,
        task: TaskState,
        instructions: str,
        query: str = "",
        page_ids: Iterable[str] = (),
        refinements: Mapping[str, Sequence[VirtualOption]] | None = None,
        context_updates: Iterable[ContextBlock] = (),
        phase: str | None = None,
        execute: Callable[[VirtualOption], Any] | None = None,
    ) -> RuntimeStepResult:
        """Run one decision and one bounded state transition.

        A PAGE/REFINE action changes only the virtual option manager.  A
        resident option can be committed and optionally executed by the
        caller's side-effect function.  All faults are returned and traced,
        never silently converted into a different option.
        """
        self._step += 1
        contexts: tuple[ContextBlock, ...] = ()
        if self.context_manager is not None:
            contexts = self.context_manager.refresh(
                query or task.goal, updates=context_updates, phase=phase
            )
        refinements = refinements or {}
        options = self._options(task=task, page_ids=page_ids, refinements=refinements)
        request_revision = task.revision
        request = DecisionRequest(
            state=self._state_text(task, contexts),
            instructions=instructions,
            options=tuple(options),
            context=tuple(block.summary for block in contexts),
            revision=task.revision,
        )
        try:
            decision = validate_choice_result(self.decision_model.decide(request), options)
        except Exception as error:
            reason = f"decision validation failed: {error}"
            self.trace.record(
                source="runtime",
                target="FAULT",
                label="decision",
                success=False,
                error=reason,
                guard=f"task_revision == {task.revision}",
            )
            return RuntimeStepResult(
                self._step, "fault", "", context_ids=tuple(block.block_id for block in contexts),
                resident_option_ids=tuple(item.option_id for item in self.option_manager.resident_options()),
                faults=(reason,), reason=reason,
            )

        choice = decision.choice
        resident_ids = tuple(item.option_id for item in self.option_manager.resident_options())
        context_ids = tuple(block.block_id for block in contexts)
        try:
            if choice.startswith("PAGE:"):
                page_id = choice.removeprefix("PAGE:")
                page = self.option_manager.page(page_id)
                key = (task.task_id, task.revision, page_id, page.revision if page is not None else 0)
                attempts = self._page_attempts.get(key, 0)
                if attempts >= self.max_page_attempts:
                    raise OptionFault(f"page retry budget exhausted: {page_id}")
                self._page_attempts[key] = attempts + 1
                self.option_manager.page_in(page_id)
                status = "paged"
                self.trace.record(source="runtime", target="PAGE", label=page_id, success=True)
                return RuntimeStepResult(self._step, status, choice, decision,
                                         context_ids=context_ids,
                                         resident_option_ids=tuple(item.option_id for item in self.option_manager.resident_options()))
            if choice.startswith("REFINE:"):
                parent_id = choice.removeprefix("REFINE:")
                children = refinements.get(parent_id)
                if not children:
                    raise RefineFault(f"no refinement supplied for parent: {parent_id}")
                self.option_manager.refine(parent_id, children)
                self.trace.record(source="runtime", target="REFINE", label=parent_id, success=True)
                return RuntimeStepResult(self._step, "refined", choice, decision,
                                         option_id=parent_id, context_ids=context_ids,
                                         resident_option_ids=tuple(item.option_id for item in self.option_manager.resident_options()))
            if choice == "CONTEXT_FAULT":
                refreshed = self.context_manager.refresh(query or task.goal, updates=context_updates, phase=phase) if self.context_manager else ()
                self.trace.record(source="runtime", target="CONTEXT_REFRESH", label="context", success=True)
                return RuntimeStepResult(self._step, "context_refreshed", choice, decision,
                                         context_ids=tuple(block.block_id for block in refreshed),
                                         resident_option_ids=resident_ids)
            if choice in {"CLARIFY", "STOP"}:
                status = "clarification_required" if choice == "CLARIFY" else "stopped"
                self.trace.record(source="runtime", target=status, label=choice, success=True)
                return RuntimeStepResult(self._step, status, choice, decision,
                                         context_ids=context_ids, resident_option_ids=resident_ids)

            # ``TaskState.revision`` guards the decision snapshot; it is not
            # the same namespace as a VirtualOption's page revision.  Compare
            # the task snapshot separately and let the manager validate the
            # option/page revision it owns.
            if task.revision != request_revision:
                raise StaleVirtualOption(
                    f"task revision changed during decision: expected {request_revision}, got {task.revision}"
                )
            selected = self.option_manager.resolve(choice)
            tool_result = execute(selected) if execute is not None else None
            status = "executed" if execute is not None else "committed"
            self.trace.record(source="runtime", target=status, label=choice, success=True)
            return RuntimeStepResult(self._step, status, choice, decision,
                                     option_id=choice, context_ids=context_ids,
                                     resident_option_ids=resident_ids, tool_result=tool_result)
        except (OptionFault, RefineFault, StaleVirtualOption, ContextFault) as error:
            reason = str(error)
            self.trace.record(source="runtime", target="FAULT", label=choice,
                              success=False, error=reason,
                              guard=f"task_revision == {task.revision}")
            return RuntimeStepResult(self._step, "fault", choice, decision,
                                     context_ids=context_ids, resident_option_ids=resident_ids,
                                     faults=(type(error).__name__,), reason=reason)
