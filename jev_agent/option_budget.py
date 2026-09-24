"""Wire and decision budgets for the Virtual Option Space.

Jev's Choice API has a hard 255-option wire limit.  That limit is useful for
validation, but it is not a recommendation to show 255 competing actions to
the decision model.  This module keeps the two concerns explicit:

* a catalog page may contain at most ``max_wire_options`` logical entries;
* a decision call uses a much smaller target and reserves slots for control
  exits such as PAGE, REFINE, CLARIFY and STOP.

The helpers are deterministic and do not reorder or execute options.  They
are deliberately independent from a particular option type so ToolSpace,
MemorySpace and PredictionSpace can share the same accounting rules.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, TypeVar


T = TypeVar("T")

JEV_MAX_OPTIONS = 255
DEFAULT_CONTROL_RESERVE = 6
DEFAULT_DECISION_TARGET = 16


@dataclass(frozen=True)
class OptionCall:
    """One bounded Jev decision surface, before serialization."""

    candidates: tuple[Any, ...]
    controls: tuple[str, ...]

    @property
    def wire_count(self) -> int:
        return len(self.candidates) + len(self.controls)


@dataclass(frozen=True)
class OptionPageBudget:
    """Separate the logical catalog-page and per-call candidate budgets.

    ``max_wire_options`` is the protocol ceiling. ``decision_target`` is the
    normal number of action candidates sent in one call; it is capped by the
    space left after reserving controls.  The default is therefore a 16-way
    action decision with six exits, while a catalog page can still be aligned
    to the 255-entry wire ceiling.
    """

    max_wire_options: int = JEV_MAX_OPTIONS
    control_reserve: int = DEFAULT_CONTROL_RESERVE
    decision_target: int = DEFAULT_DECISION_TARGET

    def __post_init__(self) -> None:
        for name, value in (
            ("max_wire_options", self.max_wire_options),
            ("control_reserve", self.control_reserve),
            ("decision_target", self.decision_target),
        ):
            if isinstance(value, bool) or value < 1:
                raise ValueError(f"{name} must be positive")
        if self.control_reserve >= self.max_wire_options:
            raise ValueError("control_reserve must leave at least one action slot")

    @property
    def max_action_options(self) -> int:
        """Maximum action candidates after control exits are reserved."""

        return self.max_wire_options - self.control_reserve

    @property
    def call_action_target(self) -> int:
        return min(self.decision_target, self.max_action_options)

    def validate_call(self, action_count: int, control_count: int) -> None:
        """Reject a request that would violate the wire limit."""

        if isinstance(action_count, bool) or action_count < 0:
            raise ValueError("action_count must be non-negative")
        if isinstance(control_count, bool) or control_count < 0:
            raise ValueError("control_count must be non-negative")
        if control_count > self.control_reserve:
            raise ValueError(
                f"control_count {control_count} exceeds reserved slots {self.control_reserve}"
            )
        if action_count + control_count > self.max_wire_options:
            raise ValueError("option call exceeds the Jev wire limit")

    def catalog_pages(self, options: Iterable[T]) -> tuple[tuple[T, ...], ...]:
        """Split a logical catalog into pages aligned to the wire ceiling."""

        items = tuple(options)
        return tuple(
            items[start : start + self.max_wire_options]
            for start in range(0, len(items), self.max_wire_options)
        )

    def decision_calls(
        self,
        options: Iterable[T],
        *,
        controls: Iterable[str] = (),
    ) -> tuple[OptionCall, ...]:
        """Build stable, small calls from one logical page.

        The controls are repeated on each call because PAGE/REFINE/CLARIFY/
        STOP must remain available after a candidate batch is exhausted.  The
        candidate order is preserved and no option is silently dropped.
        """

        candidate_items = tuple(options)
        control_items = tuple(controls)
        if len(set(control_items)) != len(control_items) or any(not item for item in control_items):
            raise ValueError("controls must be non-empty and unique")
        self.validate_call(0, len(control_items))
        target = min(self.call_action_target, self.max_wire_options - len(control_items))
        if not candidate_items:
            return (OptionCall((), control_items),)
        return tuple(
            OptionCall(candidate_items[start : start + target], control_items)
            for start in range(0, len(candidate_items), target)
        )


DEFAULT_OPTION_PAGE_BUDGET = OptionPageBudget()

