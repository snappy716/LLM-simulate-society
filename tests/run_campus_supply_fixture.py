"""Explicit empty-shelf Godot QA fixture, then production phase processing.

The empty starting shelf is test setup; the order, payment, next-day delivery
and customer purchase are real campus commands. No privileged HTTP API added.
"""
import argparse
from http.server import ThreadingHTTPServer

from simulation.actions.commands import SimulationCommand
from simulation.api.server import Handler, SimulationBridge


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True, type=int)
    args = parser.parse_args()
    bridge = SimulationBridge()
    state = bridge.campus.kernel._state
    state.population["player"]["current_location_id"] = "supermarket_sales_floor"
    state.inventories["shops"]["campus_market"]["quantities"].pop("bread_loaf")
    result = bridge.campus.kernel.execute(SimulationCommand("supply-fixture-start", "player", "ADVANCE_PHASE", state.revision))
    assert result.success, result
    assert any(o["item_id"] == "bread_loaf" and o["status"] == "in_transit" for o in bridge.campus.kernel.state.inventories["supply"]["orders"].values())
    Handler.bridge = bridge
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print(f"SUPPLY_FIXTURE_READY {args.port} explicit_empty_shelf", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
