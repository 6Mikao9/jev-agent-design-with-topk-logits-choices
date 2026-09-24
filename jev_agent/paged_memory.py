from __future__ import annotations

"""Deterministic first slice of the Jev hierarchical paged-memory design.

The index owns page metadata and bounded reads.  It deliberately leaves the
Jev coarse/fine choice outside this module: callers pass the selected stable
page IDs to ``read_selected`` after the two candidate rounds.
"""

import re
from copy import deepcopy
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


class MemoryReadBudgetExceeded(ValueError):
    """Raised when a selected read exceeds any of its hard size limits."""


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
        existing = self._pages.get(page.page_id)
        if existing is None and len(self._pages) >= self.max_pages:
            raise ValueError("page table capacity exhausted")
        if existing is not None:
            # A retry of the exact same record is idempotent.  Any content,
            # summary, or dependency change must carry a newer revision so a
            # page selected by Jev cannot be silently replaced underneath it.
            same_payload = (
                existing.summary == page.summary
                and existing.content == page.content
                and existing.parent_id == page.parent_id
                and existing.tags == page.tags
                and existing.dependency_versions == page.dependency_versions
                and existing.sensitive == page.sensitive
            )
            if page.revision < existing.revision:
                raise ValueError("page revision must not decrease")
            if page.revision == existing.revision and not same_payload:
                raise ValueError("content, summary, or dependencies changed without revision increment")
            if page.revision == existing.revision:
                # Preserve the index-owned access timestamp and stale marker on
                # an idempotent retry; callers cannot mutate either by alias.
                return
        self._pages[page.page_id] = deepcopy(page)

    def mark_stale(self, page_id: str) -> None:
        self._pages[page_id].stale = True

    def select_pages(
        self, context: str, *, limit: int = 16, allow_sensitive: bool = False
    ) -> list[PageCandidate]:
        """Return page-table summaries for the first Jev selection round.

        This prefilter never returns page content.  Ties are stable by page ID,
        which makes replay and benchmark comparisons deterministic.
        """
        if limit < 1:
            raise ValueError("limit must be positive")
        query = _terms(context)
        scored: list[tuple[float, MemoryPage]] = []
        for page in self._pages.values():
            if page.stale or (page.sensitive and not allow_sensitive):
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
            PageCandidate(page.page_id, page.summary, score, page.revision, page.parent_id, tuple(page.tags))
            for score, page in scored[:limit]
        ]

    def search_content(
        self,
        context: str,
        *,
        required_markers: Iterable[str] = (),
        limit: int = 16,
        max_scan_bytes: int = 65_536,
        allow_sensitive: bool = False,
    ) -> list[PageCandidate]:
        """Bounded raw-evidence fallback used after a summary gap is detected.

        This deliberately runs outside Jev's page-table choice.  It is a
        retrieval/index operation: content is scanned under a byte budget and
        only stable page metadata is returned for a subsequent guarded read.
        ``required_markers`` is an evidence contract supplied by the caller
        (for example a source or schema marker), never a hidden target label.
        Stale and sensitive pages remain excluded.
        """
        if limit < 1 or max_scan_bytes < 1:
            raise ValueError("limit and max_scan_bytes must be positive")
        query = _terms(context)
        markers = tuple(marker.casefold() for marker in required_markers if marker)
        scanned = 0
        scored: list[tuple[float, MemoryPage]] = []
        for page in self._pages.values():
            if page.stale or (page.sensitive and not allow_sensitive):
                continue
            size = len(page.content.encode("utf-8"))
            if scanned + size > max_scan_bytes:
                break
            scanned += size
            content_folded = page.content.casefold()
            marker_hits = sum(1 for marker in markers if marker in content_folded)
            overlap = len(query & _terms(page.content))
            if marker_hits or overlap:
                # Marker hits express the caller's evidence contract and are
                # intentionally dominant; lexical overlap breaks ties.
                scored.append((marker_hits * 100.0 + float(overlap), page))
        scored.sort(key=lambda item: (-item[0], item[1].page_id))
        return [
            PageCandidate(page.page_id, page.summary, score, page.revision, page.parent_id, tuple(page.tags))
            for score, page in scored[:limit]
        ]

    def search_hybrid(
        self,
        context: str,
        *,
        required_markers: Iterable[str] = (),
        limit: int = 16,
        max_scan_bytes: int = 65_536,
        allow_sensitive: bool = False,
    ) -> list[PageCandidate]:
        """Fuse summary and bounded raw-content ranks for recovery.

        Raw evidence is weighted four times the summary rank so an explicit
        evidence contract can recover a page whose summary is incomplete;
        summary rank still breaks ties and helps when raw lexical evidence is
        weak.  This is a deterministic weighted-RRF index operation, not a
        Jev probability or a semantic-quality claim.
        """
        if limit < 1:
            raise ValueError("limit must be positive")
        summary = self.select_pages(context, limit=max(limit * 2, limit), allow_sensitive=allow_sensitive)
        content = self.search_content(
            context, required_markers=required_markers, limit=max(limit * 2, limit),
            max_scan_bytes=max_scan_bytes, allow_sensitive=allow_sensitive,
        )
        by_id = {candidate.page_id: candidate for candidate in summary}
        by_id.update({candidate.page_id: candidate for candidate in content})
        summary_rank = {candidate.page_id: rank for rank, candidate in enumerate(summary, 1)}
        content_rank = {candidate.page_id: rank for rank, candidate in enumerate(content, 1)}
        fused: list[tuple[float, str, PageCandidate]] = []
        for page_id, candidate in by_id.items():
            score = 0.0
            if page_id in content_rank:
                score += 4.0 / (60.0 + content_rank[page_id])
            if page_id in summary_rank:
                score += 1.0 / (60.0 + summary_rank[page_id])
            fused.append((score, page_id, candidate))
        fused.sort(key=lambda item: (-item[0], item[1]))
        return [
            PageCandidate(candidate.page_id, candidate.summary, score, candidate.revision,
                          candidate.parent_id, candidate.tags)
            for score, _, candidate in fused[:limit]
        ]

    def read_selected(
        self,
        page_ids: Iterable[str],
        *,
        max_bytes: int = 32_000,
        max_pages: int = 8,
        max_page_bytes: int = 8_192,
        allow_sensitive: bool = False,
        expected_revisions: dict[str, int] | None = None,
        expected_dependency_versions: dict[str, int] | None = None,
    ) -> list[MemoryPage]:
        """Read explicitly selected pages under hard, all-or-nothing budgets.

        Every selected page is validated before any access timestamp is changed.
        This prevents a stale, unauthorized, or over-budget page later in a
        batch from causing an earlier page to look as though it was read.
        """
        for name, value in (
            ("max_bytes", max_bytes),
            ("max_pages", max_pages),
            ("max_page_bytes", max_page_bytes),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be positive")
        expected_revisions = expected_revisions or {}
        expected_dependency_versions = expected_dependency_versions or {}

        # Materialize once: generators must not be consumed while validating
        # and then mysteriously produce a different read set.
        requested = list(page_ids)
        if len(requested) > max_pages:
            raise MemoryReadBudgetExceeded(
                f"selected {len(requested)} pages, max_pages is {max_pages}"
            )
        if len(set(requested)) != len(requested):
            raise ValueError("page_ids must not contain duplicates")

        # Validation is deliberately separate from mutation.  A missing page
        # remains a normal KeyError for callers that need to distinguish it.
        pages: list[MemoryPage] = []
        used = 0
        for page_id in requested:
            page = self._pages[page_id]
            if page.stale or page.revision != expected_revisions.get(page_id, page.revision):
                raise StaleMemoryPage(page_id)
            if page.sensitive and not allow_sensitive:
                raise PermissionError(f"sensitive page requires allow_sensitive: {page_id}")
            for dependency, expected in expected_dependency_versions.items():
                if dependency in page.dependency_versions and page.dependency_versions[dependency] != expected:
                    raise StaleMemoryPage(page_id)
            size = len(page.content.encode("utf-8"))
            if size > max_page_bytes:
                raise MemoryReadBudgetExceeded(
                    f"page {page_id} is {size} bytes, max_page_bytes is {max_page_bytes}"
                )
            used += size
            if used > max_bytes:
                raise MemoryReadBudgetExceeded(
                    f"selected pages use {used} bytes, max_bytes is {max_bytes}"
                )
            pages.append(page)

        now = datetime.now(timezone.utc).timestamp()
        for page in pages:
            page.last_accessed = now
        return [deepcopy(page) for page in pages]

    def __len__(self) -> int:
        return len(self._pages)
