from __future__ import annotations

import argparse
import json
import random
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

from jev_agent.topk import TokenProposal, TransformersLogitsBackend


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "benchmarks" / "data" / "bfcl-v4-exec-simple"
DEFAULT_OUTPUT = (
    ROOT
    / "benchmarks"
    / "results"
    / "bfcl-v4-exec-simple-qwen3-0.6b-topk-30.json"
)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def pair_examples(
    questions: list[dict[str, Any]], answers: list[dict[str, Any]]
) -> list[tuple[dict[str, Any], str]]:
    answer_by_id = {item["id"]: item for item in answers}
    pairs: list[tuple[dict[str, Any], str]] = []
    for question in questions:
        answer = answer_by_id.get(question["id"])
        if answer is None or not answer.get("ground_truth"):
            continue
        if len(question.get("function", [])) != 1:
            continue
        pairs.append((question, str(answer["ground_truth"][0])))
    return sorted(pairs, key=lambda item: item[0]["id"])


def choose_sample(
    pairs: list[tuple[dict[str, Any], str]], *, limit: int, seed: int
) -> list[tuple[dict[str, Any], str]]:
    if limit < 1:
        raise ValueError("limit must be at least 1")
    rng = random.Random(seed)
    return sorted(rng.sample(pairs, min(limit, len(pairs))), key=lambda item: item[0]["id"])


def user_request(question: dict[str, Any]) -> str:
    requests: list[str] = []
    for turn in question.get("question", []):
        messages = turn if isinstance(turn, list) else [turn]
        for message in messages:
            if isinstance(message, dict) and message.get("role") == "user":
                content = message.get("content", "")
                if isinstance(content, str):
                    requests.append(content)
    return "\n".join(requests)


def make_prompt(question: dict[str, Any]) -> str:
    functions = json.dumps(question["function"], ensure_ascii=False, sort_keys=True)
    request = user_request(question)
    return (
        "<|im_start|>user\n"
        "Generate exactly one executable Python function call for the request. "
        "Use only the provided function and arguments; return no explanation.\n"
        f"Available function schema: {functions}\n"
        f"Request: {request}"
        "<|im_end|><|im_start|>assistant\nOutput:<|im_sep|>"
    )


def target_ids(tokenizer: Any, prompt: str, target: str) -> list[int]:
    prompt_ids = tokenizer(prompt, return_tensors="pt").input_ids[0].tolist()
    full_ids = tokenizer(prompt + target, return_tensors="pt").input_ids[0].tolist()
    if full_ids[: len(prompt_ids)] != prompt_ids:
        raise ValueError("tokenizer merged the prompt boundary with the reference call")
    ids = full_ids[len(prompt_ids) :]
    decoded = tokenizer.decode(
        ids, skip_special_tokens=False, clean_up_tokenization_spaces=False
    )
    if decoded != target:
        raise ValueError("reference call does not round-trip through the tokenizer")
    return ids


def coverage_summary(
    records: list[dict[str, Any]], k_values: list[int]
) -> dict[str, Any]:
    token_count = sum(len(record["ranks"]) for record in records)
    metrics: dict[str, Any] = {"tasks": len(records), "reference_tokens": token_count}
    for k in k_values:
        token_hits = sum(
            rank is not None and rank <= k
            for record in records
            for rank in record["ranks"]
        )
        exact_calls = sum(
            bool(record["ranks"])
            and all(rank is not None and rank <= k for rank in record["ranks"])
            for record in records
        )
        metrics[f"token_hit_at_{k}"] = token_hits / token_count if token_count else 0.0
        metrics[f"oracle_exact_call_at_{k}"] = (
            exact_calls / len(records) if records else 0.0
        )
        metrics[f"oracle_exact_calls_at_{k}"] = exact_calls
    return metrics


def evaluate(
    pairs: list[tuple[dict[str, Any], str]],
    *,
    backend: TransformersLogitsBackend,
    k_values: list[int],
) -> tuple[list[dict[str, Any]], float]:
    records: list[dict[str, Any]] = []
    started = perf_counter()
    max_k = max(k_values)
    for question, reference_call in pairs:
        prompt = make_prompt(question)
        expected_ids = target_ids(backend.tokenizer, prompt, reference_call)
        state = backend.start(context=prompt, prefix="")
        ranks: list[int | None] = []
        for expected_id in expected_ids:
            proposals = backend.next_top_k(state=state, k=max_k)
            rank = next(
                (
                    index
                    for index, proposal in enumerate(proposals, start=1)
                    if proposal.token_id == expected_id
                ),
                None,
            )
            ranks.append(rank)
            state = backend.append_token(
                state=state,
                token=TokenProposal(
                    token_id=expected_id,
                    text=backend.tokenizer.convert_ids_to_tokens(expected_id),
                    logit=0.0,
                    is_eos=expected_id == backend.tokenizer.eos_token_id,
                ),
            )
        records.append(
            {
                "id": question["id"],
                "function": question["function"][0]["name"],
                "reference_tokens": len(expected_ids),
                "ranks": ranks,
            }
        )
    return records, perf_counter() - started


def run(args: argparse.Namespace) -> dict[str, Any]:
    questions = read_jsonl(args.questions)
    answers = read_jsonl(args.answers)
    pairs = choose_sample(
        pair_examples(questions, answers), limit=args.limit, seed=args.seed
    )
    if not pairs:
        raise ValueError("no single-function question/reference pairs were found")
    backend = TransformersLogitsBackend(
        args.model, device=args.device, dtype=args.dtype
    )
    records, elapsed = evaluate(pairs, backend=backend, k_values=args.k_values)
    source = (DATA_DIR / "SOURCE.md").read_text(encoding="utf-8")
    commit = next(
        (line.removeprefix("Snapshot commit: ") for line in source.splitlines() if line.startswith("Snapshot commit: ")),
        "unknown",
    )
    return {
        "date": datetime.now(timezone.utc).isoformat(),
        "benchmark": "BFCL V4 exec_simple reference-token coverage",
        "dataset_commit": commit,
        "dataset_total_pairs": len(pair_examples(questions, answers)),
        "sample_seed": args.seed,
        "sample_ids": [question["id"] for question, _ in pairs],
        "model": args.model,
        "device": args.device,
        "dtype": args.dtype or "model default",
        "max_k": max(args.k_values),
        "metrics": coverage_summary(records, args.k_values),
        "elapsed_seconds": round(elapsed, 3),
        "cases": records,
        "interpretation": (
            "Teacher-forced helper-logit coverage with an oracle that knows the "
            "reference token sequence. This is an upper bound on token availability, "
            "not a Jev-choice, end-to-end agent, or BFCL leaderboard score."
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, help="local causal LM directory or id")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--dtype", choices=("float32", "float16", "bfloat16"))
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--k-values", type=int, nargs="+", default=[1, 8, 32])
    parser.add_argument("--questions", type=Path, default=DATA_DIR / "questions.jsonl")
    parser.add_argument("--answers", type=Path, default=DATA_DIR / "answers.jsonl")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if any(k < 1 for k in args.k_values):
        parser.error("all k-values must be positive")
    return args


def main() -> None:
    args = parse_args()
    result = run(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result["metrics"], indent=2))
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
