"""Raw-logit causal LM helper with a reusable Transformers KV cache.

This module deliberately has no Transformers dependency at import time.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FastToken:
    token_id: int
    piece: str
    logit: float
    is_eos: bool = False


@dataclass(frozen=True)
class FastLogitsState:
    token_ids: tuple[int, ...]
    token_pieces: tuple[str, ...]
    past_key_values: Any
    next_logits: Any
    prompt_length: int


class FastLogitsHelper:
    """Minimal prefill/decode helper for a single active sequence.

    ``prefill`` evaluates the full prompt once. ``advance`` feeds exactly one
    selected token together with the prior cache, producing logits for the
    following token. No softmax or normalization is performed.
    """

    def __init__(
        self,
        model: Any,
        tokenizer: Any,
        *,
        device: str | None = None,
        max_cached_decodes: int = 128,
    ):
        try:
            import torch
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("Install torch to use FastLogitsHelper") from exc
        self.torch = torch
        self.model = model
        self.tokenizer = tokenizer
        self.device = device or str(next(model.parameters()).device)
        if max_cached_decodes < 1:
            raise ValueError("max_cached_decodes must be positive")
        self.max_cached_decodes = max_cached_decodes
        # TopKBuilder validates every candidate before Jev chooses one.  Keep
        # one decode result per pending state so validation of k candidates
        # does not run k identical model forwards.
        self._materialized: dict[tuple[int, int], FastLogitsState] = {}

    def _input(self, ids: list[int]):
        return self.torch.tensor([ids], dtype=self.torch.long, device=self.device)

    def prefill(self, text: str) -> FastLogitsState:
        encoded = self.tokenizer(text, return_tensors="pt")
        input_ids = encoded.input_ids.to(self.device)
        ids = tuple(int(x) for x in input_ids[0].tolist())
        model_inputs: dict[str, Any] = {"input_ids": input_ids}
        attention_mask = getattr(encoded, "attention_mask", None)
        if attention_mask is not None:
            model_inputs["attention_mask"] = attention_mask.to(self.device)
        with self.torch.inference_mode():
            out = self.model(**model_inputs, use_cache=True)
        # ``token_ids`` tracks only tokens accepted after the prompt.  Keeping
        # prompt ids in ``prompt_length`` avoids mixing context with generated
        # output when a caller branches or checks an end condition.
        return FastLogitsState((), (), out.past_key_values, out.logits[0, -1], len(ids))

    def top_k(self, state: FastLogitsState, k: int) -> list[FastToken]:
        if k < 1:
            raise ValueError("k must be positive")
        logits = state.next_logits
        values, ids = self.torch.topk(logits, k=min(k, logits.numel()))
        eos = getattr(self.tokenizer, "eos_token_id", None)
        return [
            FastToken(int(i), self.tokenizer.convert_ids_to_tokens(int(i)), float(v), int(i) == eos)
            for v, i in zip(values.tolist(), ids.tolist())
        ]

    def advance(self, state: FastLogitsState, token: FastToken | int) -> FastLogitsState:
        token_id = token.token_id if isinstance(token, FastToken) else int(token)
        with self.torch.inference_mode():
            out = self.model(
                input_ids=self._input([token_id]),
                past_key_values=state.past_key_values,
                use_cache=True,
            )
        piece = self.tokenizer.convert_ids_to_tokens(token_id)
        return FastLogitsState(
            state.token_ids + (token_id,),
            state.token_pieces + (piece,),
            out.past_key_values,
            out.logits[0, -1],
            state.prompt_length,
        )

    # The following three methods implement the existing LogitsBackend
    # protocol, allowing this helper to be dropped into TopKBuilder.  Appending
    # a candidate is lazy: the first call to the next step materializes one
    # single-token decode, and candidate validation reuses that result.
    def start(self, *, context: str, prefix: str):
        from .topk import LogitsState

        fast_state = self.prefill(context + prefix)
        return LogitsState(
            value=prefix,
            token_ids=(),
            metadata={"fast_state": fast_state, "seed_prefix": prefix, "pending": None},
        )

    def _materialize(self, state: Any) -> FastLogitsState:
        metadata = state.metadata
        fast_state = metadata["fast_state"]
        pending = metadata.get("pending")
        if pending is None:
            return fast_state
        key = (id(fast_state), int(pending))
        cached = self._materialized.get(key)
        if cached is None:
            cached = self.advance(fast_state, int(pending))
            if len(self._materialized) >= self.max_cached_decodes:
                self._materialized.pop(next(iter(self._materialized)))
            self._materialized[key] = cached
        return cached

    def next_top_k(self, *, state: Any, k: int):
        from .topk import TokenProposal

        materialized = self._materialize(state)
        return [
            TokenProposal(item.token_id, item.piece, item.logit, item.is_eos)
            for item in self.top_k(materialized, k)
        ]

    def append_token(self, *, state: Any, token: Any):
        from .topk import LogitsState

        metadata = state.metadata
        materialized = self._materialize(state)
        generated = materialized.token_ids + (int(token.token_id),)
        decoded = self.tokenizer.decode(
            list(generated),
            skip_special_tokens=False,
            clean_up_tokenization_spaces=False,
        )
        return LogitsState(
            value=metadata["seed_prefix"] + decoded,
            token_ids=generated,
            metadata={
                "fast_state": materialized,
                "seed_prefix": metadata["seed_prefix"],
                "pending": int(token.token_id),
            },
        )
