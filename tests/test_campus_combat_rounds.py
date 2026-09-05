from __future__ import annotations

import json
import unittest
from collections import Counter
from pathlib import Path

from simulation.api.server import CampusKernelBridge
from simulation.systems import campus_combat_invariant
from tests.test_campus_combat_deployment import enter_with_owned_night_task, execute


REPOSITORY_DIR = Path(__file__).resolve().parents[1]


def deploy_and_start(bridge: CampusKernelBridge, *, teammate_count: int = 0) -> dict:
    task = enter_with_owned_night_task(bridge)
    for _ in range(teammate_count):
        engaged = {
            str(candidate.get("assignee_id"))
            for candidate in bridge.kernel._state.tasks.values()
            if isinstance(candidate, dict)
            and candidate.get("state") in {"locked", "in_progress"}
        }
        candidate = next(
            item for item in bridge.snapshot()["party"]["candidates"]
            if item["expected_response"] == "likely_accept"
            and item["can_invite"]
            and item["actor_id"] not in engaged
        )
        invited = execute(
            bridge, "INVITE_PARTY_MEMBER", {"target_id": candidate["actor_id"]},
            marker=f"round-invite-{candidate['actor_id']}",
        )
        assert invited["ok"], invited
    started = execute(
        bridge, "START_BATTLE_PREPARATION", {"task_id": task["task_id"]},
        marker="round-prepare",
    )
    assert started["ok"], started
    battle = started["snapshot"]["combat"]["active_battle"]
    rows = ("front", "middle", "back")
    for index, card in enumerate(battle["character_cards"].values()):
        current = bridge.snapshot()["combat"]["active_battle"]
        deployed = execute(bridge, "DEPLOY_COMBAT_CHARACTER", {
            "battle_id": current["battle_id"],
            "expected_battle_revision": current["revision"],
            "character_card_instance_id": card["character_card_instance_id"],
            "destination_row": rows[index % len(rows)],
        }, marker=f"round-deploy-{index}")
        assert deployed["ok"], deployed
    current = bridge.snapshot()["combat"]["active_battle"]
    confirmed = execute(bridge, "CONFIRM_BATTLE_DEPLOYMENT", {
        "battle_id": current["battle_id"],
        "expected_battle_revision": current["revision"],
    }, marker="round-confirm")
    assert confirmed["ok"], confirmed
    current = confirmed["snapshot"]["combat"]["active_battle"]
    launched = execute(bridge, "START_CARD_COMBAT", {
        "battle_id": current["battle_id"],
        "expected_battle_revision": current["revision"],
    }, marker="round-launch")
    assert launched["ok"], launched
    return launched["snapshot"]["combat"]["active_battle"]


