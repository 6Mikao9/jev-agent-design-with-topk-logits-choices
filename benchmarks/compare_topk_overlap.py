from __future__ import annotations

import argparse
import json
from pathlib import Path


KS = (10, 20, 50, 100, 250)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _token_key(row: dict) -> str:
    # The escaped token piece is useful for inspection when tokenizers differ.
    return str(row.get("token", row.get("decoded", "")))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--small", type=Path, required=True)
    parser.add_argument("--large", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    small = _load(args.small)
    large = _load(args.large)
    if set(x["id"] for x in small["contexts"]) != set(x["id"] for x in large["contexts"]):
        raise SystemExit("context IDs do not match")
    small_by_id = {x["id"]: x for x in small["contexts"]}
    large_by_id = {x["id"]: x for x in large["contexts"]}
    vocab_same = (
        small.get("vocab_size") == large.get("vocab_size")
        and small.get("vocab_hash")
        and small.get("vocab_hash") == large.get("vocab_hash")
    )

    rows: list[dict] = []
    for context_id in small_by_id:
        a = small_by_id[context_id]
        b = large_by_id[context_id]
        a_top = a["topk"]
        b_top = b["topk"]
        metrics: dict[str, dict] = {}
        for k in KS:
            a_ids = {int(x["token_id"]) for x in a_top[:k]}
            b_ids = {int(x["token_id"]) for x in b_top[:k]}
            a_pieces = {_token_key(x) for x in a_top[:k]}
            b_pieces = {_token_key(x) for x in b_top[:k]}
            inter = sorted(a_ids & b_ids)
            union = a_ids | b_ids
            piece_inter = sorted(a_pieces & b_pieces)
            piece_union = a_pieces | b_pieces
            large_top1_piece = _token_key(b_top[0])
            large_top10 = {_token_key(x) for x in b_top[:10]}
            large_top20 = {_token_key(x) for x in b_top[:20]}
            large_top50 = {_token_key(x) for x in b_top[:50]}
            metrics[str(k)] = {
                "small_count": len(a_ids),
                "large_count": len(b_ids),
                "id_overlap_count": len(inter) if vocab_same else None,
                "id_overlap_rate_small": len(inter) / len(a_ids) if vocab_same else None,
                "id_overlap_rate_large": len(inter) / len(b_ids) if vocab_same else None,
                "id_jaccard": len(inter) / len(union) if vocab_same else None,
                "piece_overlap_count": len(piece_inter),
                "piece_overlap_rate_small": len(piece_inter) / len(a_pieces),
                "piece_overlap_rate_large": len(piece_inter) / len(b_pieces),
                "piece_jaccard": len(piece_inter) / len(piece_union),
                "large_top1_in_small_topk": large_top1_piece in a_pieces,
                "large_top1_miss_in_small_topk": large_top1_piece not in a_pieces,
                "large_top10_coverage_in_small_topk": len(large_top10 & a_pieces) / len(large_top10),
                "large_top20_coverage_in_small_topk": len(large_top20 & a_pieces) / len(large_top20),
                "large_top50_coverage_in_small_topk": len(large_top50 & a_pieces) / len(large_top50),
                "overlap_token_ids": inter,
                "overlap_token_pieces": piece_inter[:50],
            }
        rows.append(
            {
                "id": context_id,
                "context": a["text"],
                "metrics": metrics,
                "small_top10": a_top[:10],
                "large_top10": b_top[:10],
            }
        )

    aggregate: dict[str, dict] = {}
    for k in KS:
        values = [row["metrics"][str(k)] for row in rows]
        aggregate[str(k)] = {
            "contexts": len(values),
            "mean_id_overlap_count": sum(x["id_overlap_count"] for x in values) / len(values) if vocab_same else None,
            "mean_id_overlap_rate_small": sum(x["id_overlap_rate_small"] for x in values) / len(values) if vocab_same else None,
            "mean_id_overlap_rate_large": sum(x["id_overlap_rate_large"] for x in values) / len(values) if vocab_same else None,
            "mean_id_jaccard": sum(x["id_jaccard"] for x in values) / len(values) if vocab_same else None,
            "large_top1_hit_rate_in_small_topk": sum(x["large_top1_in_small_topk"] for x in values) / len(values),
            "large_top1_miss_rate_in_small_topk": sum(x["large_top1_miss_in_small_topk"] for x in values) / len(values),
            "mean_large_top10_coverage_in_small_topk": sum(x["large_top10_coverage_in_small_topk"] for x in values) / len(values),
            "mean_large_top20_coverage_in_small_topk": sum(x["large_top20_coverage_in_small_topk"] for x in values) / len(values),
            "mean_large_top50_coverage_in_small_topk": sum(x["large_top50_coverage_in_small_topk"] for x in values) / len(values),
            "mean_piece_overlap_count": sum(x["piece_overlap_count"] for x in values) / len(values),
            "mean_piece_jaccard": sum(x["piece_jaccard"] for x in values) / len(values),
        }

    result = {
        "experiment": "same-context-next-token-topk-overlap",
        "models": {"small": small["model"], "large": large["model"]},
        "k_values": list(KS),
        "vocab_size": {"small": small.get("vocab_size"), "large": large.get("vocab_size")},
        "vocab_hash_equal": bool(vocab_same),
        "comparison_note": (
            "Token IDs are directly comparable because both tokenizers have the same vocabulary hash. "
            "Piece overlap is included as a readable cross-tokenizer diagnostic."
        ),
        "aggregate": aggregate,
        "contexts": rows,
    }
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "aggregate": aggregate}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
