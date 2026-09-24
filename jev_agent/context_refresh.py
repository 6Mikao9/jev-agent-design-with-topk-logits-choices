"""Bounded, revision-guarded context refresh coordination.

This module is an experimental control plane for the next memory design
slice.  It does not treat a Jev choice probability as a calibrated relevance
probability.  A caller supplies a verifier (a Jev adapter, a replay chooser,
or a deterministic test double) which returns a bounded support signal for
each directory candidate.  Verified blocks are committed only if the global
epoch and per-block revisions are unchanged.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from time import perf_counter
from typing import Callable, Iterable

from .context_residency import ContextBlock, ContextFault, ContextResidencyManager


@dataclass(frozen=True)
class ContextVerification:
    """One block-level verifier result.

    ``supported`` is a decision signal, not proof that the block is correct.
    ``confidence`` is retained for ranking and must be validated to [0, 1].
    """

    block_id: str
    supported: bool
    confidence: float
    reason: str = ""


@dataclass(frozen=True)
class ContextRefreshResult:
    status: str
    reason: str = ""
    epoch: int = 0
    candidate_ids: tuple[str, ...] = ()
    selected_ids: tuple[str, ...] = ()
    verifications: tuple[ContextVerification, ...] = ()
    stage_ms: dict[str, float] = field(default_factory=dict)


Verifier = Callable[[ContextBlock, str, int], ContextVerification]


class ContextRefreshCoordinator:
    """Coordinate trigger gating, parallel block verification, and commit.

    The coordinator deliberately keeps the policy small:

    * every request advances a logical decision counter;
    * cooldown and per-phase limits suppress refresh storms;
    * directory candidates are bounded before verifier fan-out;
    * all verifier results carry the request epoch and are committed through
      ``ContextResidencyManager.commit_selected`` with revision checks.

    A production adapter can map ``Verifier`` to Jev calls.  The benchmark
    uses a deterministic function so the runtime protocol is testable without
    network access or credentials.
    """

    def __init__(
        self,
        manager: ContextResidencyManager,
        *,
        max_verifiers: int = 4,
        max_refreshes_per_phase: int = 2,
        cooldown_steps: int = 1,
        max_workers: int = 4,
    ) -> None:
        if min(max_verifiers, max_refreshes_per_phase, max_workers) < 1:
            raise ValueError("verifier and refresh limits must be positive")
        if cooldown_steps < 0:
            raise ValueError("cooldown_steps must be non-negative")
        self.manager = manager
        self.max_verifiers = max_verifiers
        self.max_refreshes_per_phase = max_refreshes_per_phase
        self.cooldown_steps = cooldown_steps
        self.max_workers = max_workers
        self._epoch = 1
        self._decision_step = 0
        self._last_refresh_step: int | None = None
        self._refreshes: dict[str, int] = {}

    @property
    def epoch(self) -> int:
        return self._epoch

    @property
    def decision_step(self) -> int:
        return self._decision_step

    def notify_state_change(self) -> int:
        """Invalidate in-flight results after a task/environment revision."""
        self._epoch += 1
        return self._epoch

    def _suppression_reason(self, phase: str) -> str | None:
        if self._last_refresh_step is not None:
            if self._decision_step - self._last_refresh_step <= self.cooldown_steps:
                return "cooldown"
        if self._refreshes.get(phase, 0) >= self.max_refreshes_per_phase:
            return "phase_budget"
        return None

    def refresh(
        self,
        query: str,
        *,
        phase: str | None,
        verifier: Verifier,
        top_m: int = 4,
        load_k: int | None = None,
        reason: str = "context_fault",
    ) -> ContextRefreshResult:
        """Try one bounded refresh and atomically install verified blocks."""
        if not query:
            raise ValueError("query must not be empty")
        if top_m < 1 or (load_k is not None and load_k < 1):
            raise ValueError("top_m and load_k must be positive")
        if not callable(verifier):
            raise TypeError("verifier must be callable")
        phase_key = phase or ""
        self._decision_step += 1
        suppressed = self._suppression_reason(phase_key)
        if suppressed:
            return ContextRefreshResult("suppressed", suppressed, self._epoch)

        if load_k is None:
            load_k = min(self.manager.max_working, top_m)
        if load_k > self.manager.max_working:
            raise ValueError("load_k exceeds manager.max_working")
        top_m = min(top_m, self.max_verifiers)

        epoch = self._epoch
        started = perf_counter()
        candidates = self.manager.candidates(query)[:top_m]
        directory_ms = (perf_counter() - started) * 1000
        if not candidates:
            return ContextRefreshResult(
                "no_candidates", "directory_empty", epoch, stage_ms={"directory": directory_ms}
            )
        snapshot = {
            candidate.block_id: block
            for candidate in candidates
            for block in self.manager.blocks()
            if block.block_id == candidate.block_id
        }
        revisions = {block_id: block.revision for block_id, block in snapshot.items()}
        verify_started = perf_counter()
        results: list[ContextVerification] = []
        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(candidates)),
                                thread_name_prefix="jev-context-verify") as pool:
            futures = {
                pool.submit(verifier, snapshot[candidate.block_id], query, epoch): candidate.block_id
                for candidate in candidates
            }
            for future in as_completed(futures):
                block_id = futures[future]
                try:
                    result = future.result()
                    if result.block_id != block_id:
                        raise ValueError("verifier returned a different block_id")
                    if not isinstance(result.supported, bool):
                        raise ValueError("supported must be boolean")
                    if not 0 <= float(result.confidence) <= 1:
                        raise ValueError("confidence must be within [0, 1]")
                    results.append(result)
                except Exception as error:
                    results.append(ContextVerification(block_id, False, 0.0, type(error).__name__))
        verify_ms = (perf_counter() - verify_started) * 1000
        results.sort(key=lambda item: (-int(item.supported), -item.confidence, item.block_id))
        selected = tuple(item.block_id for item in results if item.supported)[:load_k]
        if not selected:
            return ContextRefreshResult(
                "no_supported_block", reason or "verifier_rejected_all", epoch,
                tuple(snapshot), (), tuple(results), {"directory": directory_ms, "verify": verify_ms}
            )
        if epoch != self._epoch:
            return ContextRefreshResult(
                "stale_epoch", "task_state_changed_during_verification", epoch,
                tuple(snapshot), selected, tuple(results), {"directory": directory_ms, "verify": verify_ms}
            )
        current = {block.block_id: block.revision for block in self.manager.blocks()
                   if block.block_id in revisions}
        if current != revisions:
            return ContextRefreshResult(
                "stale_revision", "context_revision_changed_during_verification", epoch,
                tuple(snapshot), selected, tuple(results), {"directory": directory_ms, "verify": verify_ms}
            )
        if tuple(self.manager.resident()) and set(selected) == {
            block.block_id for block in self.manager.resident() if not block.pinned
        }:
            return ContextRefreshResult(
                "no_gain", "verified_set_already_resident", epoch,
                tuple(snapshot), selected, tuple(results), {"directory": directory_ms, "verify": verify_ms}
            )
        commit_started = perf_counter()
        try:
            self.manager.commit_selected(selected, expected_revisions=revisions)
        except (ContextFault, ValueError) as error:
            return ContextRefreshResult(
                "commit_rejected", type(error).__name__, epoch,
                tuple(snapshot), selected, tuple(results),
                {"directory": directory_ms, "verify": verify_ms},
            )
        commit_ms = (perf_counter() - commit_started) * 1000
        self._last_refresh_step = self._decision_step
        self._refreshes[phase_key] = self._refreshes.get(phase_key, 0) + 1
        return ContextRefreshResult(
            "committed", reason, epoch, tuple(snapshot), selected, tuple(results),
            {"directory": directory_ms, "verify": verify_ms, "commit": commit_ms},
        )
