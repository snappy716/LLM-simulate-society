"""Real support and four phase commands; explicit protected next-day duty."""
import argparse
from http.server import ThreadingHTTPServer
from simulation.api.server import Handler, SimulationBridge
from tests.test_campus_support_followup import prepare_followup_fixture
from tests.test_campus_combat_deployment import travel_to_location


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    bridge = SimulationBridge()
    _, helper, _ = prepare_followup_fixture(bridge.campus)
    travel_to_location(bridge.campus, bridge.campus.kernel._state.population["player"]["current_location_id"], helper)
    bridge.campus.kernel._state.population[helper]["display_name"] = "后续关怀验收对象"
    Handler.bridge = bridge
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print("FOLLOWUP_FIXTURE_READY real_support real_next_dawn explicit_initial_knowledge_and_duty no_api", flush=True)
        server.serve_forever()


if __name__ == "__main__": main()
