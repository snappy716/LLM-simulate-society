"""Explicit one-HP combat fixture; enemy attack and rescue are production code."""
import argparse
from http.server import ThreadingHTTPServer

from simulation.api.server import Handler, SimulationBridge
from simulation.systems.campus_vitals import change_vital
from tests.test_campus_combat_rounds import deploy_and_start


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True, type=int)
    args = parser.parse_args()
    bridge = SimulationBridge()
    deploy_and_start(bridge.campus)
    state = bridge.campus.kernel._state
    change_vital(state, "player", "health", 1 - state.population["player"]["vitals"]["health"])
    Handler.bridge = bridge
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print("ENEMY_FIXTURE_READY one_hp_boundary_real_enemy_and_rescue", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
