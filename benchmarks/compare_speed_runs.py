from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--large", type=Path, required=True)
    parser.add_argument("--small", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    parser.add_argument("--json", type=Path, required=True)
    args = parser.parse_args()
    large = json.loads(args.large.read_text(encoding="utf-8"))
    small = json.loads(args.small.read_text(encoding="utf-8"))
    rows = []
    for a, b in zip(large["cases"], small["cases"]):
        rows.append(
            {
                "id": a["id"],
                "large_helper": "Qwen3.8-27B / top20",
                "small_helper": "Qwen3.5-0.8B / top100",
                "large_helper_ms": a["helper_ms"],
                "small_helper_ms": b["helper_ms"],
                "large_chooser_ms": a["chooser_ms"],
                "small_chooser_ms": b["chooser_ms"],
                "large_end_to_end_ms": a["elapsed_ms"],
                "small_end_to_end_ms": b["elapsed_ms"],
                "large_helper_tps": a["helper_tokens_per_second"],
                "small_helper_tps": b["helper_tokens_per_second"],
            }
        )
    result = {
        "experiment": "helper-speed-comparison",
        "note": "Chooser is the local top-1 proxy in both runs; no live Jev network latency is included.",
        "runs": {
            "large": large["aggregate"],
            "small": small["aggregate"],
        },
        "cases": rows,
    }
    args.json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    md = [
        "# Helper speed comparison",
        "",
        "Both runs use the same four prompts and local top-1 selection proxy. `helper` is candidate-generation time; `chooser` is selection time. Live Jev network latency is not included.",
        "",
        "| case | Qwen3.8-27B top20 helper ms | Qwen3.5-0.8B top100 helper ms | Qwen3.8 chooser ms | Qwen3.5 chooser ms |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        md.append(
            f"| {row['id']} | {row['large_helper_ms']:.2f} | {row['small_helper_ms']:.2f} | {row['large_chooser_ms']:.2f} | {row['small_chooser_ms']:.2f} |"
        )
    md.extend(
        [
            "",
            "| aggregate | Qwen3.8-27B top20 | Qwen3.5-0.8B top100 |",
            "| --- | ---: | ---: |",
            f"| mean helper ms | {large['aggregate']['helper_ms']['mean']:.2f} | {small['aggregate']['helper_ms']['mean']:.2f} |",
            f"| mean chooser ms | {large['aggregate']['chooser_ms']['mean']:.2f} | {small['aggregate']['chooser_ms']['mean']:.2f} |",
            f"| mean helper tokens/s | {large['aggregate']['helper_tokens_per_second']['mean']:.2f} | {small['aggregate']['helper_tokens_per_second']['mean']:.2f} |",
            f"| mean end-to-end tokens/s | {large['aggregate']['end_to_end_tokens_per_second']['mean']:.2f} | {small['aggregate']['end_to_end_tokens_per_second']['mean']:.2f} |",
            "",
        ]
    )
    args.markdown.write_text("\n".join(md), encoding="utf-8")
    print("wrote", args.markdown, args.json)


if __name__ == "__main__":
    main()
