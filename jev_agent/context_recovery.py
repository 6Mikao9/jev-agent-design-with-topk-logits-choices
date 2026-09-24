"""Bounded raw-evidence recovery for context blocks.

This is the context-space analogue of ``RawEvidenceFallback`` for memory
pages.  It is intentionally deterministic: an evidence contract identifies
required markers, the materializer loads only a bounded candidate set, and a
caller may commit a unique recovered block after revision checks.  It does
not pretend that marker presence is semantic truth.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .context_materialization import (
    ContextMaterializationBudgetExceeded,
    ContextMaterializer,
    ContextSourceNotFound,
    StaleContextMaterialization,
)
from .context_residency import ContextResidencyManager


@dataclass(frozen=True)
class ContextEvidenceRecoveryResult:
    status: str
    candidate_ids: tuple[str, ...] = ()
    recovered_ids: tuple[str, ...] = ()
    marker_hits: dict[str, tuple[str, ...]] | None = None
    read_bytes: int = 0
    reason: str = ""


class ContextEvidenceFallback:
    """Search selected context candidates for a complete evidence contract."""

    def __init__(
        self,
        materializer: ContextMaterializer,
        *,
        required_markers: Iterable[str],
        max_candidates: int = 4,
        require_unique: bool = True,
    ) -> None:
        markers = tuple(marker.casefold() for marker in required_markers if marker)
        if not markers:
            raise ValueError("at least one evidence marker is required")
        if max_candidates < 1:
            raise ValueError("max_candidates must be positive")
        self.materializer = materializer
        self.required_markers = markers
        self.max_candidates = max_candidates
        self.require_unique = require_unique

    def recover(
        self,
        manager: ContextResidencyManager,
        candidate_ids: Iterable[str],
        *,
        expected_revisions: dict[str, int] | None = None,
    ) -> ContextEvidenceRecoveryResult:
        expected_revisions = expected_revisions or {}
        requested = tuple(dict.fromkeys(candidate_ids))[: self.max_candidates]
        blocks = {block.block_id: block for block in manager.blocks()}
        marker_hits: dict[str, tuple[str, ...]] = {}
        recovered: list[str] = []
        read_bytes = 0
        failure_types: set[str] = set()
        for block_id in requested:
            block = blocks.get(block_id)
            if block is None:
                failure_types.add("unknown_block")
                continue
            try:
                body = self.materializer.materialize(
                    block, expected_revision=expected_revisions.get(block_id, block.revision)
                )
            except (ContextMaterializationBudgetExceeded, ContextSourceNotFound,
                    StaleContextMaterialization) as error:
                failure_types.add(type(error).__name__)
                continue
            read_bytes += body.byte_count
            hits = tuple(marker for marker in self.required_markers if marker in body.content.casefold())
            marker_hits[block_id] = hits
            if len(hits) == len(self.required_markers):
                recovered.append(block_id)

        if len(recovered) > 1 and self.require_unique:
            return ContextEvidenceRecoveryResult(
                "ambiguous", requested, tuple(recovered), marker_hits, read_bytes,
                "multiple candidates satisfy evidence contract",
            )
        if recovered:
            return ContextEvidenceRecoveryResult(
                "recovered", requested, tuple(recovered), marker_hits, read_bytes,
            )
        reason = ",".join(sorted(failure_types)) if failure_types else "no candidate matched all markers"
        return ContextEvidenceRecoveryResult(
            "no_match", requested, (), marker_hits, read_bytes, reason,
        )
