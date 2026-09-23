"""Longer live Jev A/B/C serial workload built from the 22-step path.

The short path is repeated without the terminal stale-stop event so resident
and context replacement are exercised across cycles. A single stale-stop is
kept at the end to preserve the safety terminal case. Effects remain simulated.
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
BENCHMARKS = ROOT / "benchmarks"
if str(BENCHMARKS) not in sys.path:
    sys.path.insert(0, str(BENCHMARKS))

from benchmark_jev_decision_dense_serial import (  # noqa: E402
    ContractChooser,
    EVENTS,
    Event,
    TypeSafeJevChooser,
    run,
)


def build_events(cycles: int) -> tuple[Event, ...]:
    if cycles < 1:
        raise ValueError("cycles must be positive")
    stale = next(event for event in EVENTS if event.kind == "stale_stop")
    repeatable = tuple(event for event in EVENTS if event.kind != "stale_stop")
    events: list[Event] = []
    for cycle in range(1, cycles + 1):
        events.extend(replace(event, name=f"cycle{cycle}_{event.name}") for event in repeatable)
    events.append(replace(stale, name=f"cycle{cycles}_stale_stop"))
    return tuple(events)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cycles", type=int, default=2)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    events = build_events(args.cycles)
    if args.live:
        if not (os.environ.get("TYPESAFE_API_KEY") or os.environ.get("JEV_API_KEY")):
            raise SystemExit("Set TYPESAFE_API_KEY or JEV_API_KEY in the process environment")
        chooser = TypeSafeJevChooser(timeout_seconds=30.0)
    else:
        chooser = ContractChooser()
    result = run(chooser, events=events, experiment=f"jev-decision-dense-serial-{len(events)}-step")
    result["cycles"] = args.cycles
    args.output.parent.mkdir(parents=True, exist_ok=True)
    import json
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
