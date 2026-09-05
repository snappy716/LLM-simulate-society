from __future__ import annotations

import json
import unittest
from pathlib import Path

from simulation.actions import SimulationCommand
from simulation.api.server import CampusKernelBridge
from simulation.systems import (
    DeterministicRngPool,
    TransactionContext,
    campus_combat_invariant,
    incapacitate_character,
)


REPOSITORY_DIR = Path(__file__).resolve().parents[1]


def execute(bridge: CampusKernelBridge, action_id: str, parameters=None, marker="command") -> dict:
    snapshot = bridge.snapshot()
    clock = snapshot["clock"]
    return bridge.execute({
        "command_id": f"combat-{marker}-{snapshot['revision']}",
        "actor_id": "player",
        "action_id": action_id,
        "target_ids": [],
        "parameters": parameters or {},
        "expected_world_revision": snapshot["revision"],
        "issued_day": clock["day"],
        "issued_phase": clock["phase"],
        "issued_minute": clock["minute"],
        "source": "player",
    })


def invite_available_members(bridge: CampusKernelBridge, count: int = 2) -> list[str]:
    invited: list[str] = []
    for _ in range(count):
        candidate = next(
            item for item in bridge.snapshot()["party"]["candidates"]
            if item["expected_response"] == "likely_accept" and item["can_invite"]
        )
        result = execute(
            bridge, "INVITE_PARTY_MEMBER", {"target_id": candidate["actor_id"]},
            marker=f"invite-{candidate['actor_id']}",
        )
        if result["ok"]:
            invited.append(candidate["actor_id"])
    return invited


def enter_with_owned_night_task(bridge: CampusKernelBridge) -> dict:
    execute(bridge, "ADVANCE_PHASE", marker="to-afternoon")
    execute(bridge, "ADVANCE_PHASE", marker="to-evening")
    entered = execute(bridge, "ENTER_NIGHT_WORLD", marker="enter-night")
    if not entered["ok"]:
        destination = next(iter(bridge.snapshot()["night_world"]["moon"]), None)
        raise AssertionError((destination, entered))
    task = next(
        task for task in bridge.snapshot()["tasks"].values()
        if task.get("forum") == "night"
        and task.get("state") in {"open", "viewed", "considering"}
    )
    claimed = execute(
        bridge, "CLAIM_FORUM_TASK",
        {"task_id": task["task_id"], "expected_task_revision": task["lock_revision"]},
        marker="claim-night-task",
    )
    assert claimed["ok"], claimed
    travelled = execute(
        bridge, "FAST_TRAVEL_CAMPUS",
        {"destination_id": task["execution_region_id"]}, marker="travel-task",
    )
    assert travelled["ok"] or travelled["result"]["code"] == "already_there", travelled
    return bridge.snapshot()["tasks"][task["task_id"]]


