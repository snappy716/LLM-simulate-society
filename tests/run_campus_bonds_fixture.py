"""Real completed dates with explicit readiness; not natural romance evidence."""
import argparse
from http.server import ThreadingHTTPServer
from simulation.api.server import Handler, SimulationBridge
from tests.test_campus_bonds import prepare_bond_fixture
from tests.test_campus_contact_inquiries import as_npc

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    bridge = SimulationBridge()
    people = prepare_bond_fixture(bridge.campus)
    for actor in people[:2]:
        result = as_npc(bridge.campus, actor, "PROPOSE_CAMPUS_BOND", {"target_id": "player", "kind": "romance"})
        assert result.success and result.payload["bond"]["status"] == "pending", result.code
    Handler.bridge = bridge
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print("BONDS_FIXTURE_READY two_pending_proposals real_completed_dates no_api", flush=True)
        server.serve_forever()
