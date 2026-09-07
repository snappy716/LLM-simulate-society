"""Consent, real preparation/assembly, shared combat settlement and replay."""
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import tempfile
import unittest

from simulation.actions.commands import SimulationCommand
from simulation.domain.events import SimulationEvent
from simulation.api.server import CampusKernelBridge
from simulation.systems.transactions import TransactionContext
from simulation.systems import load_campus_location_graph
from simulation.systems.campus_parties import party_policy_from_state
from simulation.systems.campus_messaging import load_campus_messaging_policy
from simulation.systems.campus_expeditions import (
    expedition_invariant, finish_expedition, upkeep_expeditions,
    form_npc_expeditions, prepare_npc_combat_supplies, already_fought_this_phase,
)
from simulation.persistence.kernel_checkpoint import save_kernel_checkpoint, load_kernel_checkpoint
from simulation.systems.campus_growth import project_growth_events


class ExpeditionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = CampusKernelBridge(46)
        cls.initial, cls.initial_rng = cls.bridge.kernel.capture_checkpoint()
        cls.events = []
        for index in range(11):
            state = cls.bridge.kernel.state
            result = cls.bridge.kernel.execute(SimulationCommand(f"expedition-natural:{index}", "player", "ADVANCE_PHASE",
                state.revision, issued_day=state.clock.day, issued_phase=state.clock.phase))
            assert result.success, result.code
            cls.events.extend(result.events)
            if index == 9:
                cls.reserved, cls.reserved_rng = cls.bridge.kernel.capture_checkpoint()
        cls.completed, cls.completed_rng = cls.bridge.kernel.capture_checkpoint()
        cls.graph = load_campus_location_graph(cls.bridge.registry)
        cls.messaging = load_campus_messaging_policy(cls.bridge.registry)
        cls.plan_id = next(key for key, plan in cls.completed.cognition["night_expeditions"]["plans"].items()
                           if plan["status"] == "completed" and len(plan["actual_member_ids"]) > 1)

    def setUp(self):
        self.state, self.rng = deepcopy(self.reserved), deepcopy(self.reserved_rng)
        self.plan = self.state.cognition["night_expeditions"]["plans"][self.plan_id]
        self.leader = self.plan["leader_id"]
        self.helper = self.plan["member_ids"][1]

    def context(self):
        return TransactionContext(self.state, self.rng, SimulationCommand("expedition-unit", "player", "ADVANCE_PHASE",
            self.state.revision, issued_day=self.state.clock.day, issued_phase=self.state.clock.phase))

    def form_again(self):
        self.state.parties.pop(self.plan["party_id"], None)
        self.state.cognition["night_expeditions"]["plans"].pop(self.plan_id)
        context = self.context()
        form_npc_expeditions(context, self.graph, party_policy_from_state(self.state),
                             self.bridge.kernel._handlers["INVITE_PARTY_MEMBER"], self.messaging)
        return context

    def test_three_days_naturally_form_and_execute_without_player_or_llm(self):
        plan = self.completed.cognition["night_expeditions"]["plans"][self.plan_id]
        self.assertEqual(3, plan["day"])
        self.assertEqual(plan["member_ids"], plan["actual_member_ids"])
        battle = self.completed.battles[plan["battle_id"]]
        self.assertEqual("victory", battle["result"])
        self.assertNotIn("player", battle["participant_ids"])
        self.assertNotIn(plan["party_id"], self.completed.parties)
        types = {event.event_type for event in self.events}
        self.assertTrue({"PARTY_DEPARTURE_RESERVED", "ACTOR_LOCATION_CHANGED", "COMBAT_CARD_PLAYED",
                         "NPC_EXPEDITION_UPDATED", "NPC_COMBAT_SUPPLY_PREPARED"} <= types)
        self.assertEqual([], expedition_invariant(self.completed))

    def test_only_actual_participants_share_original_reward_and_pay_once(self):
        plan = self.completed.cognition["night_expeditions"]["plans"][self.plan_id]
        total = self.completed.tasks[self.plan_id]["reward"]["wealth"]
        self.assertEqual(total, sum(plan["settled_rewards"].values()))
        for actor in plan["actual_member_ids"]:
            self.assertTrue(already_fought_this_phase(self.completed, actor))
            budget = self.completed.action_economy["actors"][actor]
            self.assertTrue(budget["night_combat_paid"])
            self.assertEqual(0, budget["major_remaining"])
        self.assertFalse(already_fought_this_phase(self.completed, "player"))

    def test_settlement_replay_is_idempotent_and_requires_real_battle(self):
        self.state = deepcopy(self.completed)
        receipt = self.state.tasks[self.plan_id]["execution_receipts"][-1]
        before = deepcopy(self.state)
        finish_expedition(self.context(), self.plan_id, receipt)
        self.assertEqual(before.population, self.state.population)
        self.assertEqual(before.cognition, self.state.cognition)
        with self.assertRaises(ValueError):
            finish_expedition(self.context(), self.plan_id, {**receipt, "battle_id": "invented"})

    def test_npc_can_refuse_and_is_not_forced_into_party(self):
        actor = self.state.population[self.helper]
        actor["needs"].update(safety=100, rest=100, commitment_pressure=100)
        actor["personality"].update(risk_tolerance=0, altruism=0)
        context = self.form_again()
        self.assertTrue(any(event.event_type == "PARTY_INVITATION_DECLINED" and self.helper in event.target_ids
                            for event in context.event_drafts))
        self.assertFalse(any(self.helper in party["member_ids"] for party in self.state.parties.values()))

    def test_protected_duty_blocks_invitation(self):
        self.state.population[self.helper]["weekly_schedule"]["2"]["late_night"]["priority"] = 100
        self.form_again()
        self.assertFalse(any(self.helper in party["member_ids"] for party in self.state.parties.values()))

    def test_expiry_releases_party_without_reward_and_only_once(self):
        self.state.clock.day = 4
        self.state.clock.phase = "morning"
        wealth = {key: actor["wealth"] for key, actor in self.state.population.items()}
        upkeep_expeditions(self.context())
        self.assertEqual("expired", self.plan["status"])
        self.assertNotIn(self.plan["party_id"], self.state.parties)
        self.assertEqual(wealth, {key: actor["wealth"] for key, actor in self.state.population.items()})
        relations = deepcopy(self.state.relationships)
        upkeep_expeditions(self.context())
        self.assertEqual(relations, self.state.relationships)

    def test_changed_task_cancels_without_punishing_helpers(self):
        self.state.tasks[self.plan_id]["state"] = "failed"
        relations = deepcopy(self.state.relationships)
        upkeep_expeditions(self.context())
        self.assertEqual("cancelled", self.plan["status"])
        self.assertEqual(relations, self.state.relationships)
        self.assertNotIn(self.plan["party_id"], self.state.parties)

    def test_actual_shop_purchase_uses_cash_stock_route_and_no_major_action(self):
        self.state, self.rng = deepcopy(self.initial), deepcopy(self.initial_rng)
        self.state.clock.phase = "afternoon"
        before = deepcopy(self.state)
        context = self.context()
        result = prepare_npc_combat_supplies(context, self.graph,
            self.bridge.kernel._handlers["TRAVERSE_LOCATION_PASSAGE"], self.bridge.kernel._handlers["BUY_ITEM"])
        self.assertGreater(result["npc_combat_supply_purchases"], 0)
        self.assertEqual(before.action_economy, self.state.action_economy)
        self.assertEqual(before.population["player"], self.state.population["player"])
        for event in context.event_drafts:
            if event.event_type != "NPC_COMBAT_SUPPLY_PREPARED":
                continue
            actor, item = event.actor_ids[0], event.payload["item_id"]
            self.assertLess(self.state.population[actor]["wealth"], before.population[actor]["wealth"])
            self.assertEqual(before.inventories["actors"][actor]["quantities"].get(item, 0) + 1,
                             self.state.inventories["actors"][actor]["quantities"][item])
        receipts = [event for event in context.event_drafts if event.event_type == "NPC_COMBAT_SUPPLY_PREPARED"]
        for shop_id, item_id in {(event.payload["shop_id"], event.payload["item_id"]) for event in receipts}:
            count = sum(event.payload["shop_id"] == shop_id and event.payload["item_id"] == item_id for event in receipts)
            self.assertEqual(before.inventories["shops"][shop_id]["quantities"][item_id] - count,
                             self.state.inventories["shops"][shop_id]["quantities"][item_id])
        inventories = deepcopy(self.state.inventories)
        prepare_npc_combat_supplies(context, self.graph,
            self.bridge.kernel._handlers["TRAVERSE_LOCATION_PASSAGE"], self.bridge.kernel._handlers["BUY_ITEM"])
        # Previously supplied actors cannot buy duplicate medicine in this phase.
        for event in receipts:
            actor = event.actor_ids[0]
            self.assertEqual(inventories["actors"][actor], self.state.inventories["actors"][actor])

    def test_forged_rewards_and_participants_fail_invariant(self):
        for field, value in (("settled_rewards", {self.leader: 9999}), ("actual_member_ids", [self.leader, "player"]), ("battle_id", "invented")):
            state = deepcopy(self.completed)
            state.cognition["night_expeditions"]["plans"][self.plan_id][field] = value
            self.assertTrue(expedition_invariant(state), field)
        state = deepcopy(self.completed)
        state.cognition["night_expeditions"]["supply_day"]["unknown"] = 0
        self.assertTrue(expedition_invariant(state))

    def run_boundary_battle(self, *, helper_exhausted=False, force_defeat=False):
        # Explicit boundary fixture: actual owned goal/reservation, now due.
        self.state.clock.phase = "late_night"
        actor = self.state.population[self.leader]
        actor["current_location_id"] = self.state.tasks[self.plan_id]["scene_id"]
        actor.pop("current_activity", None)
        actor.pop("current_decision", None)
        for member in self.plan["member_ids"]:
            self.state.action_economy["actors"][member].update(day=3, phase="late_night", major_remaining=1, night_combat_paid=False)
        if helper_exhausted:
            self.state.action_economy["actors"][self.helper].update(major_remaining=0)
        if force_defeat:
            for member in self.plan["member_ids"]:
                self.state.population[member]["vitals"]["health"] = 1
                self.state.inventories["actors"][member]["quantities"].clear()
            for enemy in self.state.metadata["campus_combat"]["enemy_archetypes"].values():
                enemy.update(max_health=10000, speed=1000)
        context = self.context()
        command = SimulationCommand("expedition-boundary", self.leader, "EXECUTE_NPC_NIGHT_TASK", self.state.revision,
            parameters={"task_id": self.plan_id}, source="rule", issued_day=3, issued_phase="late_night")
        result = self.bridge.kernel._handlers["EXECUTE_NPC_NIGHT_TASK"](context, command)
        self.assertTrue(result.success, result.code)
        events = [SimulationEvent(**asdict(draft), event_id=f"boundary:{index}", day=3, phase="late_night",
                  minute=0, world_revision=self.state.revision, command_id=command.command_id)
                  for index, draft in enumerate(context.event_drafts)]
        project_growth_events(self.state, events)
        return self.state.battles[self.plan["battle_id"]]

    def test_unavailable_helper_gets_no_reward_no_combat_charge_or_case(self):
        wealth = self.state.population[self.helper]["wealth"]
        battle = self.run_boundary_battle(helper_exhausted=True)
        self.assertEqual([self.leader], battle["participant_ids"])
        self.assertEqual(wealth, self.state.population[self.helper]["wealth"])
        self.assertNotIn(self.helper, self.plan.get("settled_rewards", {}))
        self.assertFalse(self.state.action_economy["actors"][self.helper]["night_combat_paid"])
        self.assertFalse(already_fought_this_phase(self.state, self.helper))
        cases = self.state.knowledge["growth"]["actors"][self.helper]["case_records"]
        self.assertFalse(any(case.get("battle_id") == battle["battle_id"] for case in cases.values()))
        self.assertTrue(any("未能参战" in entry["message"] for entry in self.plan["history"]))

    def test_cooperative_defeat_does_not_pay_reward_or_advance_player_time(self):
        wealth = {member: self.state.population[member]["wealth"] for member in self.plan["member_ids"]}
        battle = self.run_boundary_battle(force_defeat=True)
        self.assertEqual("defeat", battle["result"])
        self.assertEqual({}, self.plan.get("settled_rewards", {}))
        self.assertEqual(wealth, {member: self.state.population[member]["wealth"] for member in self.plan["member_ids"]})
        self.assertEqual((3, "late_night"), (self.state.clock.day, self.state.clock.phase))
        self.assertNotIn(self.plan["party_id"], self.state.parties)

    def test_checkpoint_replays_real_cooperative_battle_deterministically(self):
        with tempfile.TemporaryDirectory(prefix="campus-expedition-save-") as directory:
            path = Path(directory) / "checkpoint.json"
            save_kernel_checkpoint(path, self.reserved, self.reserved_rng)
            loaded = load_kernel_checkpoint(path)
        self.bridge.kernel.restore_checkpoint(loaded.state, loaded.rng, expected_revision=self.bridge.kernel.state.revision)
        state = self.bridge.kernel.state
        result = self.bridge.kernel.execute(SimulationCommand("expedition-natural:10", "player", "ADVANCE_PHASE",
            state.revision, issued_day=state.clock.day, issued_phase=state.clock.phase))
        self.assertTrue(result.success, result.code)
        after = self.bridge.kernel.state
        self.assertEqual(self.completed.cognition["night_expeditions"], after.cognition["night_expeditions"])
        self.assertEqual(self.completed.battles, after.battles)
        self.assertEqual(self.completed.inventories, after.inventories)

    def test_voluntary_departure_cancellation_releases_expedition_atomically(self):
        self.bridge.kernel.restore_checkpoint(self.reserved, self.reserved_rng, expected_revision=self.bridge.kernel.state.revision)
        before = self.bridge.kernel.state
        result = self.bridge.kernel.execute(SimulationCommand("expedition-cancel", self.leader, "CANCEL_PARTY_DEPARTURE",
            before.revision, source="rule", issued_day=3, issued_phase="evening"))
        self.assertTrue(result.success, result.code)
        after = self.bridge.kernel.state
        self.assertEqual("cancelled", after.cognition["night_expeditions"]["plans"][self.plan_id]["status"])
        self.assertNotIn(self.plan["party_id"], after.parties)
        self.assertEqual(before.action_economy, after.action_economy)


if __name__ == "__main__":
    unittest.main()
