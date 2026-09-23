from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any, Callable, Protocol

from .models import ChoiceBackend, ChoiceOption, ChoiceResult


@dataclass(frozen=True)
class TokenProposal:
    token_id: int
    text: str
    logit: float
    is_eos: bool = False

    @property
    def option_id(self) -> str:
        return f"token_{self.token_id}"


class LogitsBackend(Protocol):
    def start(self, *, context: str, prefix: str) -> "LogitsState": ...

    def next_top_k(self, *, state: "LogitsState", k: int) -> list[TokenProposal]: ...

    def append_token(self, *, state: "LogitsState", token: TokenProposal) -> "LogitsState": ...


@dataclass(frozen=True)
class LogitsState:
    """Immutable helper state; ``metadata`` carries backend-specific token state."""

    value: str
    token_ids: tuple[int, ...] = ()
    metadata: Any = None


@dataclass
class TopKResult:
    status: str
    value: str
    choice_calls: int
    helper_calls: int
    decisions: list[ChoiceResult]
    reason: str = ""


class TopKBuilder:
    RECOVERY = {
        "EXPAND_K": "The current token set may be too narrow; increase k within budget.",
        "REPROPOSE": "Discard this construction and request a fresh field proposal.",
        "BACKTRACK": "Remove the most recently accepted token and continue from the prior prefix.",
        "LOOKUP": "Look up missing environment facts before continuing.",
        "CLARIFY": "Ask the user for missing or ambiguous information.",
        "STOP_UNRESOLVED": "Stop safely and report the unresolved field.",
        "FINISH": "The current prefix is a complete field value and has passed validation.",
    }

    def __init__(
        self,
        *,
        helper: LogitsBackend,
        chooser: ChoiceBackend,
        initial_k: int = 5,
        max_k: int = 20,
        max_tokens: int = 64,
        max_backtracks: int = 2,
        max_choice_calls: int = 128,
        max_helper_calls: int = 128,
        time_budget_seconds: float = 60.0,
        dialogue_end_option_id: str = "END_DIALOGUE",
        min_output_tokens: int = 1,
        allow_end: Callable[[str], bool] | None = None,
    ) -> None:
        self.helper = helper
        self.chooser = chooser
        self.initial_k = initial_k
        self.max_k = max_k
        self.max_tokens = max_tokens
        self.max_backtracks = max_backtracks
        self.max_choice_calls = max_choice_calls
        self.max_helper_calls = max_helper_calls
        self.time_budget_seconds = time_budget_seconds
        self.dialogue_end_option_id = dialogue_end_option_id
        self.min_output_tokens = min_output_tokens
        self.allow_end = allow_end

    def construct(
        self,
        *,
        context: str,
        prefix: str = "",
        complete: Callable[[str], bool],
        prefix_valid: Callable[[str], bool] = lambda _value: True,
    ) -> TopKResult:
        k = self.initial_k
        choices: list[ChoiceResult] = []
        helper_calls = 0
        backtracks = 0
        started_at = perf_counter()
        state = self.helper.start(context=context, prefix=prefix)
        history = [state]

        for _step in range(self.max_tokens):
            if (
                len(choices) >= self.max_choice_calls
                or helper_calls >= self.max_helper_calls
                or perf_counter() - started_at >= self.time_budget_seconds
            ):
                return TopKResult("budget_exhausted", state.value, len(choices), helper_calls, choices, "call or time budget exhausted")

            started = perf_counter()
            tokens = self.helper.next_top_k(state=state, k=k)
            helper_calls += 1
            if perf_counter() - started_at >= self.time_budget_seconds:
                return TopKResult("budget_exhausted", state.value, len(choices), helper_calls, choices, "time budget exhausted")
            candidate_states: dict[int, LogitsState] = {}
            options: list[ChoiceOption] = []
            for token in tokens:
                if token.is_eos:
                    options.append(
                        ChoiceOption(
                            token.option_id,
                            f"Select EOS token id {token.token_id}; current decoded field is {state.value!r}.",
                            token,
                        )
                    )
                    continue
                candidate = self.helper.append_token(state=state, token=token)
                if not prefix_valid(candidate.value):
                    continue
                candidate_states[token.token_id] = candidate
                options.append(
                    ChoiceOption(
                        token.option_id,
                        f"Append exact token id {token.token_id}; decoded field becomes {candidate.value!r}; helper logit {token.logit:.4f}.",
                        token,
                    )
                )
            if complete(state.value):
                options.append(ChoiceOption("FINISH", self.RECOVERY["FINISH"]))
            if (
                self.allow_end is not None
                and len(state.token_ids) >= self.min_output_tokens
            ):
                options.append(
                    ChoiceOption(
                        self.dialogue_end_option_id,
                        "End the current assistant dialogue only if the answer is complete.",
                    )
                )
            if k < self.max_k:
                options.append(ChoiceOption("EXPAND_K", self.RECOVERY["EXPAND_K"]))
            options.extend(
                ChoiceOption(key, description)
                for key, description in self.RECOVERY.items()
                if key not in {"FINISH", "EXPAND_K"}
            )
            if not options:
                return TopKResult("failed", prefix, len(choices), helper_calls, choices, "no valid extensions")

            result = self.chooser.choose(
                state=f"{context}\nCurrent exact prefix: {state.value!r}",
                instructions="Choose one exact token extension or a recovery action. Do not invent or rewrite a token.",
                options=options,
            )
            result = ChoiceResult(
                result.choice,
                result.probabilities,
                result.confidence,
                result.model,
                result.input_tokens,
                result.output_tokens,
                result.latency_ms or (perf_counter() - started) * 1000,
            )
            choices.append(result)

            if result.choice == self.dialogue_end_option_id:
                if (
                    self.allow_end is not None
                    and len(state.token_ids) >= self.min_output_tokens
                    and self.allow_end(state.value)
                ):
                    return TopKResult(
                        "dialogue_complete",
                        state.value,
                        len(choices),
                        helper_calls,
                        choices,
                        "jev_end",
                    )
                return TopKResult(
                    "premature_end",
                    state.value,
                    len(choices),
                    helper_calls,
                    choices,
                    "END_DIALOGUE selected before completion predicate",
                )

            if result.choice == "FINISH":
                if complete(state.value):
                    return TopKResult("complete", state.value, len(choices), helper_calls, choices)
                return TopKResult("failed", state.value, len(choices), helper_calls, choices, "FINISH selected for invalid prefix")
            if result.choice == "EXPAND_K":
                k = min(self.max_k, max(k + 1, k * 2))
                continue
            if result.choice == "BACKTRACK":
                if len(history) <= 1 or backtracks >= self.max_backtracks:
                    return TopKResult("failed", state.value, len(choices), helper_calls, choices, "backtrack budget exhausted")
                history.pop()
                state = history[-1]
                backtracks += 1
                continue
            if result.choice in {"REPROPOSE", "LOOKUP", "CLARIFY", "STOP_UNRESOLVED"}:
                status = {
                    "REPROPOSE": "repropose",
                    "LOOKUP": "lookup_required",
                    "CLARIFY": "clarification_required",
                    "STOP_UNRESOLVED": "unresolved",
                }[result.choice]
                return TopKResult(status, state.value, len(choices), helper_calls, choices, result.choice)

            selected = next((item.payload for item in options if item.option_id == result.choice), None)
            if not isinstance(selected, TokenProposal):
                return TopKResult("failed", state.value, len(choices), helper_calls, choices, "choice did not map to an exact token id")
            if selected.is_eos:
                if complete(state.value):
                    return TopKResult(
                        "complete",
                        state.value,
                        len(choices),
                        helper_calls,
                        choices,
                        "native_eos",
                    )
                return TopKResult("failed", state.value, len(choices), helper_calls, choices, "EOS before field validation")
            state = candidate_states[selected.token_id]
            history.append(state)

        return TopKResult("budget_exhausted", state.value, len(choices), helper_calls, choices, "token budget exhausted")


