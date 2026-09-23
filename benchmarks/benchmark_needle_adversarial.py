"""Stress lexical page filtering with missing summaries and near-duplicate pages."""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jev_agent.paged_memory import MemoryPage, PagedMemoryIndex


def run_case(*, mode: str, pages: int, limit: int, decoys: int, seed: int) -> dict:
    rng = random.Random(seed)
    query = "departure schedule"
    target_id = f"mem-{pages - 1:05d}"
    index = PagedMemoryIndex(max_pages=pages)
    for i in range(pages):
        page_id = f"mem-{i:05d}"
        noise = f"noise_{rng.randrange(100000)}"
        if i == pages - 1:
            if mode == "content_only":
                summary = f"page {i:05d} unrelated note"
                content = f"{noise} departure schedule: Friday 08:00"
            elif mode == "paraphrase":
                summary = f"page {i:05d} travel timing"
                content = f"{noise} leave plan for Friday morning"
            else:
                summary = f"page {i:05d} contains {query}"
                content = f"{noise} {query}: Friday 08:00"
        elif mode == "dense_decoys" and i < decoys:
            summary = f"decoy {i:05d} contains {query}"
            content = f"{noise} decoy"
        else:
            summary = f"page {i:05d} unrelated note"
            content = noise
        index.upsert(MemoryPage(page_id=page_id, summary=summary, content=content))
    started = time.perf_counter()
    candidates = index.select_pages(query, limit=limit)
    elapsed_ms = (time.perf_counter() - started) * 1000
    candidate_ids = [item.page_id for item in candidates]
    return {
        "mode": mode,
        "pages": pages,
        "limit": limit,
        "decoys": decoys,
        "target_page": target_id,
        "candidate_count": len(candidate_ids),
        "target_hit": target_id in candidate_ids,
        "target_rank": candidate_ids.index(target_id) + 1 if target_id in candidate_ids else None,
        "elapsed_ms": round(elapsed_ms, 6),
        "baseline": "lexical coarse prefilter; adversarial control; not two-stage Jev",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages", type=int, default=100)
    parser.add_argument("--limit", type=int, default=16)
    parser.add_argument("--decoys", type=int, default=32)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.pages < 2 or args.limit < 1 or args.decoys < 0:
        parser.error("pages must be at least 2; limit and decoys must be non-negative/positive")
    rows = [
        run_case(mode="exact", pages=args.pages, limit=args.limit, decoys=args.decoys, seed=args.seed),
        run_case(mode="content_only", pages=args.pages, limit=args.limit, decoys=args.decoys, seed=args.seed),
        run_case(mode="paraphrase", pages=args.pages, limit=args.limit, decoys=args.decoys, seed=args.seed),
        run_case(mode="dense_decoys", pages=args.pages, limit=args.limit, decoys=args.decoys, seed=args.seed),
    ]
    result = {
        "experiment": "lexical-needle-adversarial-controls",
        "cases": rows,
        "notes": [
            "The target is always the last page; this intentionally tests summary coverage and tie pressure.",
            "A miss is a lexical-prefilter limitation, not a Jev decision failure.",
        ],
    }
    encoded = json.dumps(result, ensure_ascii=False, indent=2)
    print(encoded)
    if args.output:
        args.output.write_text(encoded + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
