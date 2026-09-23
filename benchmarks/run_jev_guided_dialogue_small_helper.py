from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

from benchmarks.run_jev_guided_dialogue import CASES, complete, template


def run_case(model, tokenizer, case: dict, *, top_k: int, max_tokens: int) -> dict:
    prompt = template(tokenizer, case["user"])
    encoded = tokenizer(prompt, return_tensors="pt").to("cuda")
    prompt_ids = encoded.input_ids[0].tolist()
    generated_ids: list[int] = []
    answer = ""
    trace: list[dict] = []
    helper_ms = 0.0
    chooser_ms = 0.0
    started = time.perf_counter()
    eos_id = tokenizer.eos_token_id

    for step in range(max_tokens):
        input_ids = torch.tensor([prompt_ids + generated_ids], dtype=torch.long, device="cuda")
        helper_started = time.perf_counter()
        with torch.inference_mode():
            logits = model(input_ids=input_ids).logits[0, -1].float()
            values, ids = torch.topk(logits, k=min(top_k, logits.numel()))
        step_helper_ms = (time.perf_counter() - helper_started) * 1000
        helper_ms += step_helper_ms
        candidates = [
            {
                "rank": rank,
                "token_id": int(token_id),
                "decoded": tokenizer.decode([int(token_id)], skip_special_tokens=False),
                "logit": float(value),
            }
            for rank, (value, token_id) in enumerate(zip(values.tolist(), ids.tolist()), 1)
        ]
        end_available = complete(case, answer)
        chooser_started = time.perf_counter()
        if end_available:
            selected_choice = "END_DIALOGUE"
        else:
            selected_choice = f"TOKEN_{candidates[0]['token_id']}"
        step_chooser_ms = (time.perf_counter() - chooser_started) * 1000
        chooser_ms += step_chooser_ms
        trace.append(
            {
                "step": step,
                "selected": selected_choice,
                "selected_rank": None if selected_choice == "END_DIALOGUE" else 1,
                "end_offered": True,
                "end_available": end_available,
                "helper_latency_ms": round(step_helper_ms, 2),
                "chooser_latency_ms": round(step_chooser_ms, 2),
            }
        )
        if selected_choice == "END_DIALOGUE":
            elapsed_ms = (time.perf_counter() - started) * 1000
            return {
                "answer": answer,
                "status": "dialogue_complete",
                "stop_reason": "jev_end_proxy",
                "output_tokens": step,
                "trace": trace,
                "chooser": "local_top1_proxy",
                "elapsed_ms": round(elapsed_ms, 2),
                "helper_latency_ms_total": round(helper_ms, 2),
                "chooser_latency_ms_total": round(chooser_ms, 2),
                "helper_tokens_per_second": round(step / (helper_ms / 1000), 2) if helper_ms else None,
                "tokens_per_second": round(step / (elapsed_ms / 1000), 2) if elapsed_ms else None,
            }
        selected_id = candidates[0]["token_id"]
        generated_ids.append(selected_id)
        answer = tokenizer.decode(generated_ids, skip_special_tokens=False, clean_up_tokenization_spaces=False)
        if selected_id == eos_id:
            elapsed_ms = (time.perf_counter() - started) * 1000
            return {
                "answer": answer,
                "status": "premature_end",
                "stop_reason": "native_eos",
                "output_tokens": step + 1,
                "trace": trace,
                "chooser": "local_top1_proxy",
                "elapsed_ms": round(elapsed_ms, 2),
                "helper_latency_ms_total": round(helper_ms, 2),
                "chooser_latency_ms_total": round(chooser_ms, 2),
                "helper_tokens_per_second": round((step + 1) / (helper_ms / 1000), 2) if helper_ms else None,
                "tokens_per_second": round((step + 1) / (elapsed_ms / 1000), 2) if elapsed_ms else None,
            }
    elapsed_ms = (time.perf_counter() - started) * 1000
    return {
        "answer": answer,
        "status": "budget_exhausted",
        "stop_reason": "budget_exhausted",
        "output_tokens": max_tokens,
        "trace": trace,
        "chooser": "local_top1_proxy",
        "elapsed_ms": round(elapsed_ms, 2),
        "helper_latency_ms_total": round(helper_ms, 2),
        "chooser_latency_ms_total": round(chooser_ms, 2),
        "helper_tokens_per_second": round(max_tokens / (helper_ms / 1000), 2) if helper_ms else None,
        "tokens_per_second": round(max_tokens / (elapsed_ms / 1000), 2) if elapsed_ms else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--top-k", type=int, default=100)
    parser.add_argument("--max-tokens", type=int, default=160)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    tokenizer = AutoTokenizer.from_pretrained(args.model_path, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(args.model_path, trust_remote_code=True, dtype=torch.bfloat16).to("cuda").eval()
    cases = []
    for case in CASES:
        guided = run_case(model, tokenizer, case, top_k=args.top_k, max_tokens=args.max_tokens)
        cases.append({"id": case["id"], "user": case["user"], "guided": guided})
        print(case["id"], guided["status"], guided["stop_reason"], guided["output_tokens"])
    args.output.write_text(
        json.dumps(
            {
                "experiment": "jev-guided-dialogue-small-helper",
                "helper_model": "Qwen3.5-0.8B",
                "helper_model_path": args.model_path,
                "top_k": args.top_k,
                "chooser": "local_top1_proxy",
                "live_jev_enabled": bool(os.environ.get("LIVE_JEV")),
                "cases": cases,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
