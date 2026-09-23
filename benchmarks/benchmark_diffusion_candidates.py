from __future__ import annotations

"""Run a small masked-diffusion proposal experiment.

This is a proposal generator, not an autoregressive next-token helper.  It
fills several masked continuation positions in parallel and returns complete
candidate strings for Jev to accept, reject, or request clarification on.
"""

import argparse
import json
import time
from pathlib import Path
from typing import Any

import torch
from transformers import AutoModelForMaskedLM, AutoTokenizer

from jev_agent.diffusion import ParallelCandidateGenerator


class MaskedDiffusionBackend:
    def __init__(self, model: Any, tokenizer: Any, *, device: str) -> None:
        self.model = model
        self.tokenizer = tokenizer
        self.device = device
        self.mask_id = int(getattr(model.config, "mask_token_id", tokenizer.mask_token_id))
        self.vocab_size = int(getattr(model.config, "vocab_size", self.mask_id))
        self.forbidden_ids = {
            int(token_id)
            for token_id in getattr(tokenizer, "all_special_ids", [])
            if int(token_id) != self.mask_id and int(token_id) < self.vocab_size
        }

    def generate(self, *, prompt: str, seed: int, parameters: dict[str, Any]) -> str:
        new_tokens = int(parameters.get("new_tokens", 24))
        steps = int(parameters.get("steps", 4))
        temperature = max(float(parameters.get("temperature", 1.0)), 1e-4)
        if new_tokens < 1 or steps < 1:
            raise ValueError("new_tokens and steps must be positive")
        prompt_ids = self.tokenizer(prompt, return_tensors="pt").input_ids[0].tolist()
        max_positions = int(getattr(self.model.config, "n_positions", 1024))
        total = min(len(prompt_ids) + new_tokens, max_positions)
        if total <= len(prompt_ids):
            raise ValueError("prompt leaves no room for a continuation")
        ids = torch.full((1, total), self.mask_id, dtype=torch.long, device=self.device)
        ids[0, : len(prompt_ids)] = torch.tensor(prompt_ids, dtype=torch.long, device=self.device)
        generator = torch.Generator(device=self.device).manual_seed(int(seed))
        remaining_steps = steps
        with torch.inference_mode():
            while True:
                mask_positions = ids[0].eq(self.mask_id).nonzero(as_tuple=False).flatten()
                if mask_positions.numel() == 0:
                    break
                logits = self.model(input_ids=ids).logits[0, mask_positions, : self.vocab_size]
                scaled = logits / temperature
                if self.forbidden_ids:
                    scaled[:, list(self.forbidden_ids)] = float("-inf")
                probabilities = torch.softmax(scaled, dim=-1)
                values, top_ids = probabilities.max(dim=-1)
                reveal = max(1, (mask_positions.numel() + remaining_steps - 1) // remaining_steps)
                reveal = min(reveal, mask_positions.numel())
                selected = torch.topk(values, k=reveal).indices
                for row in selected.tolist():
                    position = int(mask_positions[row])
                    if bool(parameters.get("sample", False)):
                        token_id = int(torch.multinomial(probabilities[row], 1, generator=generator).item())
                    else:
                        token_id = int(top_ids[row])
                    ids[0, position] = token_id
                remaining_steps = max(1, remaining_steps - 1)
        continuation = ids[0, len(prompt_ids) :].tolist()
        return self.tokenizer.decode(continuation, skip_special_tokens=False, clean_up_tokenization_spaces=False)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--prompt", default="A safe tool call should")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    tokenizer = AutoTokenizer.from_pretrained(args.model_path, trust_remote_code=True)
    model = AutoModelForMaskedLM.from_pretrained(args.model_path, trust_remote_code=True).to(args.device).eval()
    backend = MaskedDiffusionBackend(model, tokenizer, device=args.device)
    parameter_sets = [
        {"new_tokens": 24, "steps": 4, "temperature": 0.8, "sample": False},
        {"new_tokens": 24, "steps": 8, "temperature": 1.0, "sample": False},
        {"new_tokens": 32, "steps": 8, "temperature": 1.2, "sample": True},
    ]
    started = time.perf_counter()
    candidates = ParallelCandidateGenerator(backend, max_workers=2).generate(
        prompt=args.prompt,
        seeds=[11, 22, 33],
        parameter_sets=parameter_sets,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000
    result = {
        "experiment": "masked-diffusion-parallel-proposals",
        "model_path": args.model_path,
        "prompt": args.prompt,
        "elapsed_ms": elapsed_ms,
        "candidate_count": len(candidates),
        "candidates": [
            {"candidate_id": item.candidate_id, "seed": item.seed, "parameters": item.parameters, "value": item.value}
            for item in candidates
        ],
        "notes": [
            "This BabyLM MDLM checkpoint is bidirectional masked diffusion, not an AR next-token logits source.",
            "Candidates are complete proposal strings for Jev acceptance/rejection; no external tool was executed.",
            "Special control tokens are suppressed during continuation proposal to avoid an all-EOS degenerate output.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"candidate_count": len(candidates), "elapsed_ms": round(elapsed_ms, 2)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
