"""Revision-guarded shadow preparation for virtual option-space transitions.

The first version is intentionally synchronous and read-only.  It models the
correct ownership boundary needed by an asynchronous implementation: prepared
pages live outside ``VirtualOptionManager`` until the caller commits the parent
transition.  It does not execute tools and does not treat Jev's distribution as
a page probability without an explicit predictor.
"""
from __future__ import annotations

from copy import deepcopy
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from threading import Lock
from time import monotonic
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
        self._pending: list[Future[ShadowPage]] = []
        self._executor: ThreadPoolExecutor | None = None
        self._lock = Lock()

    def prepared(self) -> tuple[ShadowPage, ...]:
        return tuple(deepcopy(tuple(self._pages.values())))

    def clear(self, *, reason: str = "cancelled") -> None:
        for future in self._pending:
            future.cancel()
        self._pending.clear()
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None
        for page in tuple(self._pages.values()):
            self.events.append(SpeculationEvent("discard", page.page_id, page.base_revision,
                                                page.prepare_cost_ms, reason))
        self._pages.clear()

    @staticmethod
    def _prepare_page(page: OptionPage, *, base_revision: int, limit: int | None,
                      max_options: int, prepare_cost_ms: Callable[[OptionPage], float] | None) -> ShadowPage:
        selected = page.options if limit is None else page.options[:limit]
        if len(selected) > max_options:
            raise ValueError("option_budget")
        cost = float(prepare_cost_ms(page)) if prepare_cost_ms else 0.0
        if cost < 0:
            raise ValueError("prepare cost must be non-negative")
        return ShadowPage(page.page_id, base_revision, page.revision,
                          tuple(deepcopy(selected)), cost)

    def prefetch_async(
        self,
        manager: VirtualOptionManager,
        ranked_page_ids: Sequence[str],
        *,
        base_revision: int,
        limit: int | None = None,
        prepare_cost_ms: Callable[[OptionPage], float] | None = None,
    ) -> tuple[Future[ShadowPage], ...]:
        """Schedule bounded shadow-page materialization without changing residency."""
        if isinstance(base_revision, bool) or base_revision < 1:
            raise ValueError("base_revision must be positive")
        self.clear(reason="replaced")
        selected: list[OptionPage] = []
        seen: set[str] = set()
        for page_id in ranked_page_ids:
            if page_id in seen or len(selected) >= self.max_pages:
                continue
            seen.add(page_id)
            page = manager.page(page_id)
            if page is None:
                self.events.append(SpeculationEvent("skip", page_id, base_revision, reason="unknown_page"))
                continue
            selected.append(page)
        self._executor = ThreadPoolExecutor(max_workers=max(1, len(selected)),
                                             thread_name_prefix="jev-speculation")
        self._pending = [self._executor.submit(
            self._prepare_page, page, base_revision=base_revision, limit=limit,
            max_options=self.max_options, prepare_cost_ms=prepare_cost_ms)
            for page in selected]
        for page in selected:
            self.events.append(SpeculationEvent("scheduled", page.page_id, base_revision))
        return tuple(self._pending)

    def await_materialization(self, *, timeout_seconds: float | None = None) -> tuple[ShadowPage, ...]:
        """Collect futures; failed pages are audited and never promoted."""
        if timeout_seconds is not None and timeout_seconds < 0:
            raise ValueError("timeout_seconds must be non-negative")
        deadline = None if timeout_seconds is None else monotonic() + timeout_seconds
        pending = list(self._pending)
        self._pending.clear()
        try:
            for future in pending:
                remaining = None if deadline is None else max(0.0, deadline - monotonic())
                try:
                    shadow = future.result(timeout=remaining)
                except Exception as error:
                    self.events.append(SpeculationEvent("failed", "unknown", 0,
                                                        reason=type(error).__name__))
                    continue
                with self._lock:
                    self._pages[shadow.page_id] = shadow
                self.events.append(SpeculationEvent("prepared", shadow.page_id,
                                                    shadow.base_revision, shadow.prepare_cost_ms))
        finally:
            if self._executor is not None:
                self._executor.shutdown(wait=False, cancel_futures=True)
                self._executor = None
        return self.prepared()

    @property
    def pending_count(self) -> int:
        return len(self._pending)

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
            page = manager.page(page_id)
            if page is None:
                self.events.append(SpeculationEvent("skip", page_id, base_revision,
                                                    reason="unknown_page"))
                continue
            selected = page.options if limit is None else page.options[:limit]
            if len(selected) > self.max_options:
                self.events.append(SpeculationEvent("skip", page_id, base_revision,
                                                    reason="option_budget"))
                continue
            shadow = self._prepare_page(page, base_revision=base_revision, limit=limit,
                                        max_options=self.max_options, prepare_cost_ms=prepare_cost_ms)
            self._pages[page_id] = shadow
            self.events.append(SpeculationEvent("prepared", page_id, base_revision,
                                                shadow.prepare_cost_ms))
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
        page = manager.page(page_id)
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
