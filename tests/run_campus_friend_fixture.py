"""Explicit friend-threshold and fake-provider fixture, never a real API call."""
import argparse
from http.server import ThreadingHTTPServer
from simulation.api.server import Handler, SimulationBridge
from simulation.systems.campus_social import DEFAULT_RELATIONSHIP
from tests.test_campus_cognition import LastLegalProvider, command


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    bridge = SimulationBridge()
    for _ in range(3):
        assert command(bridge.campus, "ADVANCE_PHASE")["ok"]
    state = bridge.campus.kernel._state
    ordinary = [n for n in state.population if n != "player" and n not in state.cognition["focused_ids"]]
    for index, npc in enumerate(ordinary[:2]):
        state.population[npc]["current_location_id"] = state.population["player"]["current_location_id"]
        state.population[npc].pop("current_activity", None)
        state.population[npc].pop("current_decision", None)
        state.population[npc]["display_name"] = "好友接入验收" if index == 0 else "普通同学验收"
        state.relationships[npc]["player"] = {**DEFAULT_RELATIONSHIP, "closeness": 45 if index == 0 else 0, "trust": 45}
    bridge.campus.cognition_runtime.provider = LastLegalProvider()
    Handler.bridge = bridge
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print("FRIEND_FIXTURE_READY explicit_relationship fake_provider no_paid_api", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
