"""Explicit strained relationship; real dispute resolver, commands and UI."""
import argparse
from http.server import ThreadingHTTPServer

from simulation.api.server import Handler, SimulationBridge
from tests.test_campus_disputes import prepare_dispute_fixture


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    bridge = SimulationBridge()
    state, first, second, *_ = prepare_dispute_fixture(bridge.campus)
    state.population[first]["display_name"] = "纠纷调解验收"
    state.population[second]["display_name"] = "争执另一方"
    # The second interview must use an existing contact, not teleportation.
    state.population[second]["current_location_id"] = next(p for p in state.places if p != state.population["player"]["current_location_id"])
    state.population[second].pop("current_activity", None)
    for actor in (first, second):
        state.population[actor].pop("current_decision", None)
    Handler.bridge = bridge
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print("DISPUTES_FIXTURE_READY explicit_relationship actual_confrontation no_api", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
