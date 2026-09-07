"""Home-location fixture only; reading and deck configuration are real commands."""
import argparse
from http.server import ThreadingHTTPServer
from simulation.api.server import Handler, SimulationBridge


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    bridge = SimulationBridge()
    actor = bridge.campus.kernel._state.population["player"]
    actor["current_location_id"] = actor["home_location_id"]
    Handler.bridge = bridge
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print("GROWTH_FIXTURE_READY home_location_no_free_experience", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
