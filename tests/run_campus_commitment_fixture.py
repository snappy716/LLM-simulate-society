"""Actual NPC claim and expiry; delayed execution and UI colocation are fixtures."""
import argparse
from http.server import ThreadingHTTPServer
from simulation.api.server import Handler, SimulationBridge
from tests.test_campus_commitment_disputes import prepare_commitment_fixture


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    bridge = SimulationBridge()
    state, _, issuer, _, _ = prepare_commitment_fixture(bridge.campus)
    state.population[issuer]["display_name"] = "履约核对验收"
    state.population[issuer]["current_location_id"] = state.population["player"]["current_location_id"]
    state.population[issuer].pop("current_activity", None)
    state.population[issuer].pop("current_decision", None)
    Handler.bridge = bridge
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print("COMMITMENT_FIXTURE_READY real_claim_expiry explicit_execution_delay no_api", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