class CampusCombatDeploymentTests(unittest.TestCase):
    def test_character_cards_read_real_actor_stats_and_contract_fields(self):
        bridge = CampusKernelBridge(42)
        task = enter_with_owned_night_task(bridge)
        budget = bridge.snapshot()["player"]["action_budget"].copy()
        started = execute(
            bridge, "START_BATTLE_PREPARATION", {"task_id": task["task_id"]},
            marker="start",
        )
        self.assertTrue(started["ok"], started)
        combat = started["snapshot"]["combat"]
        battle = combat["active_battle"]
        self.assertEqual("setup", battle["phase"])
        self.assertEqual(task["task_id"], battle["situation_id"])
        self.assertEqual([], list(campus_combat_invariant(bridge.kernel.state)))
        player_card = next(
            card for card in battle["character_cards"].values()
            if card["actor_id"] == "player"
        )
        schema = json.loads(
            (REPOSITORY_DIR / "contracts/combat_character_card.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(set(schema["required"]), set(player_card))
        self.assertEqual(92, player_card["max_health"])
        self.assertEqual(77, player_card["max_focus"])
        self.assertEqual(5, len(player_card["command_card_ids"]))
        self.assertIn(player_card["preferred_row"], {"front", "middle", "back"})
        self.assertEqual(budget, started["snapshot"]["player"]["action_budget"])
        player_entries = [
            bridge.kernel._state.chronicles["entries"][entry_id]
            for entry_id in bridge.kernel._state.chronicles["by_actor"]["player"]
        ]
        self.assertTrue(any(
            entry.get("event_type") == "BATTLE_PREPARATION_STARTED"
            and entry.get("category") == "combat"
            and entry.get("parameters", {}).get("battle_id") == battle["battle_id"]
            for entry in player_entries
        ))

    def test_three_people_deploy_free_with_two_per_row_limit_and_player_required(self):
        bridge = CampusKernelBridge(77)
        task = enter_with_owned_night_task(bridge)
        autonomous_ids = set(
            bridge.kernel._state.situations["night_world"]["active_actor_ids"]
        )
        for _ in range(2):
            current_members = set(bridge.kernel._state.parties["party:player"]["member_ids"])
            candidate_id = next(
                actor_id for actor_id, actor in bridge.kernel._state.population.items()
                if actor_id not in autonomous_ids
                and actor_id not in current_members
                and actor.get("night_access") in {"capable", "willing"}
            )
            bridge.kernel._state.relationships.setdefault(candidate_id, {})["player"] = {
                "familiarity": 80, "trust": 90, "closeness": 70, "respect": 70,
                "suspicion": 0, "fear": 0, "obligation": 30, "conflict": 0,
            }
            invited = execute(
                bridge, "INVITE_PARTY_MEMBER", {"target_id": candidate_id},
                marker=f"idle-invite-{candidate_id}",
            )
            self.assertTrue(invited["ok"], invited)
        party_ids = bridge.kernel._state.parties["party:player"]["member_ids"][1:]
        started = execute(
            bridge, "START_BATTLE_PREPARATION", {"task_id": task["task_id"]},
            marker="start-team",
        )
        self.assertTrue(started["ok"], started)
        cards = list(started["snapshot"]["combat"]["active_battle"]["character_cards"].values())
        self.assertEqual(3, len(cards))
        battle_id = started["snapshot"]["combat"]["active_battle"]["battle_id"]
        budget = started["snapshot"]["player"]["action_budget"].copy()

        def deploy(card, row, marker):
            current = bridge.snapshot()["combat"]["active_battle"]
            return execute(bridge, "DEPLOY_COMBAT_CHARACTER", {
                "battle_id": battle_id,
                "expected_battle_revision": current["revision"],
                "character_card_instance_id": card["character_card_instance_id"],
                "destination_row": row,
            }, marker=marker)

        self.assertTrue(deploy(cards[0], "front", "deploy-one")["ok"])
        self.assertTrue(deploy(cards[1], "front", "deploy-two")["ok"])
        blocked = deploy(cards[2], "front", "deploy-overflow")
        self.assertFalse(blocked["ok"])
        self.assertEqual("row_capacity_reached", blocked["result"]["code"])
        self.assertTrue(deploy(cards[2], "middle", "deploy-three")["ok"])
        current = bridge.snapshot()["combat"]["active_battle"]
        self.assertEqual(2, len(current["formations"]["party:player"]["front"]))
        self.assertEqual(1, len(current["formations"]["party:player"]["middle"]))
        self.assertEqual(budget, bridge.snapshot()["player"]["action_budget"])
        self.assertTrue(all(
            bridge.kernel._state.situations["night_world"]["actor_states"][actor_id]["layer"] == "night"
            for actor_id in party_ids
        ))
        self.assertTrue(all(
            bridge.kernel._state.population[actor_id]["current_location_id"]
            == bridge.kernel._state.population["player"]["current_location_id"]
            for actor_id in party_ids
        ))
        self.assertEqual([], list(campus_combat_invariant(bridge.kernel.state)))

    def test_setup_reposition_is_free_and_confirmation_closes_reserves(self):
        bridge = CampusKernelBridge(42)
        task = enter_with_owned_night_task(bridge)
        execute(bridge, "START_BATTLE_PREPARATION", {"task_id": task["task_id"]}, marker="start")
        battle = bridge.snapshot()["combat"]["active_battle"]
        player_card = next(iter(battle["character_cards"].values()))
        missing_player = execute(
            bridge, "CONFIRM_BATTLE_DEPLOYMENT",
            {"battle_id": battle["battle_id"], "expected_battle_revision": battle["revision"]},
            marker="confirm-missing",
        )
        self.assertFalse(missing_player["ok"])
        self.assertEqual("player_must_be_deployed", missing_player["result"]["code"])
        deployed = execute(bridge, "DEPLOY_COMBAT_CHARACTER", {
            "battle_id": battle["battle_id"],
            "expected_battle_revision": battle["revision"],
            "character_card_instance_id": player_card["character_card_instance_id"],
            "destination_row": "back",
        }, marker="deploy-player")
        self.assertTrue(deployed["ok"])
        current = deployed["snapshot"]["combat"]["active_battle"]
        moved = execute(bridge, "REPOSITION_COMBAT_CHARACTER", {
            "battle_id": current["battle_id"],
            "expected_battle_revision": current["revision"],
            "character_card_instance_id": player_card["character_card_instance_id"],
            "destination_row": "middle",
        }, marker="reposition")
        self.assertTrue(moved["ok"])
        move_event = next(
            event for event in moved["result"]["events"]
            if event["event_type"] == "COMBAT_CHARACTER_REPOSITIONED"
        )
        self.assertEqual(0, move_event["payload"]["command_cost"])
        current = moved["snapshot"]["combat"]["active_battle"]
        confirmed = execute(bridge, "CONFIRM_BATTLE_DEPLOYMENT", {
            "battle_id": current["battle_id"],
            "expected_battle_revision": current["revision"],
        }, marker="confirm")
        self.assertTrue(confirmed["ok"], confirmed)
        ready = confirmed["snapshot"]["combat"]["active_battle"]
        self.assertEqual("ready", ready["phase"])
        self.assertEqual([], ready["reserve_character_card_ids"])
        self.assertFalse(confirmed["snapshot"]["combat"]["rules"]["replacement_allowed_after_start"])
        locked = execute(bridge, "REPOSITION_COMBAT_CHARACTER", {
            "battle_id": ready["battle_id"],
            "expected_battle_revision": ready["revision"],
            "character_card_instance_id": player_card["character_card_instance_id"],
            "destination_row": "front",
        }, marker="locked-move")
        self.assertFalse(locked["ok"])
        self.assertEqual("deployment_locked", locked["result"]["code"])

    def test_active_preparation_blocks_exit_task_settlement_and_party_changes(self):
        bridge = CampusKernelBridge(42)
        task = enter_with_owned_night_task(bridge)
        started = execute(
            bridge, "START_BATTLE_PREPARATION", {"task_id": task["task_id"]},
            marker="start-guards",
        )
        self.assertTrue(started["ok"])
        for action_id, parameters, expected_code in (
            ("EXIT_NIGHT_WORLD", {}, "battle_preparation_active"),
            ("ABANDON_FORUM_TASK", {"task_id": task["task_id"]}, "battle_preparation_active"),
            ("COMPLETE_FORUM_TASK", {"task_id": task["task_id"]}, "battle_resolution_required"),
            ("DISBAND_PARTY", {}, "battle_preparation_active"),
        ):
            result = execute(bridge, action_id, parameters, marker=f"guard-{action_id}")
            self.assertFalse(result["ok"], result)
            self.assertEqual(expected_code, result["result"]["code"])

    def test_daylight_interrupts_unfinished_preparation_before_night_exit(self):
        bridge = CampusKernelBridge(42)
        task = enter_with_owned_night_task(bridge)
        execute(
            bridge, "START_BATTLE_PREPARATION", {"task_id": task["task_id"]},
            marker="start-daylight",
        )
        execute(bridge, "ADVANCE_PHASE", marker="to-late-night")
        morning = execute(bridge, "ADVANCE_PHASE", marker="to-morning")
        execution = morning["result"]["payload"]["phase_execution"]
        self.assertEqual(1, execution["battle_preparation_interrupted_count"])
        self.assertIsNone(morning["snapshot"]["combat"]["active_battle"])
        self.assertEqual("surface", morning["snapshot"]["night_world"]["current_layer"])
        self.assertEqual([], list(campus_combat_invariant(bridge.kernel.state)))

    def test_incapacitation_removes_character_and_invalidates_bound_hand_cards(self):
        bridge = CampusKernelBridge(42)
        task = enter_with_owned_night_task(bridge)
        execute(bridge, "START_BATTLE_PREPARATION", {"task_id": task["task_id"]}, marker="start")
        snapshot_battle = bridge.snapshot()["combat"]["active_battle"]
        card_id = next(
            card_id for card_id, card in snapshot_battle["character_cards"].items()
            if card["actor_id"] == "player"
        )
        execute(bridge, "DEPLOY_COMBAT_CHARACTER", {
            "battle_id": snapshot_battle["battle_id"],
            "expected_battle_revision": snapshot_battle["revision"],
            "character_card_instance_id": card_id,
            "destination_row": "front",
        }, marker="deploy-incapacitation")
        snapshot_battle = bridge.snapshot()["combat"]["active_battle"]
        execute(bridge, "CONFIRM_BATTLE_DEPLOYMENT", {
            "battle_id": snapshot_battle["battle_id"],
            "expected_battle_revision": snapshot_battle["revision"],
        }, marker="confirm-incapacitation")
        snapshot_battle = bridge.snapshot()["combat"]["active_battle"]
        execute(bridge, "START_CARD_COMBAT", {
            "battle_id": snapshot_battle["battle_id"],
            "expected_battle_revision": snapshot_battle["revision"],
        }, marker="start-card-incapacitation")
        battle = bridge.kernel._state.battles["battle:000001"]
        card = battle["character_cards"][card_id]
        hand_before = list(battle["shared_hand_ids"])
        self.assertEqual(2, len(hand_before))
        command = SimulationCommand(
            command_id="incapacitate-test", actor_id="player", action_id="TEST",
            expected_world_revision=bridge.kernel._state.revision,
            issued_day=bridge.kernel._state.clock.day,
            issued_phase=bridge.kernel._state.clock.phase,
        )
        context = TransactionContext(bridge.kernel._state, DeterministicRngPool(42), command)
        outcome = incapacitate_character(context, battle, card_id)
        self.assertEqual(card["actor_id"], outcome["actor_id"])
        self.assertEqual("incapacitated", card["deployment_state"])
        self.assertIsNone(card["row"])
        self.assertNotIn(card_id, battle["formations"][card["team_id"]]["front"])
        self.assertEqual([], battle["shared_hand_ids"])
        self.assertEqual(8, len(battle["exhaust_piles"]["player"]))
        self.assertTrue(all(
            instance["zone"] == "exhaust"
            for instance in battle["card_instances"].values()
        ))
        self.assertFalse(True if battle["reserve_character_card_ids"] else False)
        self.assertEqual("COMBAT_CHARACTER_INCAPACITATED", context.event_drafts[-1].event_type)
        self.assertFalse(context.event_drafts[-1].payload["replacement_allowed"])
        self.assertEqual([], list(campus_combat_invariant(bridge.kernel._state)))

    def test_fear_injury_pollution_other_task_and_moral_boundaries_block_npcs(self):
        bridge = CampusKernelBridge(42)
        member_ids = invite_available_members(bridge, 1)
        self.assertEqual(1, len(member_ids))
        target_id = member_ids[0]
        state = bridge.kernel._state
        policy = state.metadata["campus_combat"]["policy"]
        self.assertEqual(80, policy["readiness_limits"]["fear"])
        state.population[target_id]["emotions"]["fear"] = 80
        task = {"task_id": "night:test", "forbidden_boundary_ids": []}
        state.tasks[task["task_id"]] = task
        from simulation.systems import combat_policy_from_state, combat_readiness_assessment
        parsed_policy = combat_policy_from_state(state)
        self.assertEqual(
            "fear_limit",
            combat_readiness_assessment(
                state, "player", target_id, parsed_policy, situation_id=task["task_id"]
            )["reason"],
        )
        state.population[target_id]["emotions"]["fear"] = 0
        state.population[target_id]["injury_severity"] = 75
        self.assertEqual(
            "injury_limit",
            combat_readiness_assessment(
                state, "player", target_id, parsed_policy, situation_id=task["task_id"]
            )["reason"],
        )
        state.population[target_id]["injury_severity"] = 0
        boundary = state.population[target_id]["moral_boundaries"][0]
        state.tasks[task["task_id"]]["forbidden_boundary_ids"] = [boundary]
        self.assertEqual(
            "moral_boundary",
            combat_readiness_assessment(
                state, "player", target_id, parsed_policy, situation_id=task["task_id"]
            )["reason"],
        )


if __name__ == "__main__":
    unittest.main()
