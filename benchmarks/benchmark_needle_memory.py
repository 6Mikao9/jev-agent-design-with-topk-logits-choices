"""Deterministic lexical needle-in-a-haystack baseline for PagedMemoryIndex."""
from __future__ import annotations
import argparse, json, random, sys, time
from pathlib import Path

# Keep direct ``python benchmarks/benchmark_needle_memory.py`` execution
# equivalent to ``python -m`` when launched from any working directory.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jev_agent.paged_memory import MemoryPage, PagedMemoryIndex


def run(args):
    rng = random.Random(args.seed)
    needle = "needle_fact_7391"
    position = args.needle_position
    if position == "first": idx = 0
    elif position == "last": idx = args.pages - 1
    elif position == "middle": idx = args.pages // 2
    else: idx = max(0, min(args.pages - 1, int(position)))
    vocab = [f"noise_{i:04d}" for i in range(max(8, args.noise_words))]
    index = PagedMemoryIndex(max_pages=args.pages)
    for i in range(args.pages):
        words = [rng.choice(vocab) for _ in range(args.noise_words)]
        if i == idx:
            words.insert(len(words)//2, needle)
            summary = f"page {i:04d} contains {needle}"
        else:
            summary = f"page {i:04d} noise summary"
        index.upsert(MemoryPage(page_id=f"mem_{i:04d}", summary=summary, content=" ".join(words)))
    started = time.perf_counter()
    candidates = index.select_pages(needle, limit=args.limit)
    elapsed_ms = (time.perf_counter() - started) * 1000
    ids = [c.page_id for c in candidates]
    needle_id = f"mem_{idx:04d}"
    hit = needle_id in ids
    result = {"pages": args.pages, "needle_position": position, "needle_page": needle_id,
              "noise_words": args.noise_words, "seed": args.seed, "limit": args.limit,
              "candidate_count": len(candidates), "needle_hit": hit,
              "recall_at_M": 1.0 if hit else 0.0, "elapsed_ms": round(elapsed_ms, 6),
              "baseline": "lexical coarse prefilter; not two-stage Jev"}
    if args.output:
        Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--pages", type=int, default=100)
    p.add_argument("--needle-position", default="middle", help="first, middle, last, or zero-based page index")
    p.add_argument("--noise-words", type=int, default=40)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--limit", type=int, default=16)
    p.add_argument("--output")
    args = p.parse_args()
    if args.pages < 1 or args.noise_words < 1 or args.limit < 1:
        p.error("pages, noise-words, and limit must be positive")
    run(args)

if __name__ == "__main__": main()
