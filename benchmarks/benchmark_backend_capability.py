"""Synthetic backend-capability and page-recovery baseline.

The benchmark isolates runtime mechanics: a target option is sampled from a
large logical directory, while the decision backend has a controlled chance of
selecting the target once it is resident.  It does not model Jev calibration,
network latency, or task semantics.
"""
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

from jev_agent.virtual_option import OptionFault, VirtualOption, VirtualOptionManager


def _manager(logical_options: int, resident_k: int) -> tuple[VirtualOptionManager, int]:
    page_size = min(8, resident_k)
    page_count = (logical_options + page_size - 1) // page_size
    manager = VirtualOptionManager(max_resident=resident_k, max_pages=page_count)
    for page_number in range(page_count):
        page_id = f"page-{page_number:06d}"
        start = page_number * page_size
        end = min(start + page_size, logical_options)
        manager.register_page(
            page_id,
            tuple(
                VirtualOption(
                    f"option-{index:07d}", f"option {index}", {"index": index}, page_id
                )
                for index in range(start, end)
            ),
        )
    return manager, page_size


def run_case(
    logical_options: int,
    resident_k: int,
    capability: float,
    strategy: str,
    *,
    trials: int,
    seed: int,
) -> dict:
    if not 0 < capability <= 1:
        raise ValueError("capability must be in (0, 1]")
    manager, page_size = _manager(logical_options, resident_k)
    rng = random.Random(seed)
    successes = faults = page_ins = 0
    initial_page_ins = recovery_page_ins = visible_trials = recovered = 0
    started = time.perf_counter()
    for _ in range(trials):
        resident = manager.resident_options()
        if resident:
            manager.evict_lru(len(resident))
        manager.page_in("page-000000")
        page_ins += 1
        initial_page_ins += 1
        target_index = rng.randrange(logical_options)
        target_id = f"option-{target_index:07d}"
        target_page = f"page-{target_index // page_size:06d}"
        try:
            manager.resolve(target_id)
            target_resident = True
        except OptionFault:
            target_resident = False
            faults += 1
        if not target_resident and strategy == "page_expand":
            manager.page_in(target_page)
            page_ins += 1
            recovery_page_ins += 1
            recovered += 1
        visible = {option.option_id for option in manager.resident_options()}
        if target_id not in visible:
            continue
        visible_trials += 1
        chosen = target_id if rng.random() < capability else next(
            option_id for option_id in sorted(visible) if option_id != target_id
        ) if len(visible) > 1 else None
        successes += chosen == target_id
    elapsed_ms = (time.perf_counter() - started) * 1000
    return {
        "logical_options": logical_options,
        "resident_k": resident_k,
        "backend_capability": capability,
        "strategy": strategy,
        "trials": trials,
        "successes": successes,
        "success_rate": successes / trials,
        "coverage_rate": visible_trials / trials,
        "resident_decision_success_rate": (
            successes / visible_trials if visible_trials else None
        ),
        "option_faults": faults,
        "page_ins": page_ins,
        "initial_page_ins": initial_page_ins,
        "recovery_page_ins": recovery_page_ins,
        "recovery_rate": recovered / faults if faults else None,
        "elapsed_ms": round(elapsed_ms, 3),
        "seed": seed,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", nargs="+", type=int, default=[10, 100, 1000, 10000, 100000])
    parser.add_argument("--resident-k", nargs="+", type=int, default=[8, 16, 32])
    parser.add_argument("--capabilities", nargs="+", type=float, default=[0.6, 0.7, 0.8, 0.9, 1.0])
    parser.add_argument("--trials", type=int, default=50)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if any(size < 1 for size in args.sizes) or any(k < 1 for k in args.resident_k) or args.trials < 1:
        parser.error("sizes, resident-k and trials must be positive")
    rows = []
    case_number = 0
    for size in args.sizes:
        for resident_k in args.resident_k:
            # Large directories are deliberately sampled with fewer trials so
            # this CPU baseline remains quick and reproducible.
            case_trials = min(args.trials, max(5, 5000 // size))
            for capability in args.capabilities:
                for strategy in ("fixed_resident", "page_expand"):
                    rows.append(run_case(
                        size, resident_k, capability, strategy,
                        trials=case_trials, seed=args.seed + case_number,
                    ))
                    case_number += 1
    result = {
        "experiment": "decision-model-capability-and-option-page-recovery",
        "cases": rows,
        "notes": [
            "Synthetic backend only; no Jev calls or model-quality claim.",
            "fixed_resident never pages in a missing target; page_expand simulates PAGE/EXPAND recovery.",
            "Use RecoveryRate on trials where the target was initially absent for the full evaluation.",
        ],
    }
    encoded = json.dumps(result, ensure_ascii=False, indent=2)
    print(encoded)
    if args.output:
        args.output.write_text(encoded + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