class TransformersLogitsBackend:
    """Optional causal-LM adapter. CPU is the safe default; CUDA is opt-in."""

    def __init__(
        self, model_id: str, *, device: str = "cpu", dtype: str | None = None
    ) -> None:
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("Install the 'models' extra to use this backend") from exc
        self._torch = torch
        self.tokenizer = AutoTokenizer.from_pretrained(model_id)
        model_kwargs: dict[str, Any] = {}
        if dtype is not None:
            allowed_dtypes = {"float32", "float16", "bfloat16"}
            if dtype not in allowed_dtypes:
                raise ValueError(f"dtype must be one of {sorted(allowed_dtypes)}")
            model_kwargs["dtype"] = getattr(torch, dtype)
        self.model = (
            AutoModelForCausalLM.from_pretrained(model_id, **model_kwargs)
            .to(device)
            .eval()
        )
        self.device = device

    def start(self, *, context: str, prefix: str) -> LogitsState:
        encoded = self.tokenizer(context + prefix, return_tensors="pt").to(self.device)
        prompt_ids = tuple(int(token_id) for token_id in encoded.input_ids[0].tolist())
        return LogitsState(
            value=prefix,
            metadata={"prompt_ids": prompt_ids, "generated_ids": (), "seed_prefix": prefix},
        )

    def next_top_k(self, *, state: LogitsState, k: int) -> list[TokenProposal]:
        metadata = state.metadata
        input_ids = metadata["prompt_ids"] + metadata["generated_ids"]
        tensor = self._torch.tensor([input_ids], dtype=self._torch.long, device=self.device)
        with self._torch.inference_mode():
            logits = self.model(input_ids=tensor).logits[0, -1]
            values, ids = self._torch.topk(logits, k=min(k, logits.numel()))
        eos_id = self.tokenizer.eos_token_id
        return [
            TokenProposal(
                int(token_id),
                self.tokenizer.convert_ids_to_tokens(int(token_id)),
                float(logit),
                int(token_id) == eos_id,
            )
            for logit, token_id in zip(values.tolist(), ids.tolist())
        ]

    def append_token(self, *, state: LogitsState, token: TokenProposal) -> LogitsState:
        metadata = state.metadata
        generated_ids = metadata["generated_ids"] + (token.token_id,)
        decoded = self.tokenizer.decode(
            list(generated_ids),
            skip_special_tokens=False,
            clean_up_tokenization_spaces=False,
        )
        return LogitsState(
            value=metadata["seed_prefix"] + decoded,
            token_ids=state.token_ids + (token.token_id,),
            metadata={
                "prompt_ids": metadata["prompt_ids"],
                "generated_ids": generated_ids,
                "seed_prefix": metadata["seed_prefix"],
            },
        )
