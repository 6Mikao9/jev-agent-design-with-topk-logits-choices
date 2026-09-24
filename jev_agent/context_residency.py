"""Bounded logical-context residency for decision-native agents.

This module is a deterministic lexical baseline for the context-space half of
the runtime.  It keeps a small pinned set, rebuilds a replaceable working set,
and leaves cold blocks addressable by stable IDs.  Embeddings, external RAG
stores and learned utility predictors can implement the same scoring boundary
later.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Iterable


_WORD = re.compile(r"[\w一-龥]+", re.UNICODE)


def _terms(text: str) -> set[str]:
    return {item.casefold() for item in _WORD.findall(text) if item}


class ContextFault(RuntimeError):
    """A requested logical context block is cold, stale or unavailable."""


@dataclass
class ContextBlock:
    block_id: str
    summary: str
    raw_content_ref: str
    revision: int = 1
    dependencies: tuple[str, ...] = ()
    last_access: int = 0
    access_count: int = 0
    utility_score: float = 0.0
    last_useful: int = 0
    created_at: int = 0
    kind: str = "observation"
    size: int = 0
    pinned: bool = False
    phase: str | None = None
    stale: bool = False
    last_loaded_step: int = -1


@dataclass(frozen=True)
class ContextCandidate:
    block_id: str
    score: float
    phase: str | None


class ContextResidencyManager:
    """Keep logical context larger than the decision model's working set."""

    DEFAULT_AGING = {
        "constraint": 0.0,
        "task_state": 0.01,
        "observation": 0.05,
        "tool_output": 0.08,
        "retrieval": 0.15,
    }

    def __init__(
        self,
        *,
        max_working: int = 8,
        hysteresis: float = 0.05,
        minimum_residency_steps: int = 1,
        aging_rates: dict[str, float] | None = None,
    ) -> None:
        if isinstance(max_working, bool) or max_working < 1:
            raise ValueError("max_working must be positive")
        if hysteresis < 0 or minimum_residency_steps < 0:
            raise ValueError("hysteresis and minimum_residency_steps must be non-negative")
        self.max_working = max_working
        self.hysteresis = float(hysteresis)
        self.minimum_residency_steps = minimum_residency_steps
        self.aging_rates = dict(self.DEFAULT_AGING)
        if aging_rates:
            if any(value < 0 for value in aging_rates.values()):
                raise ValueError("aging rates must be non-negative")
            self.aging_rates.update(aging_rates)
        self._blocks: dict[str, ContextBlock] = {}
        self._working: list[str] = []
        self._step = 0

    @property
    def step(self) -> int:
        return self._step

    def register(self, block: ContextBlock) -> None:
        if not block.block_id or not block.summary or block.revision < 1:
            raise ValueError("block_id, summary and positive revision are required")
        existing = self._blocks.get(block.block_id)
        if existing is not None:
            if block.revision < existing.revision:
                raise ValueError("context revision must not decrease")
            if block.revision == existing.revision:
                comparable = (existing.summary, existing.raw_content_ref, existing.dependencies, existing.kind, existing.pinned, existing.phase)
                incoming = (block.summary, block.raw_content_ref, block.dependencies, block.kind, block.pinned, block.phase)
                if comparable != incoming:
                    raise ValueError("context changed without a revision increment")
                return
            self._working = [item for item in self._working if item != block.block_id]
        self._blocks[block.block_id] = ContextBlock(**vars(block))

    def refresh(
        self,
        query: str,
        *,
        updates: Iterable[ContextBlock] = (),
        phase: str | None = None,
    ) -> tuple[ContextBlock, ...]:
        """Apply event updates and rebuild the working context in one step.

        A refresh is intentionally explicit: callers may replace a block with
        a newer revision and immediately derive a new resident set.  It does
        not assume any cross-request prefix/KV reuse; each decision observes
        the current resident set and stable block IDs.
        """
        for block in updates:
            self.register(block)
        return self.rebuild(query, phase=phase, advance_step=True)

    def blocks(self) -> tuple[ContextBlock, ...]:
        return tuple(ContextBlock(**vars(block)) for block in self._blocks.values())

    def resident(self) -> tuple[ContextBlock, ...]:
        ids = [block_id for block_id, block in self._blocks.items() if block.pinned]
        ids.extend(self._working)
        return tuple(ContextBlock(**vars(self._blocks[block_id])) for block_id in ids if not self._blocks[block_id].stale)

    def cold(self) -> tuple[ContextBlock, ...]:
        resident_ids = {block.block_id for block in self.resident()}
        return tuple(ContextBlock(**vars(block)) for block in self._blocks.values() if block.block_id not in resident_ids and not block.stale)

    def _score(self, block: ContextBlock, query_terms: set[str], phase: str | None) -> float:
        overlap = len(query_terms & _terms(block.summary))
        age = max(0, self._step - block.last_useful)
        decay = math.exp(-self.aging_rates.get(block.kind, 0.05) * age)
        phase_bonus = 0.25 if phase and block.phase == phase else 0.0
        return float(overlap) + block.utility_score * decay + phase_bonus

    def candidates(self, query: str, *, phase: str | None = None) -> tuple[ContextCandidate, ...]:
        query_terms = _terms(query)
        scored = [
            ContextCandidate(block.block_id, self._score(block, query_terms, phase), block.phase)
            for block in self._blocks.values()
            if not block.stale and not block.pinned and (query_terms & _terms(block.summary) or not query_terms)
        ]
        return tuple(sorted(scored, key=lambda item: (-item.score, item.block_id)))

    def rebuild(self, query: str, *, phase: str | None = None, advance_step: bool = True) -> tuple[ContextBlock, ...]:
        if advance_step:
            self._step += 1
        candidates = self.candidates(query, phase=phase)
        by_id = {candidate.block_id: candidate for candidate in candidates}
        query_terms = _terms(query)
        # Current working blocks remain eligible for the residency minimum
        # even when the new query no longer contains their lexical terms.
        for block_id in self._working:
            block = self._blocks[block_id]
            if not block.stale:
                by_id.setdefault(
                    block_id,
                    ContextCandidate(block_id, self._score(block, query_terms, phase), block.phase),
                )
        protected = [
            block_id for block_id in self._working
            if block_id in by_id
            and self._step - self._blocks[block_id].last_loaded_step < self.minimum_residency_steps
        ]
        selected = protected[: self.max_working]
        for candidate in candidates:
            if candidate.block_id in selected:
                continue
            if len(selected) < self.max_working:
                selected.append(candidate.block_id)
                continue
            replaceable = [
                item for item in selected
                if item not in protected
            ]
            if not replaceable:
                break
            worst = min(replaceable, key=lambda item: (by_id[item].score, item))
            if candidate.score <= by_id[worst].score + self.hysteresis:
                continue
            selected[selected.index(worst)] = candidate.block_id
        previous_working = set(self._working)
        self._working = selected
        for block_id in selected:
            block = self._blocks[block_id]
            if block_id not in previous_working:
                block.last_loaded_step = self._step
                block.last_access = self._step
                block.access_count += 1
        return self.resident()

    def commit_selected(
        self,
        block_ids: Iterable[str],
        *,
        expected_revisions: dict[str, int] | None = None,
    ) -> tuple[ContextBlock, ...]:
        """Atomically install an explicitly verified working set.

        The normal :meth:`rebuild` path computes a lexical/utility ranking.
        A refresh coordinator may instead ask a decision model to verify a
        bounded set of blocks.  This method is the commit boundary for that
        path: every ID and revision is validated before the working set is
        changed, and pinned blocks remain outside the working-set budget.
        """
        requested = list(block_ids)
        if len(requested) > self.max_working:
            raise ValueError("selected context blocks exceed max_working")
        if len(set(requested)) != len(requested):
            raise ValueError("block_ids must not contain duplicates")
        expected_revisions = expected_revisions or {}
        validated: list[ContextBlock] = []
        for block_id in requested:
            block = self._blocks.get(block_id)
            if block is None or block.stale:
                raise ContextFault(f"context block is unavailable or stale: {block_id}")
            expected = expected_revisions.get(block_id)
            if expected is not None and block.revision != expected:
                raise ContextFault(f"context revision changed: {block_id}")
            if block.pinned:
                raise ValueError("pinned blocks are not part of the working-set selection")
            validated.append(block)

        previous = set(self._working)
        self._step += 1
        self._working = requested
        for block in validated:
            if block.block_id not in previous:
                block.last_loaded_step = self._step
                block.last_access = self._step
                block.access_count += 1
        return self.resident()

    def require(self, block_id: str, *, expected_revision: int | None = None) -> ContextBlock:
        block = self._blocks.get(block_id)
        if block is None or block.stale:
            raise ContextFault(f"context block is unavailable or stale: {block_id}")
        if not block.pinned and block_id not in self._working:
            raise ContextFault(f"context block is cold: {block_id}")
        if expected_revision is not None and block.revision != expected_revision:
            raise ContextFault(f"context revision changed: {block_id}")
        block.last_access = self._step
        block.access_count += 1
        return ContextBlock(**vars(block))

    def mark_useful(self, block_id: str, reward: float) -> None:
        block = self._blocks[block_id]
        if not math.isfinite(reward):
            raise ValueError("reward must be finite")
        block.utility_score = 0.9 * block.utility_score + 0.1 * reward
        block.last_useful = self._step

    def invalidate(self, block_id: str) -> None:
        block = self._blocks[block_id]
        block.stale = True
        self._working = [item for item in self._working if item != block_id]
