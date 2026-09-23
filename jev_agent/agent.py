from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Any, Callable, Sequence

from .memory import MemoryBank
from .models import Candidate, ChoiceBackend, ChoiceOption, TaskState
from .topk import LogitsBackend, TopKBuilder
from .validation import SchemaError, validate_json_schema


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    schema_version: str
    parameters_schema: dict[str, Any]
    executor: Callable[[dict[str, Any]], Any]


@dataclass
class AgentResult:
    status: str
    candidate: Candidate | None = None
    tool_result: Any = None
    recovery: str = ""
    choice_calls: int = 0
    helper_calls: int = 0
    memory_ids: tuple[str, ...] = ()


class Agent:
    """First vertical slice: choose, validate, optionally construct, execute."""

    RECOVERY = {
        "FALLBACK_TOPK": "Reject the drafts and construct the missing field using helper logits Top-k.",
        "REPROPOSE": "Generate a fresh set of complete call proposals.",
        "LOOKUP": "Query an environment tool for a missing fact.",
        "CLARIFY": "Ask the user for a missing or ambiguous requirement.",
        "STOP_UNRESOLVED": "Stop without executing and report the unresolved task.",
    }

    def __init__(
        self,
        chooser: ChoiceBackend,
        *,
        topk: TopKBuilder | None = None,
        memory: MemoryBank | None = None,
    ) -> None:
        self.chooser = chooser
        self.topk = topk
        self.memory = memory

    def run(
        self,
        *,
        state: TaskState,
        tool: ToolDefinition,
        drafts: Sequence[Candidate],
        fallback_field: Sequence[str] = (),
        fallback_prefix: str = "",
        fallback_complete: Callable[[str], bool] | None = None,
        fallback_prefix_valid: Callable[[str], bool] = lambda _value: True,
        base_arguments: dict[str, Any] | None = None,
        helper: LogitsBackend | None = None,
        decision_dependencies: Sequence[str] = (),
        impact_tags: Sequence[str] = (),
        fallback_dependencies: Sequence[str] = (),
    ) -> AgentResult:
        task_revision = state.revision
        schema_version = tool.schema_version
        dependency_versions = (
            {
                dependency: state.dependency_versions.get(dependency, 0)
                for dependency in fallback_dependencies
            }
            if fallback_dependencies
            else dict(state.dependency_versions)
        )
        fallback_versions = {
            dependency: state.dependency_versions.get(dependency, 0)
            for dependency in fallback_dependencies
        }
        memory_records = []
        if self.memory is not None:
            self.memory.invalidate_changed(
                current_versions=state.dependency_versions, changed_ids=()
            )
            if decision_dependencies or impact_tags:
                memory_records = self.memory.retrieve(
                    dependency_ids=decision_dependencies,
                    current_versions=state.dependency_versions,
                    impact_tags=impact_tags,
                )
        memory_ids = tuple(record.record_id for record in memory_records)
        memory_context = "\n".join(
            f"[{record.kind}; {record.record_id}] {record.text}"
            for record in memory_records
        )
        valid: list[Candidate] = []
        for candidate in drafts:
            if candidate.tool_name != tool.name or not candidate.is_current(state, tool.schema_version):
                continue
            try:
                validate_json_schema(candidate.arguments, tool.parameters_schema)
            except SchemaError:
                continue
            valid.append(candidate)

        options = [
            ChoiceOption(
                candidate.candidate_id,
                f"Use this {candidate.tool_name} call with arguments {candidate.arguments!r}",
                candidate,
            )
            for candidate in valid
        ]
        controls = dict(self.RECOVERY)
        if (
            (self.topk is None and helper is None)
            or not fallback_field
            or fallback_complete is None
        ):
            controls.pop("FALLBACK_TOPK")
        options.extend(ChoiceOption(key, value) for key, value in controls.items())
        decision = self.chooser.choose(
            state=(
                f"Goal: {state.goal}\nObservations: {state.observations}\n"
                f"Constraints: {state.constraints}\nTask revision: {state.revision}\n"
                f"Relevant current memories:\n{memory_context}"
            ),
            instructions="Choose a valid call proposal or the recovery action that fits the task state.",
            options=options,
        )

        chosen = next((item.payload for item in options if item.option_id == decision.choice), None)
        if isinstance(chosen, Candidate):
            if not chosen.is_current(state, tool.schema_version):
                return AgentResult(
                    "stale_before_execution",
                    candidate=chosen,
                    recovery="task or schema changed after selection",
                    choice_calls=1,
                    memory_ids=memory_ids,
                )
            try:
                validate_json_schema(chosen.arguments, tool.parameters_schema)
            except SchemaError as exc:
                return AgentResult(
                    "invalid_after_choice",
                    candidate=chosen,
                    recovery=str(exc),
                    choice_calls=1,
                    memory_ids=memory_ids,
                )
            try:
                result = tool.executor(deepcopy(chosen.arguments))
            except Exception as exc:
                failed = replace(chosen, validation="passed", execution_status="failed")
                return AgentResult(
                    "execution_failed",
                    failed,
                    recovery=str(exc),
                    choice_calls=1,
                    memory_ids=memory_ids,
                )
            executed = replace(chosen, validation="passed", execution_status="executed")
            return AgentResult(
                "executed", executed, result, choice_calls=1, memory_ids=memory_ids
            )

        if decision.choice == "FALLBACK_TOPK":
            if not fallback_field:
                return AgentResult("unresolved", recovery="no fallback field was configured", choice_calls=1)
            if fallback_complete is None:
                return AgentResult(
                    "unresolved",
                    recovery="Top-k fallback requires an explicit field completion predicate",
                    choice_calls=1,
                    memory_ids=memory_ids,
                )
            builder = self.topk or TopKBuilder(helper=helper, chooser=self.chooser)  # type: ignore[arg-type]
            generated = builder.construct(
                context=(
                    f"Goal: {state.goal}\nObservations: {state.observations}\n"
                    f"Constraints: {state.constraints}\nRelevant current memories:\n"
                    f"{memory_context}\nTool: {tool.name}\n"
                    f"Field: {'.'.join(fallback_field)}"
                ),
                prefix=fallback_prefix,
                complete=fallback_complete,
                prefix_valid=fallback_prefix_valid,
            )
            if generated.status != "complete":
                return AgentResult(
                    generated.status,
                    recovery=generated.reason,
                    choice_calls=1 + generated.choice_calls,
                    helper_calls=generated.helper_calls,
                    memory_ids=memory_ids,
                )
            dependencies_changed = (
                any(
                    state.dependency_versions.get(dependency, 0) != version
                    for dependency, version in fallback_versions.items()
                )
                if fallback_dependencies
                else state.revision != task_revision
            )
            if dependencies_changed or tool.schema_version != schema_version:
                return AgentResult(
                    "stale_before_execution",
                    recovery="a fallback dependency or tool schema changed during Top-k construction",
                    choice_calls=1 + generated.choice_calls,
                    helper_calls=generated.helper_calls,
                    memory_ids=memory_ids,
                )
            arguments: dict[str, Any] = deepcopy(base_arguments or {})
            target = arguments
            for name in fallback_field[:-1]:
                if not isinstance(target.get(name), dict):
                    target[name] = {}
                target = target[name]
            target[fallback_field[-1]] = generated.value
            try:
                validate_json_schema(arguments, tool.parameters_schema)
            except SchemaError as exc:
                return AgentResult(
                    "invalid_after_fallback",
                    recovery=str(exc),
                    choice_calls=1 + generated.choice_calls,
                    helper_calls=generated.helper_calls,
                    memory_ids=memory_ids,
                )
            candidate = Candidate(
                candidate_id=f"topk-{state.task_id}-{state.revision}",
                tool_name=tool.name,
                arguments=arguments,
                source="topk_fallback",
                task_revision=task_revision,
                schema_version=schema_version,
                dependency_versions=dependency_versions,
                validation="passed",
                execution_status="selected",
            )
            try:
                result = tool.executor(deepcopy(arguments))
            except Exception as exc:
                candidate = replace(candidate, execution_status="failed")
                return AgentResult(
                    "execution_failed",
                    candidate,
                    recovery=str(exc),
                    choice_calls=1 + generated.choice_calls,
                    helper_calls=generated.helper_calls,
                    memory_ids=memory_ids,
                )
            candidate = replace(candidate, execution_status="executed")
            return AgentResult(
                "executed",
                candidate,
                result,
                choice_calls=1 + generated.choice_calls,
                helper_calls=generated.helper_calls,
                memory_ids=memory_ids,
            )

        statuses = {
            "REPROPOSE": "repropose",
            "LOOKUP": "lookup_required",
            "CLARIFY": "clarification_required",
            "STOP_UNRESOLVED": "unresolved",
        }
        return AgentResult(
            statuses.get(decision.choice, "unresolved"),
            recovery=decision.choice,
            choice_calls=1,
            memory_ids=memory_ids,
        )
