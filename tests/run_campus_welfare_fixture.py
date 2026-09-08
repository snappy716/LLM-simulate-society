"""Real incident and dawn advancement; injury/colocation is an explicit UI fixture."""
import argparse
from http.server import ThreadingHTTPServer
from simulation.api.server import Handler, SimulationBridge
from simulation.systems.campus_vitals import change_vital
from tests.test_campus_welfare import prepare_welfare_fixture
from tests.test_campus_disputes import command


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    bridge = SimulationBridge()
    state, victim, helper, *_ = prepare_welfare_fixture(bridge.campus)
    state.relationships[victim][helper]["trust"] = 100
    for _ in range(2):
        assert command(bridge.campus, "ADVANCE_PHASE", {})["ok"]
    state = bridge.campus.kernel._state
    case = next(c for c in state.situations["campus_welfare"]["cases"].values() if c["actor_id"] == victim)
    # Keep an unresolved injury boundary when the natural routine has rested.
    # Only this explicit fixture restores the open case; production never does.
    case["status"] = "needs_care"
    state.population[victim]["display_name"] = "近况回访验收"
    state.population[victim]["current_location_id"] = state.population["player"]["current_location_id"]
    state.population[victim].pop("current_activity", None)
    state.population[victim].pop("current_decision", None)
    change_vital(state, victim, "health", -10)
    Handler.bridge = bridge
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print("WELFARE_FIXTURE_READY real_dawn explicit_injury no_api", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
