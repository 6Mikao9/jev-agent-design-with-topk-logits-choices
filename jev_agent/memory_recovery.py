"""Guarded recovery from a page-table summary gap.

The normal two-stage selector only reads pages chosen from summaries.  This
module adds an explicit, bounded fallback: a verifier reports that the read
set lacks a required evidence marker, the index performs a raw-content
retrieval pass, and selected extra pages are read with the same revision and
budget checks.  The fallback does not expose raw content to Jev during the
choice round and does not use an oracle page id.
"""
from __future__ import annotations

from dataclasses import dataclass

from .memory_selection import MemorySelectionResult
from .paged_memory import MemoryPage, MemoryReadBudgetExceeded, PagedMemoryIndex, StaleMemoryPage


@dataclass(frozen=True)
class EvidenceRecoveryResult:
    status: str
    pages: tuple[MemoryPage, ...] = ()
    candidate_ids: tuple[str, ...] = ()
    recovered_ids: tuple[str, ...] = ()
    read_bytes: int = 0
    reason: str = ""


class RawEvidenceFallback:
    """Recover missing evidence under bounded scan/read budgets."""

    def __init__(
        self,
        *,
        required_markers: tuple[str, ...],
        max_candidates: int = 8,
        max_pages: int = 2,
        max_read_bytes: int = 16_384,
        max_page_bytes: int = 8_192,
        max_scan_bytes: int = 65_536,
        retrieval: str = "hybrid",
    ) -> None:
        if not required_markers:
            raise ValueError("at least one evidence marker is required")
        if min(max_candidates, max_pages, max_read_bytes, max_page_bytes, max_scan_bytes) < 1:
            raise ValueError("fallback limits must be positive")
        if retrieval not in {"content", "hybrid"}:
            raise ValueError("retrieval must be content or hybrid")
        self.required_markers = tuple(required_markers)
        self.max_candidates = max_candidates
        self.max_pages = max_pages
        self.max_read_bytes = max_read_bytes
        self.max_page_bytes = max_page_bytes
        self.max_scan_bytes = max_scan_bytes
        self.retrieval = retrieval

    def recover(
        self,
        index: PagedMemoryIndex,
        *,
        context: str,
        initial: MemorySelectionResult,
    ) -> EvidenceRecoveryResult:
        if initial.status != "read_complete":
            return EvidenceRecoveryResult(
                "not_attempted", initial.pages, reason=f"initial status: {initial.status}"
            )
        present = {marker.casefold() for page in initial.pages for marker in self.required_markers
                   if marker.casefold() in page.content.casefold()}
        missing = tuple(marker for marker in self.required_markers if marker.casefold() not in present)
        if not missing:
            return EvidenceRecoveryResult("not_needed", initial.pages,
                                          read_bytes=initial.read_bytes)

        search = index.search_hybrid if self.retrieval == "hybrid" else index.search_content
        candidates = search(context, required_markers=missing, limit=self.max_candidates,
                            max_scan_bytes=self.max_scan_bytes)
        selected = set(initial.selected_ids)
        extra = [candidate for candidate in candidates if candidate.page_id not in selected]
        if not extra:
            return EvidenceRecoveryResult("no_match", initial.pages,
                                          tuple(candidate.page_id for candidate in candidates),
                                          reason="no unselected page matched evidence contract")
        extra = extra[: self.max_pages]
        try:
            pages = index.read_selected(
                [candidate.page_id for candidate in extra],
                max_bytes=self.max_read_bytes,
                max_pages=self.max_pages,
                max_page_bytes=self.max_page_bytes,
                expected_revisions={candidate.page_id: candidate.revision for candidate in extra},
            )
        except MemoryReadBudgetExceeded as error:
            return EvidenceRecoveryResult("read_budget_exceeded", initial.pages,
                                          tuple(candidate.page_id for candidate in candidates),
                                          reason=str(error))
        except (StaleMemoryPage, KeyError) as error:
            return EvidenceRecoveryResult("stale_selection", initial.pages,
                                          tuple(candidate.page_id for candidate in candidates),
                                          reason=str(error))
        merged = tuple(initial.pages) + tuple(pages)
        return EvidenceRecoveryResult(
            "recovered",
            merged,
            tuple(candidate.page_id for candidate in candidates),
            tuple(page.page_id for page in pages),
            initial.read_bytes + sum(len(page.content.encode("utf-8")) for page in pages),
        )
