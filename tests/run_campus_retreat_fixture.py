"""Active combat fixture used to validate the rendered retreat path over HTTP."""
import argparse
from http.server import ThreadingHTTPServer

from simulation.api.server import Handler, SimulationBridge
from tests.test_campus_combat_rounds import deploy_and_start


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True, type=int)
    args = parser.parse_args()
    bridge = SimulationBridge()
    deploy_and_start(bridge.campus)
    Handler.bridge = bridge
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print("RETREAT_FIXTURE_READY active_combat_real_enemy_intent", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
