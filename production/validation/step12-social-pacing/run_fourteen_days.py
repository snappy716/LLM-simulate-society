"""Natural social participation distribution, real receipts, no paid API."""
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from simulation.api.server import CampusKernelBridge
from simulation.actions.commands import SimulationCommand
from simulation.systems.campus_outings import records, outings_invariant, participants
from simulation.systems.campus_bonds import records as bonds, bonds_invariant


def run(seed):
    with patch("urllib.request.urlopen", side_effect=AssertionError("No paid API in natural audit")):
        bridge = CampusKernelBridge(seed)
        for step in range(56):
            state = bridge.kernel._state
            result = bridge.kernel.execute(SimulationCommand(f"social-natural:{seed}:{step}", "player", "ADVANCE_PHASE",
                state.revision, issued_day=state.clock.day, issued_phase=state.clock.phase))
            assert result.success, result.code
            state = bridge.kernel._state
            assert not outings_invariant(state) and not bonds_invariant(state)
            assert not bridge.cognition_runtime.provider.configured
            if step % 4 == 3:
                print(json.dumps({"seed": seed, "elapsed_days": (step + 1) // 4,
                    "outings": dict(Counter(r["status"] for r in records(state).values())),
                    "bonds": dict(Counter(r["kind"] + ":" + r["status"] for r in bonds(state).values()))}), flush=True)
        done = [r for r in records(state).values() if r["status"] == "completed"]
        by_actor, per_actor_day, by_pair = Counter(), Counter(), Counter()
        days = defaultdict(list)
        for row in done:
            assert "player" not in participants(row)
            by_pair[tuple(sorted(participants(row)))] += 1
            for who in participants(row):
                by_actor[who] += 1
                per_actor_day[(who, row["day"])] += 1
                days[who].append(row["day"])
        intervals = Counter(b - a for sequence in days.values() for a, b in zip(sorted(set(sequence)), sorted(set(sequence))[1:]))
        for record in bonds(state).values():
            if "player" in (record["proposer_id"], record["recipient_id"]):
                assert record["status"] != "active"
        print(json.dumps({"result": "SOCIAL_FOURTEEN_DAYS_OK", "seed": seed, "completed": len(done),
            "participating_npcs": len(by_actor), "quiet_npcs": 200 - len(by_actor),
            "actor_participation_histogram": dict(Counter(by_actor.values())),
            "max_actor_day": max(per_actor_day.values(), default=0), "unique_pairs": len(by_pair),
            "day_interval_histogram": dict(intervals), "paid_api_calls": 0,
            "no_injected_affinity_or_receipts": True}), flush=True)


if __name__ == "__main__":
    for seed in (42, 314): run(seed)
