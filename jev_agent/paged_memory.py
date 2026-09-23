from __future__ import annotations

"""Deterministic first slice of the Jev hierarchical paged-memory design.

The index owns page metadata and bounded reads.  It deliberately leaves the
Jev coarse/fine choice outside this module: callers pass the selected stable
page IDs to ``read_selected`` after the two candidate rounds.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable


_WORD = re.compile(r"[\w一-龥]+", re.UNICODE)


def _terms(text: str) -> set[str]:
    return {item.casefold() for item in _WORD.findall(text) if item}


@dataclass
class MemoryPage:
    page_id: str
    summary: str
    content: str
    revision: int = 1
    parent_id: str | None = None
    tags: tuple[str, ...] = ()
    dependency_versions: dict[str, int] = field(default_factory=dict)
    sensitive: bool = False
    last_accessed: float = field(default_factory=lambda: datetime.now(timezone.utc).timestamp())
    stale: bool = False


@dataclass(frozen=True)
class PageCandidate:
    page_id: str
    summary: str
    score: float
    revision: int
    parent_id: str | None
    tags: tuple[str, ...]


class StaleMemoryPage(RuntimeError):
    """Raised when a selected page changed after Jev saw its page-table entry."""


class PagedMemoryIndex:
    """A bounded, deterministic page table with lexical prefiltering and LRU metadata."""

    def __init__(self, *, max_pages: int = 10_000) -> None:
        if max_pages < 1:
            raise ValueError("max_pages must be positive")
        self.max_pages = max_pages
        self._pages: dict[str, MemoryPage] = {}

    def upsert(self, page: MemoryPage) -> None:
        if not page.page_id or not page.summary:
            raise ValueError("page_id and summary are required")
        if page.page_id not in self._pages and len(self._pages) >= self.max_pages:
            raise ValueError("page table capacity exhausted")
        self._pages[page.page_id] = page

    def mark_stale(self, page_id: str) -> None:
        self._pages[page_id].stale = True

    def select_pages(self, context: str, *, limit: int = 16) -> list[PageCandidate]:
        """Return page-table summaries for the first Jev selection round.

        This prefilter never returns page content.  Ties are stable by page ID,
        which makes replay and benchmark comparisons deterministic.
        """
        if limit < 1:
            raise ValueError("limit must be positive")
        query = _terms(context)
        scored: list[tuple[float, MemoryPage]] = []
        for page in self._pages.values():
            if page.stale:
                continue
            terms = _terms(" ".join((page.summary, *page.tags)))
            overlap = len(query & terms)
            score = float(overlap)
            # A tiny recency tie-breaker keeps hot pages ahead without allowing
            # LRU to hide a relevant old page with a positive lexical score.
            score += min(page.last_accessed / 1e12, 1e-6)
            if overlap or not query:
                scored.append((score, page))
        scored.sort(key=lambda item: (-item[0], item[1].page_id))
        return [
            PageCandidate(page.page_id, page.summary, score, page.revision, page.parent_id, page.tags)
            for score, page in scored[:limit]
        ]

    def read_selected(
        self,
        page_ids: Iterable[str],
        *,
        max_bytes: int = 32_000,
        expected_revisions: dict[str, int] | None = None,
    ) -> list[MemoryPage]:
        """Read explicitly selected pages under a total UTF-8 byte budget."""
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        expected_revisions = expected_revisions or {}
        result: list[MemoryPage] = []
        used = 0
        seen: set[str] = set()
        for page_id in page_ids:
            if page_id in seen:
                continue
            seen.add(page_id)
            page = self._pages[page_id]
            if page.stale or page.revision != expected_revisions.get(page_id, page.revision):
                raise StaleMemoryPage(page_id)
            size = len(page.content.encode("utf-8"))
            if used + size > max_bytes:
                break
            used += size
            page.last_accessed = datetime.now(timezone.utc).timestamp()
            result.append(page)
        return result

    def __len__(self) -> int:
        return len(self._pages)
