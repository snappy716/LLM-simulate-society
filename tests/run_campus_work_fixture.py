"""Reserve a real shift before phase simulation; never inject cash or wages."""
import argparse
from http.server import ThreadingHTTPServer
from simulation.api.server import Handler, SimulationBridge
from tests.test_campus_disputes import command
from tests.test_campus_parties import execute
from tests.test_campus_combat_deployment import travel_to_location

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    bridge = SimulationBridge()
    assert command(bridge.campus, "ENROLL_CAMPUS_OPPORTUNITY", {"session_id": "life:1:canteen_part_time"})["ok"]
    for _ in range(2):
        assert execute(bridge.campus, "ADVANCE_PHASE")["ok"]
    travel_to_location(bridge.campus, "canteen_dining_hall")
    Handler.bridge = bridge
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print("WORK_FIXTURE_READY real_booking_route no_wage_injection no_api", flush=True)
        server.serve_forever()
