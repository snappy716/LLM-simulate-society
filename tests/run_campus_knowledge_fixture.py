"""Explicit 75-understanding threshold fixture; tactic and enemy turn are real."""
import argparse
from http.server import ThreadingHTTPServer
from simulation.api.server import Handler, SimulationBridge
from simulation.systems.campus_growth import _actor_growth, project_growth_events
from tests.test_campus_combat_rounds import deploy_and_start


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    bridge = SimulationBridge()
    deploy_and_start(bridge.campus, teammate_count=1)
    state = bridge.campus.kernel._state
    battle = next(iter(state.battles.values()))
    topic = next(iter(battle["enemy_units"].values()))["archetype_id"]
    _actor_growth(state, "player")["topics"][topic] = {"theory": 40, "cases": 30, "application": 5, "reflection": 0}
    project_growth_events(state, [])
    Handler.bridge = bridge
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print("KNOWLEDGE_FIXTURE_READY explicit_understanding_threshold_75", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
