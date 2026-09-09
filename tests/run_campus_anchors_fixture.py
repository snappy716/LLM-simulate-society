"""Explicit thresholds; real material request, delivery and personal report."""
import argparse
from http.server import ThreadingHTTPServer
from simulation.api.server import Handler, SimulationBridge
from tests.test_campus_relationship_anchors import prepare_anchor_fixture


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    bridge = SimulationBridge()
    target, *_ = prepare_anchor_fixture(bridge.campus)
    bridge.campus.kernel._state.population[target]["display_name"] = "共同经历验收对象"
    Handler.bridge = bridge
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print("ANCHORS_FIXTURE_READY real_need_request_and_delivery explicit_thresholds no_api", flush=True)
        server.serve_forever()


if __name__ == "__main__": main()
