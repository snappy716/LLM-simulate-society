"""Three real autonomous days, no injected friendship, victory or inventory."""
import argparse
from pathlib import Path
import tempfile
from http.server import ThreadingHTTPServer
from simulation.actions.commands import SimulationCommand
from simulation.api.server import CampusKernelBridge, Handler, SimulationBridge


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="campus-expedition-fixture-") as directory:
        bridge = SimulationBridge(save_dir=Path(directory))
        bridge.campus = CampusKernelBridge(46)
        def act(action, params=None):
            state = bridge.campus.kernel.state
            result = bridge.campus.kernel.execute(SimulationCommand(f"expedition-fixture:{state.revision}:{action}", "player", action,
                state.revision, parameters=params or {}, issued_day=state.clock.day, issued_phase=state.clock.phase))
            assert result.success, result.code
        for _ in range(11):
            act("ADVANCE_PHASE")
        state = bridge.campus.kernel.state
        plans = [plan for plan in state.cognition["night_expeditions"]["plans"].values()
                 if plan["status"] == "completed" and len(plan["actual_member_ids"]) > 1]
        assert plans and all("player" not in plan["actual_member_ids"] for plan in plans)
        assert not bridge.campus.snapshot()["forums"]["night"]["enabled"]
        act("ENTER_NIGHT_WORLD")
        for plan in plans:
            act("VIEW_FORUM_TASK", {"task_id": plan["task_id"]})
        Handler.bridge = bridge
        with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
            print("EXPEDITION_FIXTURE_READY real_three_days consensual_party actual_combat shared_rewards no_paid_api", flush=True)
            server.serve_forever()


if __name__ == "__main__":
    main()
