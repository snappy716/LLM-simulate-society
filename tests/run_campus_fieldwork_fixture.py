"""Fresh publication, real claim and travel; no injected clues or report result."""
import argparse
from pathlib import Path
import tempfile
from http.server import ThreadingHTTPServer
from simulation.api.server import CampusKernelBridge, Handler, SimulationBridge
from tests.test_campus_combat_deployment import execute, travel_to_location


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="campus-field-fixture-") as directory:
        bridge = SimulationBridge(save_dir=Path(directory))
        bridge.campus = CampusKernelBridge(42)
        for index in range(2):
            assert execute(bridge.campus, "ADVANCE_PHASE", marker=f"field-phase-{index}")["ok"]
        assert execute(bridge.campus, "ENTER_NIGHT_WORLD")["ok"]
        task = next(t for t in bridge.campus.kernel.state.tasks.values() if t.get("resolution_kind") == "field_recon"
                    and t["state"] in {"open", "viewed", "considering"})
        assert execute(bridge.campus, "CLAIM_FORUM_TASK", {"task_id": task["task_id"], "expected_task_revision": task["lock_revision"]})["ok"]
        travel_to_location(bridge.campus, task["scene_id"])
        Handler.bridge = bridge
        with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
            print("FIELDWORK_FIXTURE_READY real_publication_claim_and_travel no_injected_readings", flush=True)
            server.serve_forever()


if __name__ == "__main__":
    main()
