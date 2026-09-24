"""Partitioned context-frame budget accounting.

The controller is deliberately independent from retrieval and Jev.  It packs
already selected summaries/evidence into named regions with hard UTF-8 byte
budgets.  Regions do not silently borrow one another's budget, which makes
overflow and context churn visible in experiments.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping


REGIONS = (
    "pinned",
    "recent",
    "working",
    "evidence",
    "options",
    "trace",
)


class ContextBudgetExceeded(ValueError):
    """A required partition cannot fit its hard budget."""


@dataclass(frozen=True)
class ContextBudget:
    pinned: int = 3 * 1024
    recent: int = 4 * 1024
    working: int = 6 * 1024
    evidence: int = 6 * 1024
    options: int = 3 * 1024
    trace: int = 2 * 1024

    def __post_init__(self) -> None:
        values = {name: getattr(self, name) for name in REGIONS}
        if any(isinstance(value, bool) or value < 0 for value in values.values()):
            raise ValueError("context budgets must be non-negative integers")
        if any(type(value) is not int for value in values.values()):
            raise ValueError("context budgets must be integers")

    @property
    def total(self) -> int:
        return sum(getattr(self, name) for name in REGIONS)

    def for_region(self, region: str) -> int:
        if region not in REGIONS:
            raise ValueError(f"unknown context region: {region}")
        return getattr(self, region)


@dataclass(frozen=True)
class ContextSlice:
    region: str
    item_id: str
    text: str
    priority: float = 0.0
    required: bool = False

    @property
    def byte_count(self) -> int:
        return len(self.text.encode("utf-8"))


@dataclass(frozen=True)
class PackedContext:
    sections: dict[str, tuple[ContextSlice, ...]]
    usage: dict[str, int]
    dropped_ids: tuple[str, ...] = ()

    @property
    def total_bytes(self) -> int:
        return sum(self.usage.values())

    def as_prompt_sections(self) -> dict[str, str]:
        """Render sections without allowing dropped items back into prompt."""
        return {
            region: "\n".join(item.text for item in self.sections.get(region, ()))
            for region in REGIONS
        }


class ContextBudgetController:
    """Pack selected context slices under independent region budgets."""

    def __init__(self, budget: ContextBudget | None = None) -> None:
        self.budget = budget or ContextBudget()

    def pack(self, slices: Iterable[ContextSlice]) -> PackedContext:
        grouped: dict[str, list[ContextSlice]] = {region: [] for region in REGIONS}
        for item in slices:
            if item.region not in REGIONS:
                raise ValueError(f"unknown context region: {item.region}")
            if not item.item_id or not item.text:
                raise ValueError("context slices require item_id and text")
            if item.byte_count > self.budget.for_region(item.region):
                if item.required or item.region == "pinned":
                    raise ContextBudgetExceeded(
                        f"required {item.region} slice {item.item_id} exceeds its partition"
                    )
            grouped[item.region].append(item)

        selected: dict[str, tuple[ContextSlice, ...]] = {}
        usage: dict[str, int] = {}
        dropped: list[str] = []
        for region in REGIONS:
            limit = self.budget.for_region(region)
            used = 0
            keep: list[ContextSlice] = []
            # Stable priority ordering makes replay independent of insertion order.
            candidates = sorted(grouped[region], key=lambda item: (-item.priority, item.item_id))
            for item in candidates:
                if used + item.byte_count <= limit:
                    keep.append(item)
                    used += item.byte_count
                elif item.required or region == "pinned":
                    raise ContextBudgetExceeded(
                        f"required {region} slice {item.item_id} exceeds remaining partition budget"
                    )
                else:
                    dropped.append(item.item_id)
            selected[region] = tuple(keep)
            usage[region] = used
        return PackedContext(selected, usage, tuple(dropped))
