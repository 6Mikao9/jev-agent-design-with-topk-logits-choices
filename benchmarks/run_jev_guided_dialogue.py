from __future__ import annotations

"""Small end-to-end dialogue experiment.

Qwen3.8-27B supplies a fresh top-20 vocabulary at each step.  A chooser then
selects one exact token or the explicit END_DIALOGUE control.  The default
chooser is a deterministic local proxy so the experiment is reproducible and
does not spend a live Jev key; setting LIVE_JEV=1 enables TypeSafeJevChooser.
"""

import argparse
import json
import os
import time
import urllib.request
from pathlib import Path


CASES = [
    {
        "id": "math",
        "user": "Compute 17 × 19. Give the expression and result in one sentence.",
        "min_chars": 10,
        "predicate": "len(text)>=10 and '=' in text and '323' in text",
    },
    {
        "id": "tcp_udp",
        "user": "Explain TCP and UDP for a beginner in exactly three bullet points.",
        "min_chars": 45,
        "predicate": "sum(1 for line in text.splitlines() if line.lstrip().startswith('*'))>=3 and text.rstrip().endswith(('.', '!', '?'))",
    },
    {
        "id": "backup",
        "user": "Give a four-step checklist for backing up important files.",
        "min_chars": 45,
        "predicate": "'4.' in text and len(text.split('4.', 1)[1].strip())>=20 and text.rstrip().endswith(('.', '!', '?'))",
    },
    {
        "id": "conflict",
        "user": (
            "I want to leave on Friday, but I am only free on Saturday. "
            "Identify the contradiction, quote the two conflicting facts, and ask exactly one clarifying question."
        ),
        "min_chars": 55,
        "predicate": "('Friday' in text or '周五' in text) and ('Saturday' in text or '周六' in text) and ('?' in text or '？' in text)",
    },
]


def post_json(url: str, payload: dict, timeout: float = 180.0) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def template(tokenizer, user: str) -> str:
    return tokenizer.apply_chat_template(
        [
            {"role": "system", "content": "Answer directly and concisely."},
            {"role": "user", "content": user},
        ],
        tokenize=False,
        add_generation_prompt=True,
        enable_thinking=False,
    )


def complete(case: dict, text: str) -> bool:
    if len(text) < case["min_chars"]:
        return False
    # The fixtures are intentionally small and fixed; keeping predicates in
    # data makes the end decision auditable instead of using punctuation alone.
    safe_builtins = {"len": len, "any": any, "sum": sum}
    return bool(eval(case["predicate"], {"__builtins__": safe_builtins, "text": text}, {}))


def baseline(base_url: str, tokenizer, case: dict) -> dict:
    started = time.perf_counter()
    result = post_json(
        f"{base_url}/generate",
        {
            "text": template(tokenizer, case["user"]),
            "sampling_params": {"temperature": 0, "top_p": 1, "max_new_tokens": 160},
        },
    )
    elapsed_ms = (time.perf_counter() - started) * 1000
    return {
        "answer": result.get("text", ""),
        "finish_reason": result.get("meta_info", {}).get("finish_reason"),
        "elapsed_ms": round(elapsed_ms, 2),
        "tokens_per_second": round(len(result.get("output_ids", [])) / (elapsed_ms / 1000), 2) if elapsed_ms else None,
    }


