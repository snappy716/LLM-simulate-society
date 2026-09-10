"""Natural NPC activity, no affinity/plan/receipt injection or paid API."""
import argparse
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from simulation.api.server import Handler, SimulationBridge
from simulation.actions.commands import SimulationCommand
from simulation.systems.campus_outings import records, outings_invariant
from tests.test_campus_combat_deployment import travel_to_location


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    with patch("urllib.request.urlopen", side_effect=AssertionError("Offline acceptance only")):
        bridge = SimulationBridge()
        for step in range(20):
            state = bridge.campus.kernel._state
            result = bridge.campus.kernel.execute(SimulationCommand(f"natural-ui:{step}", "player", "ADVANCE_PHASE",
                state.revision, issued_day=state.clock.day, issued_phase=state.clock.phase))
            assert result.success, result.code
            state = bridge.campus.kernel._state
            assert not outings_invariant(state)
            done = [r for r in records(state).values() if r["status"] == "completed"
                and (r["day"], r["phase"]) == (state.clock.day, state.clock.phase)]
            if done:
                assert all("player" not in (r["proposer_id"], r["recipient_id"]) for r in done)
                travel_to_location(bridge.campus, done[0]["location_id"])
                break
        else:
            raise AssertionError("No naturally completed shared activity within five days")
        Handler.bridge = bridge
        with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
            print("SOCIAL_PACING_FIXTURE_READY natural_shared_activity real_player_route no_api", flush=True)
            server.serve_forever()
