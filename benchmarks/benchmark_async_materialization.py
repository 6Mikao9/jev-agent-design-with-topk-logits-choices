"""Measure actual asynchronous shadow-page materialization and promotion guards."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jev_agent.speculation import SpeculationBuffer
from jev_agent.virtual_option import VirtualOption, VirtualOptionManager


def _manager():
    manager = VirtualOptionManager(max_resident=2)
    for name in ("files", "memory", "tools"):
        manager.register_page(name, [VirtualOption(f"{name}:0", name, page_id=name)])
    return manager


def _cost(_page):
    time.sleep(0.035)
    return 35.0


def run_suite() -> dict:
    manager = _manager()
    sequential = SpeculationBuffer(max_pages=2)
    started = time.perf_counter()
    sequential.prefetch(manager, ["files", "memory"], base_revision=1, prepare_cost_ms=_cost)
    sequential_ms = (time.perf_counter() - started) * 1000

    async_buffer = SpeculationBuffer(max_pages=2)
    started = time.perf_counter()
    futures = async_buffer.prefetch_async(manager, ["files", "memory"], base_revision=1,
                                          prepare_cost_ms=_cost)
    scheduled_ms = (time.perf_counter() - started) * 1000
    time.sleep(0.020)
    async_buffer.await_materialization(timeout_seconds=2)
    async_ms = (time.perf_counter() - started) * 1000
    promoted = async_buffer.promote(manager, "files", current_revision=1)

    stale = SpeculationBuffer(max_pages=1)
    stale.prefetch_async(manager, ["tools"], base_revision=2, prepare_cost_ms=_cost)
    stale.await_materialization(timeout_seconds=2)
    manager.register_page("tools", [VirtualOption("tools:new", "new", page_id="tools")], revision=2)
    stale_status = "rejected"
    try:
        stale.promote(manager, "tools", current_revision=2)
    except Exception as error:
        stale_status = type(error).__name__
    return {"experiment": "async-page-materialization", "sequential_ms": round(sequential_ms, 3),
            "scheduled_ms": round(scheduled_ms, 3), "async_total_ms": round(async_ms, 3),
            "pending_futures": len(futures), "promoted": [option.option_id for option in promoted],
            "stale_status": stale_status,
            "limitations": ["Preparation sleeps are a local materialization proxy, not network or Jev latency.",
                            "No GPU, shared IO contention or speculative quality model."]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run_suite()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
