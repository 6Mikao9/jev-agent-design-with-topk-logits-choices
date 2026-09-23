"""Safe parameter priors for ArgumentOptionSpace candidate generation.

The prior is advisory: returned values must still be materialized as options and
selected by the configured decision model.  It stores aggregate history rather
than traces, with a small freshness check to avoid stale defaults.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any

from .option_space import SpaceOption


@dataclass
class ParameterRecord:
    tool: str
    field: str
    value: Any
    phase: str = ""
    semantic_text: str = ""
    revision: int = 0
    uses: int = 0
    successes: int = 0
    updated_at: float = 0.0

    @property
    def success_rate(self) -> float:
        return self.successes / self.uses if self.uses else 0.0


@dataclass(frozen=True)
class ParameterCandidate:
    value: Any
    confidence: float
    source: str
    revision: int
    uses: int
    successes: int

    def to_option(self, option_id: str, description: str | None = None) -> SpaceOption:
        return SpaceOption(option_id, description or str(self.value), self.value, self.source)


class ParameterPrior:
    """Retrieve field values by exact state, state-machine, then lexical match."""

    def __init__(self, *, max_age_seconds: float = 7 * 24 * 3600) -> None:
        self.max_age_seconds = max_age_seconds
        self._records: list[ParameterRecord] = []

    def record(self, *, tool: str, field: str, value: Any, phase: str = "",
               semantic_text: str = "", revision: int = 0, success: bool = True,
               now: float | None = None) -> ParameterRecord:
        now = datetime.now(timezone.utc).timestamp() if now is None else now
        for item in self._records:
            if (item.tool, item.field, item.value, item.phase, item.semantic_text) == (tool, field, value, phase, semantic_text):
                item.uses += 1; item.successes += int(success); item.revision = revision; item.updated_at = now
                return item
        item = ParameterRecord(tool, field, value, phase, semantic_text, revision, 1, int(success), now)
        self._records.append(item)
        return item

    def candidates(self, *, tool: str, field: str, phase: str = "", semantic_text: str = "",
                   revision: int | None = None, limit: int = 8, now: float | None = None) -> tuple[ParameterCandidate, ...]:
        if limit < 1: raise ValueError("limit must be positive")
        now = datetime.now(timezone.utc).timestamp() if now is None else now
        rows = [r for r in self._records if r.tool == tool and r.field == field and now - r.updated_at <= self.max_age_seconds and (revision is None or r.revision <= revision)]
        query = set(_tokens(semantic_text))
        def rank(r: ParameterRecord) -> tuple[int, float, float]:
            exact = int(r.phase == phase and bool(phase))
            overlap = len(query & set(_tokens(r.semantic_text))) / max(1, len(query)) if query else 0.0
            state_match = int(r.phase == phase)
            source = exact * 3 + state_match * 2 + (1 if overlap else 0)
            return source, overlap, r.success_rate
        rows.sort(key=rank, reverse=True)
        result = []
        for r in rows[:limit]:
            exact = r.phase == phase and bool(phase)
            overlap = len(query & set(_tokens(r.semantic_text))) / max(1, len(query)) if query else 0.0
            source = "exact-state" if exact else ("state-machine" if r.phase == phase else "semantic/lexical")
            confidence = min(1.0, 0.45 + 0.25 * int(exact) + 0.15 * int(r.phase == phase) + 0.15 * overlap) * (0.5 + 0.5 * r.success_rate)
            result.append(ParameterCandidate(r.value, confidence, source, r.revision, r.uses, r.successes))
        return tuple(result)


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(re.findall(r"[\w]+", text.lower()))
