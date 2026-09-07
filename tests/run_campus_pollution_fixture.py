"""Explicit 29-pollution combat fixture for rendered threshold feedback."""
import argparse
from http.server import ThreadingHTTPServer

from simulation.api.server import Handler, SimulationBridge
from simulation.systems.campus_combat import sync_combat_pollution_status
from tests.test_campus_combat_rounds import deploy_and_start


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True, type=int)
    args = parser.parse_args()
    bridge = SimulationBridge()
    battle = deploy_and_start(bridge.campus)
    state = bridge.campus.kernel._state
    stored = state.battles[battle["battle_id"]]
    stored["pollution"]["player"] = 29
    state.situations["night_world"]["actor_states"]["player"]["pollution"] = 29
    sync_combat_pollution_status(stored, "player")
    Handler.bridge = bridge
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print("POLLUTION_FIXTURE_READY active_combat_pollution_29", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
