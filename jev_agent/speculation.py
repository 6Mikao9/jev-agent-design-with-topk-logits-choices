"""Revision-guarded shadow preparation for virtual option-space transitions.

The first version is intentionally synchronous and read-only.  It models the
correct ownership boundary needed by an asynchronous implementation: prepared
pages live outside ``VirtualOptionManager`` until the caller commits the parent
transition.  It does not execute tools and does not treat Jev's distribution as
a page probability without an explicit predictor.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

from .virtual_option import OptionFault, OptionPage, StaleVirtualOption, VirtualOption, VirtualOptionManager


@dataclass(frozen=True)
class ShadowPage:
    page_id: str
    base_revision: int
    page_revision: int
    options: tuple[VirtualOption, ...]
    prepare_cost_ms: float = 0.0


@dataclass(frozen=True)
class SpeculationEvent:
    event: str
    page_id: str
    base_revision: int
    cost_ms: float = 0.0
    reason: str = ""


class SpeculationBuffer:
    """Bounded shadow pages which can be promoted only after a real commit."""

    def __init__(self, *, max_pages: int = 2, max_options: int = 32) -> None:
        if isinstance(max_pages, bool) or max_pages < 1:
            raise ValueError("max_pages must be positive")
        if isinstance(max_options, bool) or max_options < 1:
            raise ValueError("max_options must be positive")
        self.max_pages = max_pages
        self.max_options = max_options
        self._pages: dict[str, ShadowPage] = {}
        self.events: list[SpeculationEvent] = []

    def prepared(self) -> tuple[ShadowPage, ...]:
        return tuple(deepcopy(tuple(self._pages.values())))

    def clear(self, *, reason: str = "cancelled") -> None:
        for page in tuple(self._pages.values()):
            self.events.append(SpeculationEvent("discard", page.page_id, page.base_revision,
                                                page.prepare_cost_ms, reason))
        self._pages.clear()

    def prefetch(
        self,
        manager: VirtualOptionManager,
        ranked_page_ids: Sequence[str],
        *,
        base_revision: int,
        limit: int | None = None,
        prepare_cost_ms: Callable[[OptionPage], float] | None = None,
    ) -> tuple[ShadowPage, ...]:
        """Copy at most ``max_pages`` pages without changing manager residency."""
        if isinstance(base_revision, bool) or base_revision < 1:
            raise ValueError("base_revision must be positive")
        self.clear(reason="replaced")
        seen: set[str] = set()
        for page_id in ranked_page_ids:
            if page_id in seen or len(self._pages) >= self.max_pages:
                continue
            seen.add(page_id)
            page = next((item for item in manager.pages() if item.page_id == page_id), None)
            if page is None:
                self.events.append(SpeculationEvent("skip", page_id, base_revision,
                                                    reason="unknown_page"))
                continue
            selected = page.options if limit is None else page.options[:limit]
            if len(selected) > self.max_options:
                self.events.append(SpeculationEvent("skip", page_id, base_revision,
                                                    reason="option_budget"))
                continue
            cost = float(prepare_cost_ms(page)) if prepare_cost_ms else 0.0
            if cost < 0:
                raise ValueError("prepare cost must be non-negative")
            shadow = ShadowPage(page.page_id, base_revision, page.revision,
                                tuple(deepcopy(selected)), cost)
            self._pages[page_id] = shadow
            self.events.append(SpeculationEvent("prepared", page_id, base_revision, cost))
        return self.prepared()

    def promote(
        self,
        manager: VirtualOptionManager,
        page_id: str,
        *,
        current_revision: int,
        limit: int | None = None,
    ) -> tuple[VirtualOption, ...]:
        shadow = self._pages.get(page_id)
        if shadow is None:
            raise OptionFault(f"page was not prepared: {page_id}")
        if current_revision != shadow.base_revision:
            self._pages.pop(page_id, None)
            self.events.append(SpeculationEvent("discard", page_id, shadow.base_revision,
                                                shadow.prepare_cost_ms, "state_revision_changed"))
            raise StaleVirtualOption(f"speculation is stale for state revision {current_revision}")
        page = next((item for item in manager.pages() if item.page_id == page_id), None)
        if page is None or page.revision != shadow.page_revision:
            self._pages.pop(page_id, None)
            self.events.append(SpeculationEvent("discard", page_id, shadow.base_revision,
                                                shadow.prepare_cost_ms, "page_revision_changed"))
            raise StaleVirtualOption(f"page revision changed: {page_id}")
        try:
            selected = manager.page_in(page_id, limit=limit)
        except Exception:
            self._pages.pop(page_id, None)
            raise
        self._pages.pop(page_id, None)
        self.events.append(SpeculationEvent("promote", page_id, shadow.base_revision,
                                            shadow.prepare_cost_ms))
        return selected


def rank_pages(scores: Iterable[tuple[str, float]], *, top_b: int) -> tuple[str, ...]:
    """Stable score ordering; scores are ranking signals, not calibrated probabilities."""
    if isinstance(top_b, bool) or top_b < 1:
        raise ValueError("top_b must be positive")
    return tuple(page_id for page_id, _score in sorted(scores, key=lambda item: (-item[1], item[0]))[:top_b])
