"""Actual consented material help -> source-bound afterimage battle fixture."""
import argparse
from http.server import ThreadingHTTPServer
from simulation.api.server import Handler, SimulationBridge
from tests.test_campus_evidence_insight import prepare_evidence_fixture


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    bridge = SimulationBridge()
    prepare_evidence_fixture(bridge.campus)
    Handler.bridge = bridge
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print("EVIDENCE_FIXTURE_READY actual_anchor_and_battle explicit_initial_thresholds no_api", flush=True)
        server.serve_forever()


if __name__ == "__main__": main()
