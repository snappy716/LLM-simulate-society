"""Natural relationship horizon; no player participation or paid model calls."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from simulation.actions.commands import SimulationCommand
from simulation.api.server import CampusKernelBridge
from simulation.systems.campus_bonds import records as bonds, bonds_invariant, willing
from simulation.systems.campus_outings import records as outings, outings_invariant, participants
from simulation.systems.campus_social import DEFAULT_RELATIONSHIP


def report(state, seed, elapsed):
    done = [r for r in outings(state).values() if r["status"] == "completed"]
    pairs = Counter(tuple(sorted(participants(r))) for r in done)
    readiness, missing, levels = Counter(), Counter(), []
    for first, second in sorted(pairs):
        for who, other in ((first, second), (second, first)):
            r = {**DEFAULT_RELATIONSHIP, **state.relationships.get(who, {}).get(other, {})}
            caution = (state.population[who].get("personality", {}).get("emotional_sensitivity", 50) - 50) / 10
            readiness.update(kind for kind in ("friendship", "romance") if willing(state, who, other, kind))
            missing.update(name for name, unmet in (
                ("familiarity", r["familiarity"] < 20), ("closeness", r["closeness"] < 25),
                ("trust", r["trust"] < 55 + caution)) if unmet)
            levels.append({"completed_together": pairs[tuple(sorted((who, other)))],
                "familiarity": r["familiarity"], "closeness": r["closeness"], "trust": r["trust"]})
    assert all("player" not in participants(r) for r in done)
    assert not any(r["status"] == "active" and "player" in (r["proposer_id"], r["recipient_id"]) for r in bonds(state).values())
    print(json.dumps({"result": "RELATIONSHIP_HORIZON", "seed": seed, "elapsed_days": elapsed,
        "outings": dict(Counter(r["kind"] + ":" + r["status"] for r in outings(state).values())),
        "bonds": dict(Counter(r["kind"] + ":" + r["status"] for r in bonds(state).values())),
        "unique_pairs": len(pairs), "directed_ready": dict(readiness), "friendship_missing_thresholds": dict(missing),
        "strongest_completed_pairs": sorted(levels, key=lambda r: r["closeness"], reverse=True)[:8],
        "paid_api_calls": 0, "injected_relationships_or_receipts": False}), flush=True)


def run(seed, days):
    with patch("urllib.request.urlopen", side_effect=AssertionError("No paid API in horizon audit")):
        bridge = CampusKernelBridge(seed)
        assert not bridge.cognition_runtime.provider.configured
        for step in range(days * 4):
            state = bridge.kernel._state
            result = bridge.kernel.execute(SimulationCommand(f"horizon:{seed}:{step}", "player", "ADVANCE_PHASE",
                state.revision, issued_day=state.clock.day, issued_phase=state.clock.phase))
            assert result.success, result.code
            state = bridge.kernel._state
            assert not outings_invariant(state) and not bonds_invariant(state)
            if (step + 1) % 28 == 0 or step == days * 4 - 1:
                report(state, seed, (step + 1) // 4)
        print(f"RELATIONSHIP_HORIZON_OK seed={seed} days={days} no_api", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--days", type=int, default=28)
    args = parser.parse_args()
    assert 1 <= args.days <= 56
    run(args.seed, args.days)
