"""Local UI acceptance fixture: two co-located NPCs and one real incoming quote.

Initial co-location is QA setup, not NPC pathfinding evidence. Offers and
settlement use production commands. No test-only mutation endpoint is added.
"""
import argparse
from http.server import ThreadingHTTPServer

from simulation.actions.commands import SimulationCommand
from simulation.api.server import Handler, SimulationBridge
from simulation.systems.campus_inventory import campus_inventory_invariant


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True, type=int)
    args = parser.parse_args()
    bridge = SimulationBridge()
    state = bridge.campus.kernel._state
    for actor_id in ("player", "campus_student_001", "campus_student_002"):
        state.population[actor_id]["current_location_id"] = "supermarket_sales_floor"
    result = bridge.campus.kernel.execute(SimulationCommand("fixture-incoming", "campus_student_002", "OFFER_TRADE", state.revision,
        parameters={"target_id": "player", "item_id": "bread_loaf", "unit_price": 4, "quantity": 1, "side": "sell"}, source="rule"))
    assert result.code == "offered", result
    assert not list(campus_inventory_invariant(bridge.campus.kernel.state))
    Handler.bridge = bridge
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print(f"TRADE_FIXTURE_READY {args.port} explicit_colocation_fixture", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
