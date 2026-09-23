from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Protocol


class DependencyIndex:
    """Tracks transitive invalidation from changed task or environment objects."""

    def __init__(self) -> None:
        self._dependents: dict[str, set[str]] = {}

    def register(self, object_id: str, *, depends_on: Iterable[str]) -> None:
        for dependency in depends_on:
            self._dependents.setdefault(dependency, set()).add(object_id)

    def affected_by(self, changed_ids: Iterable[str]) -> set[str]:
        affected = set(changed_ids)
        pending = list(affected)
        while pending:
            current = pending.pop()
            for dependent in self._dependents.get(current, ()):
                if dependent not in affected:
                    affected.add(dependent)
                    pending.append(dependent)
        return affected


@dataclass
class TaskState:
    task_id: str
    goal: str
    revision: int = 1
    dependency_versions: dict[str, int] = field(default_factory=dict)
    observations: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    dependency_index: DependencyIndex = field(
        default_factory=DependencyIndex, repr=False, compare=False
    )

    def register_dependency(self, object_id: str, *, depends_on: Iterable[str]) -> None:
        self.dependency_index.register(object_id, depends_on=depends_on)

    def revise(self, dependency_id: str, observation: str | None = None) -> int:
        self.revision += 1
        affected = self.dependency_index.affected_by((dependency_id,))
        for object_id in affected:
            self.dependency_versions[object_id] = (
                self.dependency_versions.get(object_id, 0) + 1
            )
        if observation:
            self.observations.append(observation)
        return self.dependency_versions[dependency_id]


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    tool_name: str
    arguments: dict[str, Any]
    source: str
    task_revision: int
    schema_version: str
    evidence_refs: tuple[str, ...] = ()
    dependency_versions: dict[str, int] = field(default_factory=dict)
    validation: str = "unchecked"
    execution_status: str = "proposed"
    storage_tier: str = "L0"
    validity: str = "current"

    def is_current(self, state: TaskState, schema_version: str) -> bool:
        if self.schema_version != schema_version:
            return False
        if not self.dependency_versions:
            return self.task_revision == state.revision
        return all(
            state.dependency_versions.get(dep, 0) == version
            for dep, version in self.dependency_versions.items()
        )


@dataclass(frozen=True)
class ChoiceOption:
    option_id: str
    description: str
    payload: Any = None


@dataclass(frozen=True)
class ChoiceResult:
    choice: str
    probabilities: dict[str, float]
    confidence: float
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0


class ChoiceBackend(Protocol):
    def choose(
        self, *, state: str, instructions: str, options: list[ChoiceOption]
    ) -> ChoiceResult: ...
