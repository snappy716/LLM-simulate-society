"""Observe existing day-six ranking without altering choices, state or RNG."""
from collections import Counter
import json
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from simulation.api.server import CampusKernelBridge
from simulation.actions.commands import SimulationCommand
from simulation.systems.campus_decisions import rank_campus_npc_activities
from simulation.systems.campus_life import assessment, session

rows = []


def observe(context, actor_id, *args, **kwargs):
    ranked = rank_campus_npc_activities(context, actor_id, *args, **kwargs)
    state = context.state
    if state.clock.day == 6 and state.clock.phase == "evening":
        event = next((c for c in ranked if c.get("parameters", {}).get("life_session_id") == "life:6:club_exchange_festival"), None)
        rows.append({"actor": actor_id, "eligibility": assessment(state, actor_id, session(state, "life:6:club_exchange_festival"))[0],
            "event_score": event["score"] if event else None,
            "event_rank": ranked.index(event) + 1 if event else None,
            "top": [{"id": r["candidate_id"], "score": r["score"]} for r in ranked[:3]],
            "club_member": bool(state.population[actor_id].get("club_ids")),
            "extraversion": state.population[actor_id]["personality"]["extraversion"]})
    return ranked


with patch("urllib.request.urlopen", side_effect=AssertionError("offline")), patch("simulation.systems.campus_daily_plans.rank_campus_npc_activities", side_effect=observe):
    bridge = CampusKernelBridge(42)
    for index in range(20):
        state = bridge.kernel._state
        result = bridge.kernel.execute(SimulationCommand(f"inspect:{index}", "player", "ADVANCE_PHASE", state.revision,
            issued_day=state.clock.day, issued_phase=state.clock.phase))
        assert result.success, result.code
print(json.dumps({"eligibility": dict(Counter(r["eligibility"] for r in rows)),
    "event_ranks": dict(Counter(r["event_rank"] for r in rows)),
    "closest": sorted([r for r in rows if r["event_rank"]], key=lambda r: (r["event_rank"], r["top"][0]["score"] - r["event_score"]))[:8]}, ensure_ascii=False), flush=True)
