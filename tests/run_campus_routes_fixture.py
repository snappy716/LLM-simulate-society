"""Actual daytime support -> victory/site closure -> fresh voluntary report."""
import argparse
from http.server import ThreadingHTTPServer
from simulation.api.server import Handler, SimulationBridge
from tests.test_campus_anomaly_feedback import prepare_route_fixture
from tests.test_campus_combat_deployment import travel_to_location


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    bridge = SimulationBridge()
    target, _, _ = prepare_route_fixture(bridge.campus)
    # Meet the NPC where they really went, without moving them or adding nodes.
    travel_to_location(bridge.campus, bridge.campus.kernel._state.population[target]["current_location_id"])
    Handler.bridge = bridge
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print("ROUTES_FIXTURE_READY actual_support actual_victory actual_disclosure no_api", flush=True)
        server.serve_forever()


if __name__ == "__main__": main()
