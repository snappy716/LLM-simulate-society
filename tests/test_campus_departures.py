from copy import deepcopy
import unittest
import tempfile
from pathlib import Path

from simulation.api.server import CampusKernelBridge
from simulation.actions import SimulationCommand
from simulation.domain.action_economy import build_action_economy_policy
from simulation.systems.time import consume_major_action
from simulation.systems.campus_departures import active_departure, assess_departure
from simulation.systems.campus_parties import campus_party_invariant, party_policy_from_state
from tests.test_campus_parties import execute, accepted_candidate
from tests.test_campus_combat_rounds import deploy_and_start
from tests.test_campus_combat_deployment import execute as combat_execute
from simulation.persistence.kernel_checkpoint import save_kernel_checkpoint, load_kernel_checkpoint
from simulation.systems.campus_combat import night_combat_entry_cost


class CampusDepartureTests(unittest.TestCase):
    def setUp(self):
        self.bridge = CampusKernelBridge(46)

    def invite(self):
        actor_id = accepted_candidate(self.bridge.snapshot())["actor_id"]
        result = execute(self.bridge, "INVITE_PARTY_MEMBER", {"target_id": actor_id})
        self.assertTrue(result["ok"], result["result"]["code"])
        return actor_id

    def reserve(self, day=1, phase="evening"):
        return combat_execute(self.bridge, "RESERVE_PARTY_DEPARTURE", {"day": day, "phase": phase}, marker=repr((day, phase)))

    def test_reservation_holds_npc_budget_only_in_appointed_phase(self):
        actor_id = self.invite()
        self.assertTrue(self.reserve()["ok"])
        execute(self.bridge, "ADVANCE_PHASE")
        self.assertFalse(active_departure(self.bridge.kernel.state, actor_id))
        execute(self.bridge, "ADVANCE_PHASE")
        state = self.bridge.kernel.state
        self.assertTrue(active_departure(state, actor_id))
        self.assertEqual(1, state.action_economy["actors"][actor_id]["major_remaining"])
        self.assertEqual("departure_reserved", state.population[actor_id]["current_activity"]["block_code"])
        execute(self.bridge, "ADVANCE_PHASE")
        self.assertFalse(active_departure(self.bridge.kernel.state, actor_id))
        self.assertEqual([], list(campus_party_invariant(self.bridge.kernel.state)))

    def test_invalid_and_conflicting_appointments_do_not_replace_existing(self):
        actor_id = self.invite()
        self.assertTrue(self.reserve()["ok"])
        original = deepcopy(self.bridge.kernel.state.parties)
        for day, phase in [(True, "evening"), (0, "evening"), (1, "morning"), (1, [])]:
            result = self.reserve(day, phase)
            self.assertFalse(result["ok"])
            self.assertEqual(original, self.bridge.kernel.state.parties)
        state = self.bridge.kernel._state
        state.population[actor_id]["weekly_schedule"]["1"]["evening"]["priority"] = 100
        result = self.reserve(2)
        self.assertFalse(result["ok"])
        self.assertEqual(original, self.bridge.kernel.state.parties)

    def test_current_spent_action_is_not_refunded(self):
        execute(self.bridge, "ADVANCE_PHASE")
        execute(self.bridge, "ADVANCE_PHASE")
        self.invite()
        before = deepcopy(self.bridge.kernel.state.action_economy)
        self.assertFalse(self.reserve()["ok"])
        self.assertEqual(before, self.bridge.kernel.state.action_economy)

    def test_cancel_releases_hold_without_changing_budget(self):
        self.invite()
        self.reserve()
        execute(self.bridge, "ADVANCE_PHASE")
        execute(self.bridge, "ADVANCE_PHASE")
        before = deepcopy(self.bridge.kernel.state.action_economy)
        result = execute(self.bridge, "CANCEL_PARTY_DEPARTURE")
        self.assertTrue(result["ok"])
        self.assertEqual(before, self.bridge.kernel.state.action_economy)
        self.assertFalse(active_departure(self.bridge.kernel.state, "player"))

    def test_reserved_player_action_cannot_be_spent_by_other_major_activity(self):
        self.reserve()
        execute(self.bridge, "ADVANCE_PHASE")
        execute(self.bridge, "ADVANCE_PHASE")
        state = self.bridge.kernel.state
        policy = build_action_economy_policy([{"id": phase, **rule} for phase, rule in state.action_economy["policy"]["phases"].items()])
        command = SimulationCommand(command_id="reserved-study", actor_id="player", action_id="SELF_STUDY",
                                    expected_world_revision=state.revision, issued_day=1, issued_phase="evening")
        result = consume_major_action(state, policy, command)
        self.assertEqual("major_action_reserved", result.code)
        self.assertEqual(1, state.action_economy["actors"]["player"]["major_remaining"])

    def test_real_three_person_departure_charges_every_deployed_actor(self):
        battle = deploy_and_start(self.bridge, teammate_count=2)
        self.assertEqual(3, len(battle["participant_ids"]))
        state = self.bridge.kernel.state
        for actor_id in battle["participant_ids"]:
            self.assertEqual(0, state.action_economy["actors"][actor_id]["major_remaining"])
            self.assertTrue(state.action_economy["actors"][actor_id]["night_combat_paid"])

    def test_paid_marker_and_reservations_survive_disk_save_then_reset_after_retreat(self):
        battle = deploy_and_start(self.bridge, teammate_count=2)
        state, rng = self.bridge.kernel.capture_checkpoint()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "departure.json"
            save_kernel_checkpoint(path, state, rng)
            loaded = load_kernel_checkpoint(path)
        self.assertEqual(state.parties, loaded.state.parties)
        self.assertEqual(state.action_economy, loaded.state.action_economy)
        assessment = night_combat_entry_cost(loaded.state, battle["participant_ids"])
        self.assertTrue(assessment["allowed"])
        self.assertEqual([], assessment["due_actor_ids"])
        blocked = execute(self.bridge, "ADVANCE_PHASE")
        self.assertFalse(blocked["ok"])
        self.assertEqual("active_combat_blocks_time_advance", blocked["result"]["code"])
        current = self.bridge.snapshot()["combat"]["active_battle"]
        retreated = combat_execute(self.bridge, "RETREAT_CARD_COMBAT", {
            "battle_id": current["battle_id"],
            "expected_battle_revision": current["revision"],
        }, marker="departure-paid-marker-retreat")
        self.assertTrue(retreated["ok"])
        self.assertTrue(execute(self.bridge, "ADVANCE_PHASE")["ok"])
        assessment = night_combat_entry_cost(self.bridge.kernel.state, battle["participant_ids"])
        self.assertEqual(sorted(battle["participant_ids"]), assessment["due_actor_ids"])

    def test_spent_actor_rejects_entry_without_changing_budget_or_formation(self):
        # Exercise real deployment with an injected exhausted-budget boundary.
        from tests.test_campus_combat_deployment import enter_with_owned_night_task
        task = enter_with_owned_night_task(self.bridge)
        prepared = combat_execute(self.bridge, "START_BATTLE_PREPARATION", {"task_id": task["task_id"]})
        battle = prepared["snapshot"]["combat"]["active_battle"]
        card = next(iter(battle["character_cards"].values()))
        for action, extra in [
            ("DEPLOY_COMBAT_CHARACTER", {"character_card_instance_id": card["character_card_instance_id"], "destination_row": "front"}),
            ("CONFIRM_BATTLE_DEPLOYMENT", {}),
        ]:
            battle = self.bridge.snapshot()["combat"]["active_battle"]
            result = combat_execute(self.bridge, action, {"battle_id": battle["battle_id"], "expected_battle_revision": battle["revision"], **extra})
            self.assertTrue(result["ok"])
        self.bridge.kernel._state.action_economy["actors"]["player"]["major_remaining"] = 0
        before = deepcopy(self.bridge.kernel.state.action_economy)
        battle = self.bridge.snapshot()["combat"]["active_battle"]
        result = combat_execute(self.bridge, "START_CARD_COMBAT", {"battle_id": battle["battle_id"], "expected_battle_revision": battle["revision"]})
        self.assertEqual("night_combat_action_exhausted", result["result"]["code"])
        self.assertEqual(before, self.bridge.kernel.state.action_economy)
        self.assertEqual("ready", self.bridge.snapshot()["combat"]["active_battle"]["phase"])

    def test_disband_releases_all_reservations_and_old_records_remain_valid(self):
        self.invite()
        self.reserve()
        self.assertTrue(execute(self.bridge, "DISBAND_PARTY")["ok"])
        self.assertFalse(self.bridge.kernel.state.parties["party:player"]["members"]["player"].get("departure"))
        self.assertEqual([], list(campus_party_invariant(self.bridge.kernel.state)))

    def test_second_real_battle_same_phase_starts_with_zero_remaining_actions(self):
        self.bridge = CampusKernelBridge(42)
        battle = deploy_and_start(self.bridge)
        enemy_id = next(iter(battle["enemy_units"]))
        # Existing one-hit victory fixture shortens combat, not accounting.
        self.bridge.kernel._state.battles[battle["battle_id"]]["enemy_health"][enemy_id] = 1
        won = combat_execute(self.bridge, "PLAY_COMBAT_CARD", {
            "battle_id": battle["battle_id"], "expected_battle_revision": battle["revision"],
            "card_instance_id": battle["shared_hand_ids"][0], "target_ids": [enemy_id],
        })
        self.assertTrue(won["ok"])
        self.assertIsNone(won["snapshot"]["combat"]["active_battle"])
        task = next(t for t in self.bridge.snapshot()["tasks"].values()
                    if t.get("forum") == "night" and t.get("state") in {"open", "viewed", "considering"})
        self.assertTrue(combat_execute(self.bridge, "CLAIM_FORUM_TASK", {
            "task_id": task["task_id"], "expected_task_revision": task["lock_revision"]})["ok"])
        combat_execute(self.bridge, "FAST_TRAVEL_CAMPUS", {"destination_id": task["execution_region_id"]})
        result = combat_execute(self.bridge, "START_BATTLE_PREPARATION", {"task_id": task["task_id"]})
        self.assertTrue(result["ok"], result["result"]["code"])
        battle = result["snapshot"]["combat"]["active_battle"]
        card = next(iter(battle["character_cards"]))
        for action, extra in [
            ("DEPLOY_COMBAT_CHARACTER", {"character_card_instance_id": card, "destination_row": "front"}),
            ("CONFIRM_BATTLE_DEPLOYMENT", {}), ("START_CARD_COMBAT", {}),
        ]:
            battle = self.bridge.snapshot()["combat"]["active_battle"]
            result = combat_execute(self.bridge, action, {"battle_id": battle["battle_id"], "expected_battle_revision": battle["revision"], **extra}, marker="second-" + action)
            self.assertTrue(result["ok"], result["result"]["code"])
        self.assertEqual([], result["result"]["payload"]["entry_action"]["due_actor_ids"])
        self.assertEqual(0, self.bridge.kernel.state.action_economy["actors"]["player"]["major_remaining"])

    def test_nonleader_cannot_replace_or_cancel_appointment(self):
        actor_id = self.invite()
        self.reserve()
        for action in ("RESERVE_PARTY_DEPARTURE", "CANCEL_PARTY_DEPARTURE"):
            result = execute(self.bridge, action, {"day": 2, "phase": "evening"}, actor_id)
            self.assertEqual("not_party_leader", result["result"]["code"])

    def test_existing_task_and_low_willingness_block_booking(self):
        actor_id = self.invite()
        state = self.bridge.kernel.state
        party = state.parties["party:player"]
        state.population[actor_id]["active_forum_task_id"] = "fixture-prior-commitment"
        result = assess_departure(state, party, 1, "evening", party_policy_from_state(state))
        self.assertEqual("task_commitment", result["blocked"][0]["reason"])
        state.population[actor_id].pop("active_forum_task_id")
        state.relationships[actor_id]["player"]["suspicion"] = 100
        state.relationships[actor_id]["player"]["trust"] = 0
        self.assertFalse(assess_departure(state, party, 1, "evening", party_policy_from_state(state))["allowed"])
