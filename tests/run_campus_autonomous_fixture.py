"""Real NPC night execution without player help; only reveal the forum afterwards."""
import argparse
from http.server import ThreadingHTTPServer
from simulation.actions.commands import SimulationCommand
from simulation.api.server import Handler, SimulationBridge


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    bridge = SimulationBridge()
    def act(action, params=None):
        state = bridge.campus.kernel.state
        result = bridge.campus.kernel.execute(SimulationCommand(f"autonomous-fixture:{state.revision}:{action}", "player", action,
            state.revision, parameters=params or {}, issued_day=state.clock.day, issued_phase=state.clock.phase))
        assert result.success, result.code
    for _ in range(3):
        act("ADVANCE_PHASE")
    state = bridge.campus.kernel.state
    tasks = [task for task in state.tasks.values() if task.get("execution_receipts")]
    assert tasks and all("player" not in r["actor_ids"] for task in tasks for r in task["execution_receipts"])
    assert not bridge.campus.snapshot()["forums"]["night"]["enabled"]
    act("ENTER_NIGHT_WORLD")
    for task in tasks:
        act("VIEW_FORUM_TASK", {"task_id": task["task_id"]})
    Handler.bridge = bridge
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print("AUTONOMOUS_FIXTURE_READY real_three_phases actual_battles no_player_help no_paid_api", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
