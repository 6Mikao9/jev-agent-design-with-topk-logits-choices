from __future__ import annotations

import argparse
import json
from pathlib import Path


def percentile(values: list[float], p: float) -> float:
    values = sorted(values)
    index = min(len(values) - 1, max(0, int(round((len(values) - 1) * p))))
    return values[index]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = json.loads(args.input.read_text(encoding="utf-8"))
    rows = []
    for case in source["cases"]:
        guided = case["guided"]
        rows.append(
            {
                "id": case["id"],
                "output_tokens": guided.get("output_tokens"),
                "helper_ms": guided.get("helper_latency_ms_total"),
                "chooser_ms": guided.get("chooser_latency_ms_total"),
                "elapsed_ms": guided.get("elapsed_ms"),
                "helper_tokens_per_second": guided.get("helper_tokens_per_second"),
                "end_to_end_tokens_per_second": guided.get("tokens_per_second"),
            }
        )

    def stats(field: str) -> dict:
        values = [float(row[field]) for row in rows if row[field] is not None]
        return {
            "mean": sum(values) / len(values),
            "p50": percentile(values, 0.50),
            "p95": percentile(values, 0.95),
        }

    result = {
        "experiment": "jev-guided-speed-breakdown",
        "chooser": source.get("chooser"),
        "note": "helper_ms is candidate-generation time; chooser_ms is selection time. This run uses local_top1_proxy, not live Jev.",
        "cases": rows,
        "aggregate": {
            "helper_ms": stats("helper_ms"),
            "chooser_ms": stats("chooser_ms"),
            "elapsed_ms": stats("elapsed_ms"),
            "helper_tokens_per_second": stats("helper_tokens_per_second"),
            "end_to_end_tokens_per_second": stats("end_to_end_tokens_per_second"),
        },
    }
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
