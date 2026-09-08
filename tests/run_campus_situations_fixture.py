"""Natural prior-night consequences plus an explicit low-stock UI boundary."""
import argparse
from http.server import ThreadingHTTPServer
from simulation.api.server import Handler, SimulationBridge
from simulation.systems.campus_situations import advance_campus_situations
from tests.test_campus_cognition import command
from tests.test_campus_situations import context_for


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    bridge = SimulationBridge()
    for _ in range(6):
        assert command(bridge.campus, "ADVANCE_PHASE")["ok"]
    for _ in range(12):
        assert command(bridge.campus, "ADVANCE_SOCIAL_PULSE")["ok"]
    state = bridge.campus.kernel._state
    assert any(t.get("situation_choice") for t in state.tasks.values())
    shop = next(iter(state.inventories["shops"].values()))
    shop["quantities"].pop(next(iter(shop["quantities"])))
    advance_campus_situations(context_for(state))
    assert any(row["pressure"] > 0 for row in state.situations["campus_dynamics"]["regions"].values())
    Handler.bridge = bridge
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print("SITUATIONS_FIXTURE_READY natural_expiry explicit_stock no_api", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
