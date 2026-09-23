from __future__ import annotations

import json
import os
import ssl
from time import perf_counter
from urllib.error import HTTPError, URLError
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener

from .models import ChoiceBackend, ChoiceOption, ChoiceResult


class TypeSafeJevChooser(ChoiceBackend):
    """Small direct HTTPS adapter for the official TypeSafe System One API.

    Proxy discovery is disabled deliberately. TLS verification remains enabled.
    Credentials are read from the process environment and never logged.
    """

    def __init__(
        self,
        *,
        model: str = "jev-latest",
        api_key: str | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.api_key = api_key or os.environ.get("TYPESAFE_API_KEY") or os.environ.get("JEV_API_KEY")
        if not self.api_key:
            raise RuntimeError("Set TYPESAFE_API_KEY or JEV_API_KEY in the process environment")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self._opener = build_opener(
            ProxyHandler({}),
            HTTPSHandler(context=ssl.create_default_context()),
        )

    def choose(
        self, *, state: str, instructions: str, options: list[ChoiceOption]
    ) -> ChoiceResult:
        if not options:
            raise ValueError("Jev Choice requires at least one option")
        if len(options) > 255:
            raise ValueError("Jev Choice supports at most 255 options")
        criteria = {option.option_id: option.description for option in options}
        payload = {
            "model": self.model,
            "state": state,
            "questions": {
                "decision": {
                    "type": "choice",
                    "instructions": instructions,
                    "criteria": criteria,
                }
            },
        }
        request = Request(
            "https://api.typesafe.ai/v1/systemone",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        started = perf_counter()
        try:
            with self._opener.open(request, timeout=self.timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise RuntimeError(f"TypeSafe API returned HTTP {exc.code}") from None
        except URLError as exc:
            raise RuntimeError(f"Could not reach TypeSafe API: {exc.reason}") from None

        answer = data["answers"]["decision"]
        if answer["choice"] not in criteria:
            raise RuntimeError("TypeSafe returned a choice outside the submitted option set")
        usage = data.get("usage", {})
        return ChoiceResult(
            choice=answer["choice"],
            probabilities=dict(answer["probabilities"]),
            confidence=float(answer["confidence"]),
            model=str(data["model"]),
            input_tokens=int(usage.get("input_tokens", 0) or 0),
            output_tokens=int(usage.get("output_tokens", 0) or 0),
            latency_ms=(perf_counter() - started) * 1000,
        )
