"""Offline phase latency probe: Python backend only, no API or Godot render.

Run the identical script with --repository pointing at each revision. Report
intraday and overnight separately: daily planning intentionally shifts work.
"""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import statistics
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args()
    sys.path.insert(0, str(args.repository.resolve()))
    from simulation.api.server import CampusKernelBridge
    start = time.perf_counter()
    bridge = CampusKernelBridge(42)
    initial = time.perf_counter() - start
    records = []
    for index in range(args.days * 4):
        clock, revision = bridge.kernel.project_view(lambda state: (asdict(state.clock), state.revision))
        start = time.perf_counter()
        result = bridge.execute({"command_id": f"latency:{index}", "actor_id": "player", "action_id": "ADVANCE_PHASE",
            "parameters": {}, "target_ids": [], "expected_world_revision": revision, "issued_day": clock["day"],
            "issued_phase": clock["phase"], "issued_minute": clock["minute"], "source": "player"})
        elapsed = time.perf_counter() - start
        if not result["ok"]:
            raise RuntimeError(result["result"]["code"])
        record = {**result["snapshot"]["clock"], "seconds": round(elapsed, 4)}
        records.append(record)
        print(json.dumps(record), flush=True)
    summary = {"days": args.days, "initial_seconds": round(initial, 4),
               "total_phase_seconds": round(sum(item["seconds"] for item in records), 4)}
    for name, values in (("intraday", [x["seconds"] for x in records if x["phase"] != "morning"]),
                         ("overnight", [x["seconds"] for x in records if x["phase"] == "morning"])):
        summary[name] = {"median_seconds": round(statistics.median(values), 4), "max_seconds": max(values)}
    print("BENCHMARK_SUMMARY " + json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
