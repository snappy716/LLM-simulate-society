"""Actual daytime support followed by real deployment/card victory/containment."""
import argparse
from http.server import ThreadingHTTPServer
from simulation.api.server import Handler, SimulationBridge
from tests.test_campus_anomaly_combat import prepare_afterimage_fixture, claim_afterimage, win_afterimage


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    bridge = SimulationBridge()
    _, _, task_id = prepare_afterimage_fixture(bridge.campus, support=True)
    claim_afterimage(bridge.campus, task_id)
    win_afterimage(bridge.campus, task_id)
    Handler.bridge = bridge
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print("AFTERIMAGE_FIXTURE_READY real_support_card_victory_and_containment explicit_prior_incident no_api", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
