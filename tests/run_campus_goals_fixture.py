"""Real one-day NPC cases/plans; explicit location/name fixture for inspector QA."""
import argparse
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from simulation.api.server import Handler, SimulationBridge, CampusKernelBridge
from simulation.systems.campus_goals import advance_personal_goals
from tests.test_campus_combat_deployment import execute


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    bridge = SimulationBridge()
    bridge.campus = CampusKernelBridge(46)
    for index in range(4):
        result = execute(bridge.campus, "ADVANCE_PHASE", {}, marker=f"goals-fixture-{index}")
        assert result["ok"], result
    state = bridge.campus.kernel._state
    advance_personal_goals(SimpleNamespace(state=state, emit=lambda *args, **kwargs: None))
    target = sorted(state.cognition["long_term_plans"]["actors"])[0]
    state.population[target]["display_name"] += "（研习验收）"
    state.population[target]["personality"]["risk_tolerance"] = 60
    for actor_id in ("player", target):
        state.population[actor_id]["current_location_id"] = "south_gate_region"
        state.population[actor_id].pop("current_activity", None)
        state.population[actor_id].pop("current_decision", None)
        state.situations["night_world"]["actor_states"][actor_id]["layer"] = "surface"
    Handler.bridge = bridge
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print("GOALS_FIXTURE_READY real_npc_case explicit_inspector_location", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
