"""Wounded-player clinic QA, explicitly seeded, no paid model calls."""
import argparse
from http.server import ThreadingHTTPServer

from simulation.api.server import Handler, SimulationBridge
from tests.test_campus_contact_inquiries import as_npc
from simulation.systems.campus_medical import LOCATION, medical_invariant


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    bridge = SimulationBridge()
    state = bridge.campus.kernel._state
    staff = next(who for who, p in state.population.items() if p.get("occupation_id") == "medical_staff")
    state.population[staff]["current_location_id"] = LOCATION
    state.population["player"]["current_location_id"] = "campus_hospital"
    state.population["player"]["vitals"].update(health=1, focus=1)
    state.population["player"]["wealth"] = 500
    assert as_npc(bridge.campus, staff, "MEDICAL_SHIFT", {}).success
    assert not medical_invariant(bridge.campus.kernel.state)
    Handler.bridge = bridge
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print(f"MEDICAL_FIXTURE_READY {args.port} explicit_injury_actual_staff_command no_api", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
