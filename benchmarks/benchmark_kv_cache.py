from __future__ import annotations

"""Compare full-prefix decoding with the raw-logit KV-cache helper.

The benchmark reports model-forward time only and synchronizes CUDA around
measurements.  It is intentionally a top-1 continuation benchmark; Jev
choice/network latency must be measured separately.
"""

import argparse
import json
import time
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

from jev_agent.fast_logits import FastLogitsHelper


def _sync(device: str) -> None:
    if device.startswith("cuda"):
        torch.cuda.synchronize(device)


def _top1(logits: torch.Tensor) -> int:
    return int(torch.argmax(logits).item())


def _full_prefix(model, tokenizer, prompt: str, *, device: str, steps: int) -> dict:
    encoded = tokenizer(prompt, return_tensors="pt")
    prompt_ids = [int(item) for item in encoded.input_ids[0].tolist()]
    generated: list[int] = []
    _sync(device)
    started = time.perf_counter()
    for _ in range(steps):
        input_ids = torch.tensor([prompt_ids + generated], dtype=torch.long, device=device)
        with torch.inference_mode():
            logits = model(input_ids=input_ids, use_cache=False).logits[0, -1]
        generated.append(_top1(logits))
    _sync(device)
    elapsed_ms = (time.perf_counter() - started) * 1000
    return {"token_ids": generated, "elapsed_ms": elapsed_ms, "tokens_per_second": steps / (elapsed_ms / 1000)}


def _kv_cache(model, tokenizer, prompt: str, *, device: str, steps: int) -> dict:
    helper = FastLogitsHelper(model, tokenizer, device=device)
    _sync(device)
    prefill_started = time.perf_counter()
    state = helper.prefill(prompt)
    _sync(device)
    prefill_ms = (time.perf_counter() - prefill_started) * 1000
    generated: list[int] = []
    _sync(device)
    decode_started = time.perf_counter()
    for _ in range(steps):
        token = helper.top_k(state, 1)[0]
        generated.append(token.token_id)
        state = helper.advance(state, token)
    _sync(device)
    decode_ms = (time.perf_counter() - decode_started) * 1000
    total_ms = prefill_ms + decode_ms
    return {
        "token_ids": generated,
        "prefill_ms": prefill_ms,
        "decode_ms": decode_ms,
        "elapsed_ms": total_ms,
        "tokens_per_second": steps / (total_ms / 1000),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--prompt", default="请用一句话说明为什么工具调用需要版本校验：")
    parser.add_argument("--steps", type=int, default=32)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.steps < 1:
        raise SystemExit("--steps must be positive")
    tokenizer = AutoTokenizer.from_pretrained(args.model_path, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        args.model_path, trust_remote_code=True, dtype=torch.bfloat16
    ).to(args.device).eval()

    # Warm up kernels before recording either path.  The warm-up is excluded
    # from reported timings and uses a separate short continuation.
    _full_prefix(model, tokenizer, args.prompt, device=args.device, steps=2)
    _kv_cache(model, tokenizer, args.prompt, device=args.device, steps=2)
    full = _full_prefix(model, tokenizer, args.prompt, device=args.device, steps=args.steps)
    cached = _kv_cache(model, tokenizer, args.prompt, device=args.device, steps=args.steps)
    mismatches = sum(a != b for a, b in zip(full["token_ids"], cached["token_ids"]))
    result = {
        "experiment": "full-prefix-vs-kv-cache-raw-logits",
        "model_path": args.model_path,
        "device": args.device,
        "steps": args.steps,
        "prompt": args.prompt,
        "full_prefix": full,
        "kv_cache": cached,
        "top1_mismatches": mismatches,
        "decode_speedup": full["elapsed_ms"] / cached["decode_ms"],
        "total_speedup": full["elapsed_ms"] / cached["elapsed_ms"],
        "notes": [
            "Top-k uses raw logits; no softmax is computed.",
            "Full-prefix and KV paths share one loaded model but are timed separately.",
            "Jev choice, network, and tool latency are not included.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("steps", "top1_mismatches", "decode_speedup")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
