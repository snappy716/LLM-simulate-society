"""Explicit wounded battle fixture; pharmacy purchase and treatment are real."""
import argparse
from http.server import ThreadingHTTPServer

from simulation.api.server import Handler, SimulationBridge
from simulation.systems.campus_vitals import change_vital
from tests.test_campus_combat_deployment import execute
from tests.test_campus_combat_rounds import deploy_and_start


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True, type=int)
    args = parser.parse_args()
    bridge = SimulationBridge()
    bridge.campus.kernel._state.population["player"]["current_location_id"] = "hospital_pharmacy"
    bought = execute(bridge.campus, "BUY_ITEM", {"item_id": "bandage_roll", "quantity": 2,
                                               "shop_id": "campus_pharmacy"})
    assert bought["ok"], bought
    deploy_and_start(bridge.campus)
    change_vital(bridge.campus.kernel._state, "player", "health", -30)
    Handler.bridge = bridge
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print("COMBAT_ITEM_FIXTURE_READY purchased_two_bandages_wounded_player", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
