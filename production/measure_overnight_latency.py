"""Offline overnight critical-path probe. Never loads personal API settings.

The synthetic adapter adds a known delay to each call. Results isolate serial
network waiting; they are not a benchmark of a real model or another computer.
"""
import argparse
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from simulation.api.server import CampusKernelBridge
from tests.test_campus_cognition import LastLegalProvider, command


class TimedOfflineProvider(LastLegalProvider):
    def __init__(self, delay):
        super().__init__()
        self.delay = delay
        self.calls = []

    def _measure(self, kind, callback):
        started = time.perf_counter()
        time.sleep(self.delay)
        result = callback()
        self.calls.append({"kind": kind, "seconds": time.perf_counter() - started})
        return result

    def decide(self, request, *, max_output_tokens):
        return self._measure("daily_plan" if request.daily_options is not None else "decision",
            lambda: super(TimedOfflineProvider, self).decide(request, max_output_tokens=max_output_tokens))

    def respond(self, request, *, max_output_tokens):
        return self._measure("dialogue",
            lambda: super(TimedOfflineProvider, self).respond(request, max_output_tokens=max_output_tokens))


def probe(delay, seed=42, concurrency=1):
    with patch("urllib.request.urlopen", side_effect=AssertionError("Offline latency probe must not access the network")):
        bridge = CampusKernelBridge(seed)
        for _ in range(3):
            result = command(bridge, "ADVANCE_PHASE")
            assert result["ok"], result["result"]["code"]
        provider = TimedOfflineProvider(delay)
        provider.max_concurrent_requests = concurrency
        bridge.cognition_runtime.provider = provider
        started = time.perf_counter()
        result = command(bridge, "ADVANCE_PHASE")
        elapsed = time.perf_counter() - started
        assert result["ok"], result["result"]["code"]
        plans = [row for row in provider.calls if row["kind"] == "daily_plan"]
        assert len(plans) == 20, "probe must retain every base LLM NPC"
        simulated_wait = sum(row["seconds"] for row in provider.calls)
        return {"seed": seed, "synthetic_delay_per_call_seconds": delay, "concurrency": concurrency,
            "elapsed_seconds": round(elapsed, 4), "adapter_wait_seconds": round(simulated_wait, 4),
            # Sum of concurrent requests is not critical-path waiting time.
            "daily_planning": bridge.cognition_runtime.last_daily_performance,
            "daily_plan_calls": len(plans), "dialogue_calls": sum(row["kind"] == "dialogue" for row in provider.calls),
            "other_decision_calls": sum(row["kind"] == "decision" for row in provider.calls),
            "paid_api_calls": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delays", type=float, nargs="+", default=[0, .25])
    parser.add_argument("--concurrency", type=int, nargs="+", default=[1, 10])
    args = parser.parse_args()
    if any(not 0 <= delay <= 10 for delay in args.delays):
        parser.error("synthetic delays must be between 0 and 10 seconds")
    if any(not 1 <= count <= 20 for count in args.concurrency):
        parser.error("concurrency must be between 1 and 20")
    for delay in args.delays:
        for count in args.concurrency:
            print(json.dumps(probe(delay, concurrency=count), ensure_ascii=False), flush=True)
