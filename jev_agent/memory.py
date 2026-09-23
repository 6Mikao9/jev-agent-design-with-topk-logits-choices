from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .models import DependencyIndex


@dataclass
class MemoryRecord:
    record_id: str
    text: str
    kind: str
    dependency_versions: dict[str, int] = field(default_factory=dict)
    evidence_refs: tuple[str, ...] = ()
    storage_tier: str = "L1"
    validity: str = "current"
    execution_status: str = "observed"
    impact_tags: frozenset[str] = frozenset()


class MemoryBank:
    """Append-only facts plus decision-impact-aware retrieval."""

    def __init__(self) -> None:
        self._records: dict[str, MemoryRecord] = {}

    def add(self, record: MemoryRecord) -> None:
        if record.record_id in self._records:
            raise ValueError(f"duplicate memory id: {record.record_id}")
        self._records[record.record_id] = record

    def retrieve(
        self,
        *,
        dependency_ids: Iterable[str],
        current_versions: dict[str, int],
        impact_tags: Iterable[str] = (),
        limit: int = 20,
    ) -> list[MemoryRecord]:
        dependencies = set(dependency_ids)
        tags = set(impact_tags)
        current = [
            item
            for item in self._records.values()
            if item.validity == "current"
            and all(
                current_versions.get(dep, 0) == version
                for dep, version in item.dependency_versions.items()
            )
        ]
        current.sort(
            key=lambda item: (
                bool(dependencies.intersection(item.dependency_versions)),
                bool(tags.intersection(item.impact_tags)),
                item.storage_tier == "L0",
                item.record_id,
            ),
            reverse=True,
        )
        return current[:limit]

    def invalidate_changed(
        self, current_versions: dict[str, int], changed_ids: Iterable[str]
    ) -> list[str]:
        """Invalidate records tied to old dependency versions; retain their history."""
        changed = set(changed_ids)
        invalidated: list[str] = []
        for item in self._records.values():
            if item.validity != "current":
                continue
            if changed.intersection(item.dependency_versions) or any(
                current_versions.get(dep, 0) != version
                for dep, version in item.dependency_versions.items()
            ):
                item.validity = "stale"
                invalidated.append(item.record_id)
        return invalidated

    def all_records(self) -> list[MemoryRecord]:
        return list(self._records.values())
