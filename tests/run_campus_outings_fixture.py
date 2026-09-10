"""Explicit consenting contacts; real invitation and road travel, no rewards injected."""
import argparse
from http.server import ThreadingHTTPServer

from simulation.api.server import Handler, SimulationBridge
from simulation.systems.campus_messaging import _add_contact
from simulation.systems.campus_social import DEFAULT_RELATIONSHIP
from tests.test_campus_contact_inquiries import as_npc
from tests.test_campus_combat_deployment import travel_to_location


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    bridge = SimulationBridge()
    state = bridge.campus.kernel._state
    target = "campus_student_001"
    for who, other in (("player", target), (target, "player")):
        for day in state.population[who].get("weekly_schedule", {}).values():
            for slot in day.values():
                slot["priority"] = 10
        state.population[who]["needs"].update(rest=20, food=20, safety=20, social=70)
        _add_contact(state, who, other)
        state.relationships.setdefault(who, {})[other] = {**DEFAULT_RELATIONSHIP,
            "familiarity": 50, "closeness": 50, "trust": 70}
    result = as_npc(bridge.campus, target, "INVITE_CAMPUS_OUTING", {"target_id": "player", "day": 1,
        "phase": "afternoon", "location_id": "mirror_lake_square", "kind": "companionship"})
    assert result.success, result.code
    travel_to_location(bridge.campus, "mirror_lake_square")
    Handler.bridge = bridge
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print("OUTINGS_FIXTURE_READY pending_real_invitation real_route no_rewards no_api", flush=True)
        server.serve_forever()
