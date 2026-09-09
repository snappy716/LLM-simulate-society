"""Real incident and dawn; explicitly prepared appointment/knowledge for UI QA."""
import argparse
from http.server import ThreadingHTTPServer
from simulation.api.server import Handler, SimulationBridge
from tests.test_campus_anomalies import prepare_anomaly_fixture


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    bridge = SimulationBridge()
    target, _, _ = prepare_anomaly_fixture(bridge.campus)
    bridge.campus.kernel._state.population[target]["display_name"] = "月相体验验收对象"
    Handler.bridge = bridge
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print("ANOMALY_FIXTURE_READY real_release explicit_appointment_and_knowledge no_api", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
