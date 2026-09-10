"""Real booking and incident; explicit pre-execution phase boundary, no API."""
import argparse
from http.server import ThreadingHTTPServer
from simulation.api.server import Handler, SimulationBridge
from tests.test_campus_anomalies import prepare_anomaly_fixture
from tests.test_campus_support_reservations import reserve_for_support


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    bridge = SimulationBridge()
    target, helper, _ = prepare_anomaly_fixture(bridge.campus)
    reserve_for_support(bridge.campus, target, helper, "player")
    bridge.campus.kernel._state.population[target]["display_name"] = "预约冲突验收对象"
    Handler.bridge = bridge
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print("SUPPORT_RESERVATIONS_FIXTURE_READY real_booking real_incident explicit_phase_boundary no_api", flush=True)
        server.serve_forever()
