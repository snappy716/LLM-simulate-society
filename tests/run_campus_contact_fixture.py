"""Controlled real stranded site; Godot sends messages then advances to actual dawn."""
import argparse
from http.server import ThreadingHTTPServer
from simulation.api.server import Handler, SimulationBridge
from tests.test_campus_welfare import prepare_welfare_fixture


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    bridge = SimulationBridge()
    state, victim, *_ = prepare_welfare_fixture(bridge.campus)
    state.population[victim]["display_name"] = "联系状态验收"
    Handler.bridge = bridge
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print("CONTACT_FIXTURE_READY actual_stranded_site explicit_incident no_api", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
