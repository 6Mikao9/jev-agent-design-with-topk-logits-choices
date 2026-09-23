"""Bounded Virtual Option Space runtime primitives.

The manager separates a logical option directory from the finite set currently
visible to Jev.  It is intentionally synchronous and deterministic: async
prefetch, learned replacement and a production page store remain follow-up
work, while page-in/page-out, stable IDs, revision checks and refinement are
fully replayable here.
"""
from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Any, Iterable


class OptionFault(RuntimeError):
    """The requested virtual option or page is not resident or available."""


class RefineFault(RuntimeError):
    """A requested refinement cannot produce a valid child option page."""


class StaleVirtualOption(OptionFault):
    """A page or option revision no longer matches the caller's snapshot."""


@dataclass(frozen=True)
class VirtualOption:
    option_id: str
    description: str
    payload: Any = None
    page_id: str = "root"
    revision: int = 1
    kind: str = "generic"
    materialization_cost: float = 0.0


@dataclass(frozen=True)
class OptionPage:
    page_id: str
    options: tuple[VirtualOption, ...]
    revision: int = 1
    parent_id: str | None = None


class VirtualOptionManager:
    """Maintain a bounded resident set over a larger virtual option directory."""

    def __init__(self, *, max_resident: int = 8, max_pages: int = 10_000) -> None:
        if isinstance(max_resident, bool) or max_resident < 1:
            raise ValueError("max_resident must be positive")
        if isinstance(max_pages, bool) or max_pages < 1:
            raise ValueError("max_pages must be positive")
        self.max_resident = max_resident
        self.max_pages = max_pages
        self._pages: dict[str, OptionPage] = {}
        self._option_pages: dict[str, str] = {}
        self._stale_pages: set[str] = set()
        self._resident: OrderedDict[str, VirtualOption] = OrderedDict()

    def register_page(
        self,
        page_id: str,
        options: Iterable[VirtualOption],
        *,
        revision: int = 1,
        parent_id: str | None = None,
    ) -> OptionPage:
        if not page_id or isinstance(revision, bool) or revision < 1:
            raise ValueError("page_id and a positive revision are required")
        normalized = tuple(options)
        if not normalized:
            raise ValueError("an option page must contain at least one option")
        ids = [option.option_id for option in normalized]
        if any(not option_id for option_id in ids) or len(set(ids)) != len(ids):
            raise ValueError("option IDs must be non-empty and unique within a page")
        if any(option.page_id != page_id for option in normalized):
            raise ValueError("option.page_id must match its registered page")
        for option_id in ids:
            owner = self._option_pages.get(option_id)
            if owner is not None and owner != page_id:
                raise ValueError(f"option ID is already owned by page {owner}: {option_id}")
        page = OptionPage(page_id, deepcopy(normalized), revision, parent_id)
        previous = self._pages.get(page_id)
        if previous is None and len(self._pages) >= self.max_pages:
            raise ValueError("virtual option page capacity exhausted")
        if previous is not None:
            if revision < previous.revision:
                raise ValueError("page revision must not decrease")
            if revision == previous.revision:
                if previous != page:
                    raise ValueError("page changed without a revision increment")
                return deepcopy(previous)
            for option in previous.options:
                self._resident.pop(option.option_id, None)
                self._option_pages.pop(option.option_id, None)
        self._pages[page_id] = page
        for option in page.options:
            self._option_pages[option.option_id] = page_id
        self._stale_pages.discard(page_id)
        return deepcopy(page)

    def pages(self) -> tuple[OptionPage, ...]:
        return tuple(deepcopy(page) for page in self._pages.values())

    def resident_options(self) -> tuple[VirtualOption, ...]:
        return tuple(deepcopy(option) for option in self._resident.values())

    def page_in(
        self,
        page_id: str,
        *,
        limit: int | None = None,
        protected_ids: Iterable[str] = (),
    ) -> tuple[VirtualOption, ...]:
        page = self._pages.get(page_id)
        if page is None:
            raise OptionFault(f"virtual page is not registered: {page_id}")
        if page_id in self._stale_pages:
            raise StaleVirtualOption(f"virtual page is stale: {page_id}")
        if limit is not None and (isinstance(limit, bool) or limit < 1):
            raise ValueError("limit must be positive")
        selected = page.options if limit is None else page.options[:limit]
        if len(selected) > self.max_resident:
            raise OptionFault(
                f"page {page_id} has {len(selected)} options; use limit <= {self.max_resident}"
            )
        protected = set(protected_ids)
        missing = [option for option in selected if option.option_id not in self._resident]
        if len(self._resident) + len(missing) > self.max_resident:
            self._evict_lru(len(self._resident) + len(missing) - self.max_resident, protected)
        for option in selected:
            self._resident[option.option_id] = deepcopy(option)
            self._resident.move_to_end(option.option_id)
        return tuple(deepcopy(option) for option in selected)

    def prefetch(self, page_id: str, *, limit: int | None = None) -> tuple[VirtualOption, ...]:
        """Synchronously warm a page; an async scheduler can wrap this later."""
        return self.page_in(page_id, limit=limit)

    def evict_lru(self, count: int = 1, *, protected_ids: Iterable[str] = ()) -> tuple[str, ...]:
        if isinstance(count, bool) or count < 1:
            raise ValueError("count must be positive")
        return self._evict_lru(count, set(protected_ids))

    def _evict_lru(self, count: int, protected: set[str]) -> tuple[str, ...]:
        candidates = [option_id for option_id in self._resident if option_id not in protected]
        if len(candidates) < count:
            raise OptionFault("resident working set cannot evict protected options")
        evicted = candidates[:count]
        for option_id in evicted:
            self._resident.pop(option_id, None)
        return tuple(evicted)

    def touch(self, option_id: str) -> VirtualOption:
        if option_id not in self._resident:
            raise OptionFault(f"option is not resident: {option_id}")
        option = self._resident.pop(option_id)
        self._resident[option_id] = option
        return deepcopy(option)

    def resolve(self, option_id: str, *, expected_revision: int | None = None) -> VirtualOption:
        option = self._resident.get(option_id)
        if option is None:
            page_id = self._option_pages.get(option_id)
            if page_id in self._stale_pages:
                raise StaleVirtualOption(f"option page is stale: {page_id}")
            raise OptionFault(f"option is not resident: {option_id}")
        if option.page_id in self._stale_pages:
            raise StaleVirtualOption(f"option page is stale: {option.page_id}")
        if expected_revision is not None and option.revision != expected_revision:
            raise StaleVirtualOption(
                f"option revision changed: {option_id} expected {expected_revision}, got {option.revision}"
            )
        self.touch(option_id)
        return deepcopy(option)

    def invalidate_page(self, page_id: str) -> None:
        if page_id not in self._pages:
            raise KeyError(page_id)
        self._stale_pages.add(page_id)
        for option in self._pages[page_id].options:
            self._resident.pop(option.option_id, None)

    def refine(
        self,
        parent_id: str,
        options: Iterable[VirtualOption],
        *,
        revision: int = 1,
        page_id: str | None = None,
    ) -> tuple[VirtualOption, ...]:
        """Register and page in a finer-grained child set for one option."""
        if not parent_id:
            raise RefineFault("parent_id is required")
        children = tuple(options)
        if not children:
            raise RefineFault("refinement produced no child options")
        child_page_id = page_id or f"refine:{parent_id}:r{revision}"
        children = tuple(replace(option, page_id=child_page_id) for option in children)
        page = self.register_page(
            child_page_id, children, revision=revision, parent_id=parent_id
        )
        refined = self.page_in(page.page_id)
        # Refinement replaces the coarse decision surface.  Keeping the parent
        # resident would let a chooser commit the stale/coarse option again on
        # the next decision round, defeating progressive refinement.
        self._resident.pop(parent_id, None)
        return refined
