"""Actual publication, player claim, traversal and common card combat, no fake win."""
import argparse
from http.server import ThreadingHTTPServer
from simulation.api.server import Handler, SimulationBridge
from tests.test_campus_night_sites import NightSitesTests


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    NightSitesTests.setUpClass()
    fixture = NightSitesTests()
    fixture.setUp()
    fixture.prepare()
    fixture.battle()
    bridge = SimulationBridge()
    bridge.campus = fixture.bridge
    Handler.bridge = bridge
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print("SITES_FIXTURE_READY actual_card_victory_and_physical_goal no_injected_result", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