def guided(base_url: str, tokenizer, case: dict, *, k: int = 20, max_tokens: int = 160) -> dict:
    prompt = template(tokenizer, case["user"])
    answer = ""
    trace: list[dict] = []
    eos_id = tokenizer.eos_token_id
    run_started = time.perf_counter()
    helper_latency_ms = 0.0
    chooser_latency_ms = 0.0
    live = bool(os.environ.get("LIVE_JEV"))
    chooser = None
    if live:
        from jev_agent.jev_client import TypeSafeJevChooser

        chooser = TypeSafeJevChooser(timeout_seconds=30.0)
    for step in range(max_tokens):
        request_started = time.perf_counter()
        result = post_json(
            f"{base_url}/generate",
            {
                "text": prompt + answer,
                "sampling_params": {"temperature": 0, "top_p": 1, "max_new_tokens": 1},
                "return_logprob": True,
                "top_logprobs_num": k,
            },
        )
        step_latency_ms = (time.perf_counter() - request_started) * 1000
        helper_latency_ms += step_latency_ms
        top = result["meta_info"]["output_top_logprobs"][0]
        candidates = []
        for rank, (logprob, token_id, _) in enumerate(top, 1):
            token_id = int(token_id)
            candidates.append(
                {
                    "rank": rank,
                    "token_id": token_id,
                    "piece": tokenizer.convert_ids_to_tokens(token_id),
                    "decoded": tokenizer.decode([token_id], skip_special_tokens=False),
                    "logprob": float(logprob),
                }
            )
        end_available = complete(case, answer)
        end_offered = True
        selected_choice = None
        selected_rank = None
        chooser_meta = {"model": "local_top1_proxy", "confidence": 1.0, "latency_ms": 0.0}
        choice_started = time.perf_counter()
        if chooser is not None:
            from jev_agent.models import ChoiceOption

            options = [
                ChoiceOption(
                    f"TOKEN_{c['token_id']}",
                    f"Append exact helper token {c['token_id']} ({c['decoded']!r}) at rank {c['rank']}.",
                )
                for c in candidates
            ]
            options.append(
                ChoiceOption(
                    "END_DIALOGUE",
                    "End the current answer; accept only if the task-specific completion predicate is true.",
                )
            )
            choice_result = chooser.choose(
                state=f"User request: {case['user']}\nCurrent answer: {answer!r}\nCandidates: {candidates!r}",
                instructions="Choose exactly one candidate token or END_DIALOGUE. Do not invent a token.",
                options=options,
            )
            selected_choice = choice_result.choice
            chooser_meta = {
                "model": choice_result.model,
                "confidence": choice_result.confidence,
                "latency_ms": choice_result.latency_ms,
            }
            selected_rank = next((c["rank"] for c in candidates if f"TOKEN_{c['token_id']}" == selected_choice), None)
        elif end_available:
            selected_choice = "END_DIALOGUE"
        else:
            selected_choice = f"TOKEN_{candidates[0]['token_id']}"
        chooser_step_latency_ms = (time.perf_counter() - choice_started) * 1000
        chooser_latency_ms += chooser_step_latency_ms
        chooser_meta["measured_latency_ms"] = round(chooser_step_latency_ms, 2)

        if selected_choice == "END_DIALOGUE":
            trace.append({"step": step, "current_text": answer, "candidates": candidates, "selected": "END_DIALOGUE", "selected_rank": None, "end_offered": end_offered, "end_available": end_available, "helper_latency_ms": round(step_latency_ms, 2), "chooser_latency_ms": round(chooser_step_latency_ms, 2), "chooser": chooser_meta})
            elapsed_ms = (time.perf_counter() - run_started) * 1000
            if not end_available:
                return {
                    "answer": answer,
                    "status": "premature_end",
                    "stop_reason": "premature_end",
                    "output_tokens": step,
                    "trace": trace,
                    "chooser": chooser_meta,
                    "elapsed_ms": round(elapsed_ms, 2),
                    "helper_latency_ms_total": round(helper_latency_ms, 2),
                    "chooser_latency_ms_total": round(chooser_latency_ms, 2),
                    "helper_tokens_per_second": round(step / (helper_latency_ms / 1000), 2) if helper_latency_ms else None,
                    "tokens_per_second": round(step / (elapsed_ms / 1000), 2) if elapsed_ms else None,
                }
            return {
                "answer": answer,
                "status": "dialogue_complete",
                "stop_reason": "jev_end" if chooser is not None else "jev_end_proxy",
                "output_tokens": step,
                "trace": trace,
                "chooser": chooser_meta,
                "elapsed_ms": round(elapsed_ms, 2),
                "helper_latency_ms_total": round(helper_latency_ms, 2),
                "chooser_latency_ms_total": round(chooser_latency_ms, 2),
                "helper_tokens_per_second": round(step / (helper_latency_ms / 1000), 2) if helper_latency_ms else None,
                "tokens_per_second": round(step / (elapsed_ms / 1000), 2) if elapsed_ms else None,
            }
        selected = next(c for c in candidates if f"TOKEN_{c['token_id']}" == selected_choice)
        trace.append({"step": step, "current_text": answer, "candidates": candidates, "selected": f"TOKEN_{selected['token_id']}", "selected_rank": selected_rank or 1, "end_offered": end_offered, "end_available": end_available, "helper_latency_ms": round(step_latency_ms, 2), "chooser_latency_ms": round(chooser_step_latency_ms, 2), "chooser": chooser_meta})
        if selected["token_id"] == eos_id:
            status = "complete" if complete(case, answer) else "premature_end"
            elapsed_ms = (time.perf_counter() - run_started) * 1000
            return {"answer": answer, "status": status, "stop_reason": "native_eos", "output_tokens": step, "trace": trace, "chooser": chooser_meta, "elapsed_ms": round(elapsed_ms, 2), "helper_latency_ms_total": round(helper_latency_ms, 2), "chooser_latency_ms_total": round(chooser_latency_ms, 2), "helper_tokens_per_second": round(step / (helper_latency_ms / 1000), 2) if helper_latency_ms else None, "tokens_per_second": round(step / (elapsed_ms / 1000), 2) if elapsed_ms else None}
        answer += selected["decoded"]
    elapsed_ms = (time.perf_counter() - run_started) * 1000
    return {"answer": answer, "status": "budget_exhausted", "stop_reason": "budget_exhausted", "output_tokens": max_tokens, "trace": trace, "chooser": chooser_meta, "elapsed_ms": round(elapsed_ms, 2), "helper_latency_ms_total": round(helper_latency_ms, 2), "chooser_latency_ms_total": round(chooser_latency_ms, 2), "helper_tokens_per_second": round(max_tokens / (helper_latency_ms / 1000), 2) if helper_latency_ms else None, "tokens_per_second": round(max_tokens / (elapsed_ms / 1000), 2) if elapsed_ms else None}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:30000")
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(args.model_path, trust_remote_code=True)
    rows = []
    for case in CASES:
        b = baseline(args.base_url, tokenizer, case)
        g = guided(args.base_url, tokenizer, case)
        rows.append({"id": case["id"], "user": case["user"], "completion_predicate": case["predicate"], "baseline": b, "guided": g})
        print(case["id"], g["status"], g["stop_reason"], len(g["answer"]))
    args.output.write_text(
        json.dumps(
            {
                "experiment": "jev-guided-dialogue-with-explicit-end",
                "helper_model": "Qwen3.8-27B",
                "chooser": "local_top1_proxy",
                "live_jev_enabled": bool(os.environ.get("LIVE_JEV")),
                "end_option": {"id": "END_DIALOGUE", "description": "End only after the case predicate accepts the complete answer."},
                "cases": rows,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
