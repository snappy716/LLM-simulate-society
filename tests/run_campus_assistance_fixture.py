"""Explicit missing-notebook/co-location fixture, real contact and NPC request."""
import argparse
from http.server import ThreadingHTTPServer
from simulation.actions.commands import SimulationCommand
from simulation.api.server import Handler, SimulationBridge


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    bridge = SimulationBridge()
    state = bridge.campus.kernel._state
    npc = "campus_student_001"
    for actor_id in ("player", npc):
        state.population[actor_id]["current_location_id"] = "south_gate_region"
    state.population[npc]["wealth"] = 0
    state.inventories["actors"][npc]["quantities"].pop("blank_notebook", None)
    contact = bridge.campus.kernel.execute(SimulationCommand("help-fixture-contact", "player", "ADD_PHONE_CONTACT", state.revision,
                   parameters={"target_id": npc}, issued_day=state.clock.day, issued_phase=state.clock.phase))
    assert contact.success, contact
    state = bridge.campus.kernel.state
    request = bridge.campus.kernel.execute(SimulationCommand("help-fixture-request", npc, "REQUEST_MATERIAL_HELP", state.revision,
                   parameters={"helper_id": "player", "item_id": "blank_notebook"}, source="rule", issued_day=state.clock.day, issued_phase=state.clock.phase))
    assert request.success and request.payload["request"]["status"] == "pending", request
    Handler.bridge = bridge
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print("ASSISTANCE_FIXTURE_READY explicit_need real_npc_request no_auto_player_consent", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
