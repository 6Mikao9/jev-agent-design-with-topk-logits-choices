"""Mechanism-only scaling baseline for the bounded Virtual Option Manager.

This benchmark measures directory/page-in mechanics, not Jev choice quality,
network latency, or task success.  Every case keeps the resident set bounded
while the logical directory grows by four orders of magnitude.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jev_agent.virtual_option import OptionFault, VirtualOption, VirtualOptionManager


def run_case(logical_options: int, max_resident: int, *, seed: int) -> dict:
    if logical_options < 1 or max_resident < 1:
        raise ValueError("logical_options and max_resident must be positive")
    page_size = min(8, max_resident)
    page_count = math.ceil(logical_options / page_size)
    started = time.perf_counter()
    manager = VirtualOptionManager(max_resident=max_resident, max_pages=page_count)
    for page_number in range(page_count):
        start = page_number * page_size
        end = min(start + page_size, logical_options)
        page_id = f"page-{page_number:06d}"
        manager.register_page(
            page_id,
            tuple(
                VirtualOption(
                    option_id=f"option-{index:07d}",
                    description=f"logical option {index}",
                    payload={"index": index},
                    page_id=page_id,
                )
                for index in range(start, end)
            ),
        )

    rng = random.Random(seed)
    targets = {0, logical_options // 2, logical_options - 1}
    targets.update(rng.randrange(logical_options) for _ in range(min(29, logical_options)))
    page_ins = faults = resolved = stable_id_misses = 0
    peak = 0
    # Touch deterministic pages through the same resolve -> fault -> page-in
    # path that a Jev PAGE/EXPAND control would trigger.
    for index in sorted(targets):
        option_id = f"option-{index:07d}"
        page_number = index // page_size
        page_id = f"page-{page_number:06d}"
        try:
            option = manager.resolve(option_id)
        except OptionFault:
            faults += 1
            page_ins += 1
            manager.page_in(page_id)
            option = manager.resolve(option_id)
        if option.option_id != option_id:
            stable_id_misses += 1
        else:
            resolved += 1
        peak = max(peak, len(manager.resident_options()))
    elapsed_ms = (time.perf_counter() - started) * 1000
    return {
        "logical_options": logical_options,
        "resident_k": max_resident,
        "page_size": page_size,
        "page_count": page_count,
        "probes": len(targets),
        "page_ins": page_ins,
        "option_faults": faults,
        "resolved": resolved,
        "stable_id_misses": stable_id_misses,
        "resident_peak": peak,
        "resident_bound_ok": peak <= max_resident,
        "elapsed_ms": round(elapsed_ms, 3),
        "seed": seed,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", nargs="+", type=int, default=[10, 100, 1000, 10000, 100000])
    parser.add_argument("--resident-k", nargs="+", type=int, default=[8, 16, 32])
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if any(size < 1 for size in args.sizes) or any(k < 1 for k in args.resident_k):
        parser.error("sizes and resident-k must be positive")
    rows = [
        run_case(size, k, seed=args.seed + row * 1009 + k)
        for row, size in enumerate(args.sizes)
        for k in args.resident_k
    ]
    result = {
        "experiment": "virtual-option-space-scaling-mechanism-baseline",
        "cases": rows,
        "notes": [
            "No Jev calls, model inference, network, or task-quality claim is included.",
            "The logical directory is materialized locally to measure page mechanics.",
            "resident_k is a hard bound; page_size never exceeds resident_k.",
        ],
    }
    encoded = json.dumps(result, ensure_ascii=False, indent=2)
    print(encoded)
    if args.output:
        args.output.write_text(encoded + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
