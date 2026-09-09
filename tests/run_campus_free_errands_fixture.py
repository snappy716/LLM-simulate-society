"""Explicit cached-choice and disclosure fixture, with real production execution."""
import argparse
from copy import deepcopy
from http.server import ThreadingHTTPServer

from simulation.api.server import Handler, SimulationBridge
from simulation.systems.campus_trade import procurement_candidates
from simulation.systems.chronicles import grant_chronicle_knowledge
from tests.test_campus_cognition import command


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    bridge = SimulationBridge()
    campus = bridge.campus
    assert command(campus, "ADVANCE_PHASE")["ok"]
    state = campus.kernel._state
    who = "campus_student_001"
    actor = state.population[who]
    actor["wealth"], actor["needs"]["food"] = 500, 80
    state.inventories["actors"][who]["quantities"].pop("bread_loaf", None)
    preview = state.clone()
    preview.clock.phase = "evening"
    errand = next(c for c in procurement_candidates(preview, who, campus.location_graph)
        if c["parameters"]["item_id"] == "bread_loaf")
    slot = state.cognition["daily_plans"]["actors"][who]["evening"]
    slot.update(planned_source="llm", free_errands=[deepcopy(errand)])
    intended = (slot["activity_id"], slot["location_id"])
    result = command(campus, "ADVANCE_PHASE")
    assert result["ok"], result
    events = [e for e in result["result"]["events"] if who in e["actor_ids"]]
    kinds = [e["event_type"] for e in events]
    assert kinds.index("NPC_FREE_ERRAND_COMPLETED") < kinds.index("NPC_ACTIVITY_COMPLETED")
    moves = [e["payload"] for e in events if e["event_type"] == "ACTOR_LOCATION_CHANGED"]
    for first, second in zip(moves, moves[1:]):
        assert first["to_id"] == second["from_id"]
    state = campus.kernel._state
    actor = state.population[who]
    assert intended == (actor["current_activity"]["activity_id"], actor["current_activity"]["location_id"])
    assert actor["wealth"] < 500
    assert state.action_economy["actors"][who]["major_remaining"] == 0
    for key in state.chronicles["by_actor"][who]:
        entry = state.chronicles["entries"][key]
        if entry["phase"] == "evening" and entry["event_type"] in ("NPC_FREE_ERRAND_COMPLETED", "NPC_ACTIVITY_COMPLETED"):
            grant_chronicle_knowledge(state, "player", key, source="told", certainty="reported")
    # UI-only co-location/disclosure; neither is evidence of natural encounters.
    actor["display_name"] += "（采购续行验收）"
    for actor_id in ("player", who):
        state.population[actor_id]["current_location_id"] = "south_gate_region"
    Handler.bridge = bridge
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print("FREE_ERRANDS_FIXTURE_READY real_purchase_primary_routes explicit_choice_disclosure_colocation", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
