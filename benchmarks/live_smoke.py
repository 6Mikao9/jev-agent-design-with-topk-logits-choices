from __future__ import annotations

import json

from jev_agent.jev_client import TypeSafeJevChooser
from jev_agent.models import ChoiceOption


def main() -> None:
    result = TypeSafeJevChooser().choose(
        state=(
            "Search staging service logs from the last 30 minutes for errors. "
            "The tool requires service, query, and time_range."
        ),
        instructions="Choose the option that completes the requested log search correctly.",
        options=[
            ChoiceOption("error_query", "Search staging logs for severity=error over the last 30 minutes."),
            ChoiceOption("warning_query", "Search staging logs for severity=warning over the last 30 minutes."),
            ChoiceOption("fallback_topk", "Neither complete query fits; construct the missing query using helper logits Top-k."),
        ],
    )
    print(
        json.dumps(
            {
                "model": result.model,
                "choice": result.choice,
                "confidence": result.confidence,
                "probabilities": result.probabilities,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "latency_ms": round(result.latency_ms, 1),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
