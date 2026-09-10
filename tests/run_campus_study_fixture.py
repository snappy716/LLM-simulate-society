"""Actual route and phase only: the UI must perform the learning itself."""
import argparse
from http.server import ThreadingHTTPServer
from simulation.api.server import Handler, SimulationBridge
from tests.test_campus_parties import execute
from tests.test_campus_combat_deployment import travel_to_location

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    bridge = SimulationBridge()
    assert execute(bridge.campus, "ADVANCE_PHASE")["ok"]
    travel_to_location(bridge.campus, "humanities_classroom_pool")
    Handler.bridge = bridge
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print("STUDY_FIXTURE_READY real_route no_learning_injection no_api", flush=True)
        server.serve_forever()
