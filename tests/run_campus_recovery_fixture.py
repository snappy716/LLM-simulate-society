"""Explicit local Godot QA fixture. Never imported by the production launcher.

Seeds a wounded player and bandages; this is not evidence of enemy AI damage.
Launch with --port, then Godot with GODOT_SIM_EXTERNAL_SERVER=1 and same port.
"""
from __future__ import annotations

import argparse
from http.server import ThreadingHTTPServer
from simulation.api.server import Handler, SimulationBridge
from simulation.systems.campus_vitals import change_vital, campus_vitals_invariant
from tests.test_campus_combat_deployment import execute


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True, type=int)
    args = parser.parse_args()
    bridge = SimulationBridge()
    for _ in range(2):
        assert execute(bridge.campus, "ADVANCE_PHASE")["ok"]
    assert execute(bridge.campus, "ENTER_NIGHT_WORLD")["ok"]
    state = bridge.campus.kernel._state
    player = state.population["player"]
    player["current_location_id"] = player["home_location_id"]
    change_vital(state, "player", "health", 15 - player["vitals"]["health"])
    change_vital(state, "player", "focus", -10)
    state.inventories["actors"]["player"]["quantities"]["bandage_roll"] = 2
    assert not list(campus_vitals_invariant(state))
    Handler.bridge = bridge
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print(f"RECOVERY_FIXTURE_READY {args.port} HP=15 TEST_DATA_ONLY", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
