"""Actual public work evidence and sharing, explicit unresponsive contact."""
import argparse
from http.server import ThreadingHTTPServer
from simulation.api.server import Handler, SimulationBridge
from tests.test_campus_contact_leads import prepare_contact_lead_fixture


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    bridge = SimulationBridge()
    target, *_ = prepare_contact_lead_fixture(bridge.campus)
    bridge.campus.kernel._state.population[target]["display_name"] = "地点线索验收对象"
    Handler.bridge = bridge
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print("CONTACT_LEADS_FIXTURE_READY actual_work actual_share explicit_incapacity no_api", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