class CampusCombatRoundTests(unittest.TestCase):
    def test_three_deployed_actors_get_eight_card_decks_and_six_shared_cards(self):
        # Seed 46 leaves two willing night-capable candidates uncommitted after
        # the evening forum race, so the test exercises a real three-person party.
        bridge = CampusKernelBridge(46)
        battle = deploy_and_start(bridge, teammate_count=2)
        self.assertEqual("player_turn", battle["phase"])
        self.assertEqual(3, len(battle["participant_ids"]))
        self.assertEqual(6, len(battle["shared_hand_ids"]))
        self.assertEqual(3, battle["command_point_cap"])
        self.assertEqual({"party:player": 3}, battle["command_points"])
        for actor_id in battle["participant_ids"]:
            deck = battle["actor_decks"][actor_id]
            self.assertEqual(8, len(deck))
            card_types = {
                instance["card_type"]
                for instance in battle["card_instances"].values()
                if instance["owner_actor_id"] == actor_id
            }
            self.assertIn("defense", card_types)
            self.assertTrue(card_types & {"defense", "support", "control", "knowledge"})
            self.assertEqual(
                2,
                sum(
                    battle["card_instances"][instance_id]["owner_actor_id"] == actor_id
                    for instance_id in battle["shared_hand_ids"]
                ),
            )
        self.assertEqual([], list(campus_combat_invariant(bridge.kernel.state)))

    def test_initial_shuffle_and_draw_are_seeded_and_reproducible(self):
        first = CampusKernelBridge(79)
        second = CampusKernelBridge(79)
        first_battle = deploy_and_start(first)
        second_battle = deploy_and_start(second)
        for field in ("actor_decks", "draw_piles", "shared_hand_ids", "card_instances"):
            self.assertEqual(first_battle[field], second_battle[field])

    def test_end_round_discards_unplayed_cards_refills_points_and_draws_again(self):
        bridge = CampusKernelBridge(42)
        first = deploy_and_start(bridge)
        first_hand = list(first["shared_hand_ids"])
        result = execute(bridge, "END_COMBAT_ROUND", {
            "battle_id": first["battle_id"],
            "expected_battle_revision": first["revision"],
        }, marker="round-end-one")
        self.assertTrue(result["ok"], result)
        second = result["snapshot"]["combat"]["active_battle"]
        self.assertEqual(2, second["round"])
        self.assertEqual(4, second["command_point_cap"])
        self.assertEqual(4, second["command_points"]["party:player"])
        self.assertEqual(first_hand, second["discard_piles"]["player"])
        self.assertEqual(2, len(second["shared_hand_ids"]))
        self.assertTrue(set(first_hand).isdisjoint(second["shared_hand_ids"]))
        event = next(
            event for event in result["result"]["events"]
            if event["event_type"] == "COMBAT_ROUND_STARTED"
        )
        self.assertEqual(2, event["payload"]["round"])
        self.assertEqual([], list(campus_combat_invariant(bridge.kernel.state)))

    def test_empty_draw_pile_reshuffles_discard_with_named_rng_and_caps_at_six(self):
        bridge = CampusKernelBridge(42)
        battle = deploy_and_start(bridge)
        for index in range(5):
            result = execute(bridge, "END_COMBAT_ROUND", {
                "battle_id": battle["battle_id"],
                "expected_battle_revision": battle["revision"],
            }, marker=f"round-cycle-{index}")
            self.assertTrue(result["ok"], result)
            battle = result["snapshot"]["combat"]["active_battle"]
        self.assertEqual(6, battle["round"])
        self.assertEqual(6, battle["command_point_cap"])
        self.assertGreaterEqual(battle["reshuffle_counts"]["player"], 1)
        zone_ids = (
            battle["draw_piles"]["player"]
            + battle["discard_piles"]["player"]
            + battle["exhaust_piles"]["player"]
            + battle["shared_hand_ids"]
        )
        self.assertEqual(8, len(zone_ids))
        self.assertEqual(8, len(set(zone_ids)))
        self.assertEqual(
            Counter(battle["actor_decks"]["player"]),
            Counter(battle["card_instances"][value]["card_id"] for value in zone_ids),
        )
        self.assertEqual([], list(campus_combat_invariant(bridge.kernel.state)))

    def test_card_instances_fit_contract_and_round_events_enter_chronicle(self):
        bridge = CampusKernelBridge(42)
        battle = deploy_and_start(bridge)
        schema = json.loads(
            (REPOSITORY_DIR / "contracts/combat_card.schema.json").read_text(encoding="utf-8")
        )
        allowed = set(schema["properties"])
        required = set(schema["required"])
        for instance in battle["card_instances"].values():
            self.assertTrue(required.issubset(instance))
            self.assertTrue(set(instance).issubset(allowed))
        entries = [
            bridge.kernel._state.chronicles["entries"][entry_id]
            for entry_id in bridge.kernel._state.chronicles["by_actor"]["player"]
        ]
        self.assertTrue(any(
            entry["event_type"] == "COMBAT_ROUND_STARTED"
            and entry["category"] == "combat"
            and entry["parameters"].get("runtime_started") is True
            for entry in entries
        ))

    def test_start_and_end_require_the_correct_phase_without_partial_mutation(self):
        bridge = CampusKernelBridge(42)
        task = enter_with_owned_night_task(bridge)
        prepared = execute(
            bridge, "START_BATTLE_PREPARATION", {"task_id": task["task_id"]},
            marker="round-wrong-phase-prepare",
        )
        battle = prepared["snapshot"]["combat"]["active_battle"]
        before = bridge.kernel.state.battles[battle["battle_id"]]
        blocked = execute(bridge, "START_CARD_COMBAT", {
            "battle_id": battle["battle_id"],
            "expected_battle_revision": battle["revision"],
        }, marker="round-wrong-phase-start")
        self.assertFalse(blocked["ok"])
        self.assertEqual("formation_not_ready", blocked["result"]["code"])
        self.assertEqual(before, bridge.kernel.state.battles[battle["battle_id"]])
        blocked_end = execute(bridge, "END_COMBAT_ROUND", {
            "battle_id": battle["battle_id"],
            "expected_battle_revision": battle["revision"],
        }, marker="round-wrong-phase-end")
        self.assertFalse(blocked_end["ok"])
        self.assertEqual("wrong_battle_phase", blocked_end["result"]["code"])
        self.assertEqual(before, bridge.kernel.state.battles[battle["battle_id"]])

    def test_daylight_safely_interrupts_unresolved_round_runtime(self):
        bridge = CampusKernelBridge(46)
        battle = deploy_and_start(bridge, teammate_count=2)
        teammate_locations = {
            actor_id: bridge.kernel._state.population[actor_id]["current_location_id"]
            for actor_id in battle["participant_ids"] if actor_id != "player"
        }
        late_night = execute(bridge, "ADVANCE_PHASE", marker="round-to-late-night")
        self.assertTrue(late_night["ok"], late_night)
        self.assertIsNotNone(late_night["snapshot"]["combat"]["active_battle"])
        self.assertEqual(
            2,
            late_night["result"]["payload"]["phase_execution"]["combat_engaged_actor_count"],
        )
        self.assertEqual(teammate_locations, {
            actor_id: bridge.kernel._state.population[actor_id]["current_location_id"]
            for actor_id in teammate_locations
        })
        morning = execute(bridge, "ADVANCE_PHASE", marker="round-to-morning")
        self.assertTrue(morning["ok"], morning)
        execution = morning["result"]["payload"]["phase_execution"]
        self.assertEqual(1, execution["battle_interrupted_count"])
        self.assertIsNone(morning["snapshot"]["combat"]["active_battle"])
        self.assertEqual("surface", morning["snapshot"]["night_world"]["current_layer"])
        self.assertNotIn(battle["battle_id"], bridge.kernel._state.battles)

    def test_active_combat_prevents_campus_map_travel(self):
        bridge = CampusKernelBridge(42)
        battle = deploy_and_start(bridge)
        current_location = bridge.kernel._state.population["player"]["current_location_id"]
        destination = "south_gate_region" if current_location != "south_gate_region" else "east_dorm_region"
        blocked = execute(bridge, "FAST_TRAVEL_CAMPUS", {
            "destination_id": destination,
        }, marker="round-block-travel")
        self.assertFalse(blocked["ok"])
        self.assertEqual("combat_active", blocked["result"]["code"])
        self.assertEqual(
            current_location,
            bridge.kernel._state.population["player"]["current_location_id"],
        )
        self.assertEqual(
            battle["revision"],
            bridge.snapshot()["combat"]["active_battle"]["revision"],
        )


if __name__ == "__main__":
    unittest.main()
