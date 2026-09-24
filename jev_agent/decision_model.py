"""Replaceable Decision Model backend boundary.

The runtime consumes a typed choice distribution and does not depend on Jev's
transport.  ``ChoiceBackendAdapter`` keeps the existing chooser protocol
usable while ``ReplayDecisionModel`` and ``OracleDecisionModel`` support
mechanism and capability experiments without network calls.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol, Sequence

from .models import ChoiceBackend, ChoiceOption, ChoiceResult, validate_choice_result


@dataclass(frozen=True)
class DecisionRequest:
    state: str
    instructions: str
    options: tuple[ChoiceOption, ...]
    context: tuple[str, ...] = ()


class DecisionModel(Protocol):
    def decide(self, request: DecisionRequest) -> ChoiceResult: ...


class ChoiceBackendAdapter(ChoiceBackend):
    """Expose any DecisionModel through the existing ``choose`` protocol."""

    def __init__(self, model: DecisionModel) -> None:
        self.model = model

    def choose(
        self, *, state: str, instructions: str, options: list[ChoiceOption]
    ) -> ChoiceResult:
        if not options:
            raise ValueError("decision model requires at least one option")
        result = self.model.decide(DecisionRequest(state, instructions, tuple(options)))
        return validate_choice_result(result, options)


class ReplayDecisionModel:
    """Replay fixed results for deterministic runtime tests."""

    def __init__(self, results: Sequence[ChoiceResult]) -> None:
        if not results:
            raise ValueError("at least one replay result is required")
        self._results = tuple(results)
        self._index = 0

    def decide(self, request: DecisionRequest) -> ChoiceResult:
        if self._index >= len(self._results):
            raise RuntimeError("decision replay exhausted")
        result = self._results[self._index]
        self._index += 1
        valid = {option.option_id for option in request.options}
        return validate_choice_result(result, request.options)


class OracleDecisionModel:
    """Deterministic one-hot backend for mechanism upper-bound experiments."""

    def __init__(
        self,
        selector: Callable[[DecisionRequest], str],
        *,
        model_name: str = "oracle",
    ) -> None:
        self.selector = selector
        self.model_name = model_name

    def decide(self, request: DecisionRequest) -> ChoiceResult:
        choice = self.selector(request)
        valid = {option.option_id for option in request.options}
        if choice not in valid:
            raise ValueError(f"oracle selected an unavailable option: {choice}")
        probabilities = {
            option.option_id: 1.0 if option.option_id == choice else 0.0
            for option in request.options
        }
        return validate_choice_result(
            ChoiceResult(choice, probabilities, 1.0, self.model_name), request.options
        )
