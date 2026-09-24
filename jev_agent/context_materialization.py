"""Bounded loading of ContextBlock raw bodies.

``ContextResidencyManager`` decides which block IDs are working; this module
loads the corresponding body only after that decision.  Keeping the source
behind a callback/mapping avoids giving the runtime an implicit ability to
read arbitrary paths outside its configured workspace.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Callable, Mapping

from .context_residency import ContextBlock


class ContextMaterializationError(RuntimeError):
    """Base error for bounded raw-context loading."""


class ContextSourceNotFound(ContextMaterializationError):
    """The configured source has no body for a raw reference."""


class ContextMaterializationBudgetExceeded(ContextMaterializationError):
    """The raw body exceeds the materialization byte budget."""


class StaleContextMaterialization(ContextMaterializationError):
    """The caller's expected block revision is no longer current."""


@dataclass(frozen=True)
class MaterializedContext:
    block_id: str
    revision: int
    raw_content_ref: str
    content: str
    byte_count: int
    sha256: str


class ContextMaterializer:
    """Load raw context through a bounded, explicit source."""

    def __init__(
        self,
        source: Mapping[str, str | bytes] | Callable[[str], str | bytes],
        *,
        max_bytes: int = 16_384,
    ) -> None:
        if isinstance(max_bytes, bool) or max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        if not callable(source) and not isinstance(source, Mapping):
            raise TypeError("source must be a mapping or callable")
        self.source = source
        self.max_bytes = max_bytes

    def materialize(
        self,
        block: ContextBlock,
        *,
        expected_revision: int | None = None,
        max_bytes: int | None = None,
    ) -> MaterializedContext:
        if block.stale:
            raise StaleContextMaterialization(block.block_id)
        if expected_revision is not None and block.revision != expected_revision:
            raise StaleContextMaterialization(block.block_id)
        budget = self.max_bytes if max_bytes is None else max_bytes
        if isinstance(budget, bool) or budget < 1:
            raise ValueError("max_bytes must be positive")
        try:
            raw = self.source(block.raw_content_ref) if callable(self.source) else self.source[block.raw_content_ref]
        except (KeyError, FileNotFoundError):
            raise ContextSourceNotFound(block.raw_content_ref) from None
        if isinstance(raw, bytes):
            try:
                content = raw.decode("utf-8")
            except UnicodeDecodeError:
                raise ContextMaterializationError("raw context is not valid UTF-8") from None
        elif isinstance(raw, str):
            content = raw
        else:
            raise ContextMaterializationError("context source must return str or bytes")
        encoded = content.encode("utf-8")
        if len(encoded) > budget:
            raise ContextMaterializationBudgetExceeded(
                f"context {block.block_id} is {len(encoded)} bytes, max_bytes is {budget}"
            )
        return MaterializedContext(
            block.block_id, block.revision, block.raw_content_ref, content,
            len(encoded), hashlib.sha256(encoded).hexdigest(),
        )
