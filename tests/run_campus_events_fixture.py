"""Explicit phase boundary; all enrollment, travel and performance use commands."""
import argparse
from http.server import ThreadingHTTPServer
from simulation.api.server import Handler, SimulationBridge
from tests.test_campus_events import event_boundary
from tests.test_campus_combat_deployment import travel_to_location


def serve(kind="competition"):
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    bridge = SimulationBridge()
    event_boundary(bridge.campus, kind)
    travel_to_location(bridge.campus, "indoor_sports_hall" if kind == "competition" else "mirror_lake_square")
    Handler.bridge = bridge
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print(f"EVENTS_FIXTURE_READY {kind} explicit_phase_boundary real_route no_scores_or_attendance_injected no_api", flush=True)
        server.serve_forever()


if __name__ == "__main__": serve()
