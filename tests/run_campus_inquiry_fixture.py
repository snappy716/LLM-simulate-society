"""Explicit real stranded incident and NPC-authored contact inquiry."""
import argparse
from http.server import ThreadingHTTPServer
from simulation.api.server import Handler, SimulationBridge
from tests.test_campus_contact_inquiries import prepare_inquiry_fixture
from tests.test_campus_combat_deployment import travel_to_location


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    bridge = SimulationBridge()
    target, *_ = prepare_inquiry_fixture(bridge.campus)
    travel_to_location(bridge.campus, "south_gate", "player")
    bridge.campus.kernel._state.population[target]["display_name"] = "寻访对象验收"
    Handler.bridge = bridge
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print("INQUIRY_FIXTURE_READY actual_npc_message task physical_player_travel explicit_incident no_api", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
