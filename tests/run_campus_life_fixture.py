"""Real phase advance and route before UI check; no attendance/reward injection."""
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
    travel_to_location(bridge.campus, "indoor_sports_hall")
    Handler.bridge = bridge
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print("LIFE_FIXTURE_READY actual_phase_and_routes no_attendance_injection no_api", flush=True)
        server.serve_forever()
