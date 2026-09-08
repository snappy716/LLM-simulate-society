"""Offline unattended situation soak; no API credentials or model calls."""
import argparse
from collections import Counter
import json
from pathlib import Path

from simulation.api.server import CampusKernelBridge
from simulation.actions.commands import SimulationCommand


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=7, choices=range(1, 29))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    bridge = CampusKernelBridge(args.seed)
    rows, events = [], Counter()
    for index in range(args.days * 4):
        state = bridge.kernel._state
        result = bridge.kernel.execute(SimulationCommand(f"situation-soak:{index}", "player", "ADVANCE_PHASE", state.revision,
            issued_day=state.clock.day, issued_phase=state.clock.phase, issued_minute=state.clock.minute))
        assert result.success, result.code
        events.update(e.event_type for e in result.events)
        state = bridge.kernel._state
        ledger = state.situations.get("campus_dynamics", {})
        row = {"day": state.clock.day, "phase": state.clock.phase,
            "pressure": {k: v["pressure"] for k, v in ledger.get("regions", {}).items()},
            "shortages": dict(Counter(v["status"] for v in ledger.get("shortages", {}).values())),
            "disputes": dict(Counter(v["status"] for v in state.situations.get("campus_disputes", {}).get("cases", {}).values())),
            "welfare": dict(Counter(v["status"] for v in state.situations.get("campus_welfare", {}).get("cases", {}).values())),
            "completed_tasks": sum(t["state"] == "completed" for t in state.tasks.values()),
            "model_calls_today": state.cognition["usage"]["calls"]}
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    sites = bridge.kernel._state.situations.get("night_sites", {}).get("sites", {})
    summary = {"seed": args.seed, "days": args.days, "phases": rows, "events": dict(events),
        "site_outcomes": dict(Counter(s["status"] for s in sites.values())),
        "npc_resolved_sites": sum(s["status"] == "resolved" and s["receipt"]["actor_id"] != "player" for s in sites.values()),
        "player_participation": False, "api_calls": sum(row["model_calls_today"] for row in rows)}
    assert summary["api_calls"] == 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("SITUATION_SOAK_OK", flush=True)


if __name__ == "__main__":
    main()
