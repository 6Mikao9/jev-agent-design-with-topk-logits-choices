"""Run a small, reproducible matrix for the lexical memory needle baseline."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.benchmark_needle_memory import run


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages", nargs="+", type=int, default=[100, 1000, 10000])
    parser.add_argument("--noise-words", nargs="+", type=int, default=[40, 160])
    parser.add_argument("--positions", nargs="+", default=["first", "middle", "last"])
    parser.add_argument("--limit", type=int, default=16)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    rows = []
    for pages in args.pages:
        for noise_words in args.noise_words:
            for position in args.positions:
                class Case:
                    pass
                case = Case()
                case.pages = pages
                case.noise_words = noise_words
                case.needle_position = position
                case.limit = args.limit
                case.seed = args.seed
                case.output = None
                # ``run`` prints a row for interactive use; the matrix keeps only
                # the returned data and emits one compact JSON document below.
                # Reimplementing the baseline would risk metric drift.
                import contextlib
                import io
                with contextlib.redirect_stdout(io.StringIO()):
                    result = run(case)
                rows.append(result)
    summary = {
        "experiment": "lexical-needle-memory-matrix",
        "cases": rows,
        "notes": [
            "Lexical coarse prefilter only; no Jev call, embedding, RAG, or two-stage selection.",
            "Recall is exact hit of the injected needle page in the returned candidate set.",
        ],
    }
    encoded = json.dumps(summary, ensure_ascii=False, indent=2)
    print(encoded)
    if args.output:
        args.output.write_text(encoded + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
