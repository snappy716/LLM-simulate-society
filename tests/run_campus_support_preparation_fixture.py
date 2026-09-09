"""Actual request and voluntary statement; explicit helpful-contact QA boundary."""
import argparse
from http.server import ThreadingHTTPServer
from simulation.api.server import Handler, SimulationBridge
from tests.test_campus_support_preparation import prepare_support_fixture
from tests.test_campus_combat_deployment import travel_to_location


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    bridge = SimulationBridge()
    _, helper, _ = prepare_support_fixture(bridge.campus)
    travel_to_location(bridge.campus, bridge.campus.kernel._state.population["player"]["current_location_id"], helper)
    bridge.campus.kernel._state.population[helper]["display_name"] = "求助研习验收对象"
    Handler.bridge = bridge
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print("SUPPORT_PREPARATION_FIXTURE_READY actual_request_and_statement helpful_contact no_api no_mastery_grant", flush=True)
        server.serve_forever()


if __name__ == "__main__": main()
