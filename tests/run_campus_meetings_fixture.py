"""Actual released incident and private statement; no appointment outcome injection."""
import argparse
from http.server import ThreadingHTTPServer
from simulation.api.server import Handler, SimulationBridge
from tests.test_campus_anomaly_meetings import prepare_meeting_fixture


def main(incoming=False):
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    bridge = SimulationBridge()
    target, cid = prepare_meeting_fixture(bridge.campus)
    if incoming:
        from tests.test_campus_contact_inquiries import as_npc
        from simulation.systems.campus_anomaly_meetings import options
        state = bridge.campus.kernel._state
        choice = options(state, state.situations["campus_anomalies"]["cases"][cid], "player", bridge.campus.location_graph)[0]
        assert as_npc(bridge.campus, target, "PROPOSE_ANOMALY_MEETING", {"case_id": cid, "helper_id": "player", **choice}).success
    bridge.campus.kernel._state.population[target]["display_name"] = "支持预约验收对象"
    Handler.bridge = bridge
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print("MEETINGS_FIXTURE_READY real_incident explicit_contact_knowledge no_api", flush=True)
        server.serve_forever()


if __name__ == "__main__": main()
