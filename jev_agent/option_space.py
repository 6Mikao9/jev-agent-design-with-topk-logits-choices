from __future__ import annotations

"""Finite, budgeted option spaces shared by tools, memory and proposals."""

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class SpaceOption:
    option_id: str
    description: str
    payload: Any = None
    source: str = "unknown"


class OptionSpace:
    """Stable options with 2/4/8 expansion and explicit pagination."""

    def __init__(
        self,
        space_id: str,
        options: Iterable[SpaceOption] = (),
        *,
        budget_ladder: tuple[int, ...] = (2, 4, 8),
    ) -> None:
        if not space_id:
            raise ValueError("space_id is required")
        if not budget_ladder or any(item < 1 for item in budget_ladder):
            raise ValueError("budget_ladder must contain positive limits")
        if tuple(sorted(set(budget_ladder))) != budget_ladder:
            raise ValueError("budget_ladder must be strictly increasing")
        self.space_id = space_id
        self.budget_ladder = budget_ladder
        self._options: list[SpaceOption] = []
        self._ids: set[str] = set()
        for option in options:
            self.add(option)

    def add(self, option: SpaceOption) -> None:
        if not option.option_id or option.option_id in self._ids:
            raise ValueError(f"duplicate or empty option id: {option.option_id!r}")
        self._ids.add(option.option_id)
        self._options.append(option)

    def visible(self, *, limit: int | None = None, page: int = 0) -> tuple[SpaceOption, ...]:
        """Return one page without mutating the space or reordering options."""
        if page < 0:
            raise ValueError("page must be non-negative")
        chosen_limit = limit if limit is not None else self.budget_ladder[0]
        if chosen_limit < 1:
            raise ValueError("limit must be positive")
        start = page * chosen_limit
        return tuple(self._options[start : start + chosen_limit])

    def expand_limit(self, current: int) -> int | None:
        """Return the next allowed budget, or ``None`` at the ladder ceiling."""
        for candidate in self.budget_ladder:
            if candidate > current:
                return candidate
        return None

    def page_count(self, *, limit: int | None = None) -> int:
        chosen_limit = limit if limit is not None else self.budget_ladder[0]
        if chosen_limit < 1:
            raise ValueError("limit must be positive")
        return (len(self._options) + chosen_limit - 1) // chosen_limit

    def __len__(self) -> int:
        return len(self._options)


class OptionSpaceRegistry:
    """Keep ToolSpace, MemorySpace and PredictionSpace separate by construction."""

    def __init__(self) -> None:
        self._spaces: dict[str, OptionSpace] = {}

    def register(self, space: OptionSpace) -> None:
        if space.space_id in self._spaces:
            raise ValueError(f"duplicate option space: {space.space_id}")
        self._spaces[space.space_id] = space

    def get(self, space_id: str) -> OptionSpace:
        return self._spaces[space_id]

    def ids(self) -> tuple[str, ...]:
        return tuple(self._spaces)
