"""Only NPC placement is a fixture; ground evidence comes from real drop action."""
import argparse
from http.server import ThreadingHTTPServer
from simulation.api.server import Handler, SimulationBridge
from tests.test_campus_combat_deployment import execute


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True, type=int)
    args = parser.parse_args()
    bridge = SimulationBridge()
    state = bridge.campus.kernel._state
    task = next(task for task in state.tasks.values() if task["forum"] == "surface")
    state.population["player"]["current_location_id"] = task["scene_id"]
    npc = next(key for key in state.population if key != "player")
    state.population[npc]["current_location_id"] = state.population["player"]["current_location_id"]
    assert execute(bridge.campus, "DROP_ITEM", {"item_id": "bread_loaf", "quantity": 1})["ok"]
    Handler.bridge = bridge
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print("INVESTIGATION_FIXTURE_READY real_ground_item nearby_npc", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
