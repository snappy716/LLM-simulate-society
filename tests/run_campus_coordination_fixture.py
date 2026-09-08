"""Compatible schedules are explicit fixtures; invitation and UI use production code."""
import argparse
from http.server import ThreadingHTTPServer
from simulation.api.server import Handler, SimulationBridge
from simulation.systems.campus_social import DEFAULT_RELATIONSHIP
from simulation.systems.campus_messaging import load_campus_messaging_policy
from simulation.systems.campus_social_coordination import coordinate_daily_social
from tests.test_campus_social_coordination import prepare_fixture


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    bridge = SimulationBridge()
    state, actor, target, plans, registry, context = prepare_fixture(bridge.campus)
    state.population[actor]["display_name"] = "邀约协调验收"
    state.population[target]["display_name"] = "约好的同学"
    plans[actor]["evening"]["social_intent"]["target_name"] = "约好的同学"
    coordinate_daily_social(context, plans, load_campus_messaging_policy(registry))
    assert state.cognition["social_coordination"]["actors"][actor]["status"] == "confirmed"
    state.population[actor]["current_location_id"] = state.population["player"]["current_location_id"]
    state.population[actor].pop("current_activity", None)
    state.population[actor].pop("current_decision", None)
    state.relationships[actor]["player"] = {**DEFAULT_RELATIONSHIP, "closeness": 50, "trust": 50}
    Handler.bridge = bridge
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print("COORDINATION_FIXTURE_READY explicit_schedules actual_phone_exchange no_api", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
