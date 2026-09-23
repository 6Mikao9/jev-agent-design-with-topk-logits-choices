from __future__ import annotations

"""Optional diffusion/speculative proposal interface.

This module is model-agnostic.  It lets an agent request several candidate
parameter sets in parallel and then pass them through an explicit acceptance
function.  A real diffusion or masked-generation backend can implement the
protocol without becoming a hard dependency of the core prototype.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, Protocol, Sequence


@dataclass(frozen=True)
class DiffusionCandidate:
    candidate_id: str
    value: Any
    seed: int
    parameters: dict[str, Any]


class DiffusionCandidateBackend(Protocol):
    def generate(self, *, prompt: str, seed: int, parameters: dict[str, Any]) -> Any: ...


class ParallelCandidateGenerator:
    """Generate independent candidates with bounded parallelism."""

    def __init__(self, backend: DiffusionCandidateBackend, *, max_workers: int = 2) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be positive")
        self.backend = backend
        self.max_workers = max_workers

    def generate(
        self,
        *,
        prompt: str,
        seeds: Sequence[int],
        parameter_sets: Sequence[dict[str, Any]],
        accept: Callable[[DiffusionCandidate], bool] | None = None,
    ) -> list[DiffusionCandidate]:
        if len(seeds) != len(parameter_sets):
            raise ValueError("seeds and parameter_sets must have the same length")

        def one(index: int) -> DiffusionCandidate:
            seed = int(seeds[index])
            params = dict(parameter_sets[index])
            value = self.backend.generate(prompt=prompt, seed=seed, parameters=params)
            return DiffusionCandidate(f"diffusion-{index}", value, seed, params)

        # map preserves input order even though work executes concurrently.
        with ThreadPoolExecutor(max_workers=min(self.max_workers, max(1, len(seeds)))) as pool:
            candidates = list(pool.map(one, range(len(seeds))))
        return [item for item in candidates if accept is None or accept(item)]
