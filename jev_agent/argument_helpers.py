"""Optional proposal adapter over the existing raw-logits/KV helper protocol."""
from __future__ import annotations

import json
from dataclasses import dataclass
from time import perf_counter
from typing import Callable, Sequence

from .arguments import FieldContext, ValueProposal
from .topk import LogitsBackend


@dataclass(frozen=True)
class GreedyFieldProposer:
    """Decode one advisory value, with a separate helper session per invocation.

    A factory can wrap FastLogitsHelper for KV reuse *within* this field. It must
    not return one mutable cache shared between concurrent fields. There is no
    claim of diverse decoding here: repeated greedy attempts may repeat a value.
    """

    helper_factory: Callable[[FieldContext], LogitsBackend]
    max_tokens: int = 64
    time_budget_seconds: float = 30.0

    def __call__(self, context: FieldContext) -> Sequence[ValueProposal]:
        helper = self.helper_factory(context)
        prompt = (
            f"{context.state_text}\nField: {context.name}\n"
            f"Schema: {json.dumps(context.schema, ensure_ascii=False)}\n"
            f"Dependencies: {json.dumps(context.dependencies, ensure_ascii=False)}\n"
            f"Previous issues: {context.errors}\n"
            "Output only the exact field value. For a string output plain text; otherwise output one JSON value.\n"
        )
        started = perf_counter()
        state = helper.start(context=prompt, prefix="")
        ended = False
        for _ in range(self.max_tokens):
            if perf_counter() - started > self.time_budget_seconds:
                return []
            tokens = helper.next_top_k(state=state, k=1)
            if not tokens:
                return []
            if tokens[0].is_eos:
                ended = True
                break
            state = helper.append_token(state=state, token=tokens[0])
        # A length-truncated field is not silently treated as complete.
        if not ended or perf_counter() - started > self.time_budget_seconds:
            return []
        try:
            value = state.value if context.schema.get("type") == "string" else json.loads(state.value)
        except ValueError:
            return []
        return [ValueProposal(value, source="small_model_greedy")]
