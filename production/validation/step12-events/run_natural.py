"""Unattended full-campus events; no plan, relation, score or receipt injection."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from simulation.actions.commands import SimulationCommand
from simulation.api.server import CampusKernelBridge
from simulation.systems.campus_life import ledger, life_invariant


def run(seed, days):
    with patch("urllib.request.urlopen", side_effect=AssertionError("No paid API during event audit")):
        bridge = CampusKernelBridge(seed)
        assert not bridge.cognition_runtime.provider.configured
        for step in range(days * 4):
            state = bridge.kernel._state
            result = bridge.kernel.execute(SimulationCommand(f"events:{seed}:{step}", "player", "ADVANCE_PHASE",
                state.revision, issued_day=state.clock.day, issued_phase=state.clock.phase))
            assert result.success, result.code
            state = bridge.kernel._state
            assert not list(life_invariant(state))
            if (step + 1) % 4 == 0:
                entries = [(sid, actor, r) for sid, actors in ledger(state)["records"].items()
                    for actor, r in actors.items() if ledger(state)["definitions"][sid.split(":")[-1]].get("event")]
                assert all(actor != "player" for _,actor,_ in entries)
                done = [r["result"]["event"] for _,_,r in entries if r["status"] == "completed"]
                assert state.cognition["usage"]["calls"] == 0
                print(json.dumps({"day": (step + 1) // 4, "seed": seed,
                    "participation": dict(Counter(sid.split(":")[-1] + ":" + r["status"] for sid,_,r in entries)),
                    "outcomes": dict(Counter(r.get("outcome", "pending") for r in done)),
                    "resource_spent": sum(r["resource_cost"] for r in done),
                    "club_contribution": sum(r.get("contribution", 0) for r in done),
                    "unique_participants": len({a for _,a,r in entries if r["status"] == "completed"}),
                    "paid_api_calls": 0, "injected_plans_or_outcomes": False}), flush=True)
        assert {r["kind"] for r in done} == {"competition", "festival"}, "Both event types must naturally reach attendance"
        print(f"CAMPUS_EVENTS_NATURAL_OK seed={seed} days={days}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--days", type=int, default=14)
    args = parser.parse_args()
    assert 7 <= args.days <= 28
    run(args.seed, args.days)
