"""Promises are not inventory: real assent, preparation, delivery and expiry."""
from collections import Counter
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import unittest
import tempfile
from simulation.api.server import CampusKernelBridge
from simulation.systems import ContentRegistry, load_campus_activity_definitions, load_campus_decision_policy, load_campus_location_graph
from simulation.systems.campus_assistance import (assistance_invariant, assistance_candidates, assistance_view,
    advance_assistance_requests, advance_assistance_upkeep, advance_assistance_deliveries)
from simulation.systems.campus_messaging import _add_contact, load_campus_messaging_policy
from simulation.systems.campus_trade import acquisition_locked
from simulation.systems.campus_social import relationship_between
from simulation.persistence.kernel_checkpoint import save_kernel_checkpoint, load_kernel_checkpoint


class CampusAssistanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = CampusKernelBridge(46)
        cls.baseline, cls.rng = cls.bridge.kernel.capture_checkpoint()
        cls.registry = ContentRegistry.load_default(Path(__file__).resolve().parents[1] / "content")
        cls.graph = load_campus_location_graph(cls.registry)
        cls.definitions = load_campus_activity_definitions(cls.registry)
        cls.policy = load_campus_decision_policy(cls.registry, cls.definitions, cls.graph)
        cls.messaging = load_campus_messaging_policy(cls.registry)

    def setUp(self):
        self.bridge.kernel.restore_checkpoint(self.baseline, self.rng, expected_revision=self.bridge.kernel.state.revision)
        self.state = self.bridge.kernel._state
        self.requester = next(key for key, actor in self.state.population.items() if actor.get("occupation_id") == "librarian")
        self.helper = next(key for key, actor in self.state.population.items() if actor.get("role_kind") == "student" and key != "player")
        for actor_id in ("player", self.requester, self.helper):
            actor = self.state.population[actor_id]
            actor["current_location_id"] = "south_gate_region"
            actor["needs"].update(rest=0, food=0, safety=0, money=0)
        donor = self.state.population[self.helper]
        donor["wealth"] = 500
        donor["personality"].update(altruism=100, agreeableness=100)
        self.state.inventories["actors"][self.requester]["quantities"].pop("blank_notebook", None)
        self.state.population[self.requester]["wealth"] = 0
        self.sequence = 0

    def act(self, action, actor_id="player", **params):
        self.sequence += 1
        state = self.bridge.kernel.state
        self.last_command = {"command_id": f"assistance-test:{self.sequence}:{state.revision}", "actor_id": actor_id,
            "action_id": action, "parameters": params, "target_ids": [], "source": "player" if actor_id == "player" else "rule",
            "expected_world_revision": state.revision, "issued_day": state.clock.day, "issued_phase": state.clock.phase, "issued_minute": 0}
        return self.bridge.execute(self.last_command)

    def request(self, helper=None, requester=None, item="blank_notebook"):
        result = self.act("REQUEST_MATERIAL_HELP", requester or self.requester, helper_id=helper or self.helper, item_id=item)
        self.assertTrue(result["ok"], result)
        return result["result"]["payload"]["request"]

    def reject(self, code, action, actor_id="player", **params):
        before, rng = self.bridge.kernel.capture_checkpoint()
        result = self.act(action, actor_id, **params)
        self.assertFalse(result["ok"], result)
        self.assertEqual(code, result["result"]["code"])
        after, current = self.bridge.kernel.capture_checkpoint()
        for field in ("population", "inventories", "cognition", "relationships", "action_economy", "clock", "revision"):
            self.assertEqual(getattr(before, field), getattr(after, field), field)
        self.assertEqual(rng.snapshot(), current.snapshot())

    def test_npc_assent_creates_no_goods_or_money_and_no_major_cost(self):
        before = self.bridge.kernel.state
        request = self.request()
        self.assertEqual("accepted", request["status"])
        after = self.bridge.kernel.state
        self.assertEqual(before.inventories, after.inventories)
        self.assertEqual(before.population, after.population)
        self.assertEqual(before.action_economy, after.action_economy)
        self.assertEqual([], assistance_invariant(after))

    def test_npc_can_decline_due_to_financial_pressure_or_suspicion(self):
        self.state.population[self.helper]["wealth"] = 0
        request = self.request()
        self.assertEqual("declined", request["status"])
        self.assertEqual(0, self.bridge.kernel.state.inventories["actors"][self.requester]["quantities"].get("blank_notebook", 0))

    def test_player_is_never_auto_accepted_and_can_explicitly_decline(self):
        request = self.request(helper="player")
        self.assertEqual("pending", request["status"])
        result = self.act("RESPOND_MATERIAL_HELP", request_id=request["request_id"], accepted=False)
        self.assertTrue(result["ok"])
        self.assertEqual("declined", result["result"]["payload"]["request"]["status"])

    def test_same_need_is_atomically_locked_to_one_unresolved_request(self):
        self.request()
        self.reject("request_exists", "REQUEST_MATERIAL_HELP", self.requester, helper_id="player", item_id="blank_notebook")

    def test_no_need_or_unknown_target_is_rejected(self):
        self.reject("no_material_need", "REQUEST_MATERIAL_HELP", helper_id=self.helper, item_id="blank_notebook")
        self.reject("helper_unavailable", "REQUEST_MATERIAL_HELP", self.requester, helper_id="missing", item_id="blank_notebook")
        self.reject("no_material_need", "REQUEST_MATERIAL_HELP", self.requester, helper_id=self.helper, item_id={})

    def test_physical_delivery_conserves_goods_and_awards_trust_only_once(self):
        self.state.inventories["actors"][self.helper]["quantities"]["blank_notebook"] = 2
        request = self.request()
        before = self.bridge.kernel.state
        result = self.act("DELIVER_MATERIAL_HELP", self.helper, request_id=request["request_id"])
        self.assertTrue(result["ok"], result)
        after = self.bridge.kernel.state
        self.assertEqual(1, after.inventories["actors"][self.helper]["quantities"]["blank_notebook"])
        self.assertEqual(1, after.inventories["actors"][self.requester]["quantities"]["blank_notebook"])
        self.assertEqual(before.action_economy, after.action_economy)
        self.assertEqual("fulfilled", after.cognition["material_assistance"]["requests"][request["request_id"]]["status"])
        self.assertTrue(self.bridge.execute(self.last_command)["ok"])
        self.assertEqual(after.inventories, self.bridge.kernel.state.inventories)
        self.assertEqual(after.relationships, self.bridge.kernel.state.relationships)
        self.reject("request_closed", "DELIVER_MATERIAL_HELP", self.helper, request_id=request["request_id"])

    def test_backpack_gift_also_fulfills_without_pressing_special_delivery_button(self):
        request = self.request(helper="player")
        self.assertTrue(self.act("RESPOND_MATERIAL_HELP", request_id=request["request_id"], accepted=True)["ok"])
        result = self.act("GIVE_ITEM", target_id=self.requester, item_id="blank_notebook", quantity=1)
        self.assertTrue(result["ok"], result)
        settled = self.bridge.kernel.state.cognition["material_assistance"]["requests"][request["request_id"]]
        self.assertEqual("fulfilled", settled["status"])
        self.assertTrue(settled["receipt"]["source_event_id"])
        self.reject("request_closed", "DELIVER_MATERIAL_HELP", request_id=request["request_id"])

    def test_accepted_promise_cannot_take_last_personal_or_professional_tool(self):
        request = self.request()
        self.reject("item_protected", "DELIVER_MATERIAL_HELP", self.helper, request_id=request["request_id"])
        self.assertEqual("accepted", self.bridge.kernel.state.cognition["material_assistance"]["requests"][request["request_id"]]["status"])

    def test_doctor_keeps_last_bandage_even_after_accepting_help(self):
        doctor = next(key for key, actor in self.state.population.items() if actor.get("occupation_id") == "medical_staff")
        self.state.population[doctor]["current_location_id"] = "south_gate_region"
        self.state.population[doctor]["wealth"] = 500
        self.state.population[doctor]["personality"].update(altruism=100, agreeableness=100)
        self.state.population[doctor]["needs"].update(food=0, rest=0, safety=0, money=0)
        self.state.population[self.requester]["vitals"]["health"] -= 10
        self.state.inventories["actors"][self.requester]["quantities"].pop("bandage_roll", None)
        self.state.inventories["actors"][doctor]["quantities"]["bandage_roll"] = 1
        request = self.request(helper=doctor, item="bandage_roll")
        self.assertEqual("accepted", request["status"])
        self.reject("item_protected", "DELIVER_MATERIAL_HELP", doctor, request_id=request["request_id"])

    def test_purchased_for_commitment_can_be_delivered_but_normal_flip_is_locked(self):
        request = self.request()
        state = self.bridge.kernel._state
        state.population[self.helper]["current_location_id"] = "supermarket_sales_floor"
        self.assertTrue(self.act("BUY_ITEM", self.helper, shop_id="campus_market", item_id="blank_notebook", quantity=1)["ok"])
        self.assertTrue(acquisition_locked(self.bridge.kernel.state, self.helper, "blank_notebook"))
        state = self.bridge.kernel._state
        state.population[self.requester]["current_location_id"] = "supermarket_sales_floor"
        self.reject("item_protected", "GIVE_ITEM", self.helper, target_id=self.requester, item_id="blank_notebook", quantity=1)
        self.assertTrue(self.act("DELIVER_MATERIAL_HELP", self.helper, request_id=request["request_id"])["ok"])
        self.assertTrue(acquisition_locked(self.bridge.kernel.state, self.requester, "blank_notebook"))

    def test_phone_contact_allows_request_not_remote_delivery(self):
        _add_contact(self.state, self.requester, self.helper)  # Explicit known-contact fixture, no global address book.
        self.state.population[self.helper]["current_location_id"] = "library_reading_hall"
        self.state.inventories["actors"][self.helper]["quantities"]["blank_notebook"] = 2
        request = self.request()
        self.reject("location_mismatch", "DELIVER_MATERIAL_HELP", self.helper, request_id=request["request_id"])
        self.assertTrue(self.bridge.kernel.state.cognition["messaging"]["threads"])

    def test_view_shows_only_participated_promises_and_read_has_no_side_effects(self):
        self.request()
        before = self.bridge.kernel.state.to_dict()
        self.assertEqual([], assistance_view(self.bridge.kernel._state)["requests"])
        self.assertEqual(1, len(assistance_view(self.bridge.kernel._state, self.requester)["requests"]))
        self.assertEqual(before, self.bridge.kernel.state.to_dict())

    def test_other_route_solving_need_cancels_not_fulfills_promise(self):
        request = self.request()
        state = self.bridge.kernel._state
        state.inventories["actors"][self.requester]["quantities"]["blank_notebook"] = 1
        context = SimpleNamespace(state=state, emit=lambda *args, **kwargs: None)
        advance_assistance_upkeep(context)
        self.assertEqual("no_longer_needed", state.cognition["material_assistance"]["requests"][request["request_id"]]["status"])
        self.assertEqual(1, state.inventories["actors"][self.helper]["quantities"]["blank_notebook"])

    def test_expired_assent_changes_trust_and_does_not_create_delivery(self):
        request = self.request()
        state = self.bridge.kernel._state
        relation = relationship_between(state, self.requester, self.helper)
        trust = relation["trust"]
        state.clock = replace(state.clock, day=3)  # Explicit deadline fixture, not a simulated three-day run.
        advance_assistance_upkeep(SimpleNamespace(state=state, emit=lambda *args, **kwargs: None))
        self.assertEqual("expired", state.cognition["material_assistance"]["requests"][request["request_id"]]["status"])
        self.assertEqual(trust - 2, relation["trust"])
        self.assertEqual(0, state.inventories["actors"][self.requester]["quantities"].get("blank_notebook", 0))
        self.assertEqual([], assistance_invariant(state))

    def test_helper_plan_buys_a_spare_not_their_last_reserved_copy(self):
        self.request()
        state = self.bridge.kernel._state
        context = SimpleNamespace(state=state)
        plan = {"priority": 20, "activity_id": "SELF_STUDY", "location_id": "south_gate_region"}
        choices = assistance_candidates(context, self.helper, plan, self.graph, Counter(), self.policy, 40)
        self.assertTrue(choices)
        self.assertEqual("BUY_ITEM", choices[0]["activity_id"])
        self.assertEqual(1, choices[0]["parameters"]["quantity"])
        plan["priority"] = 95
        self.assertEqual([], assistance_candidates(context, self.helper, plan, self.graph, Counter(), self.policy, 40))

    def test_accepted_notebook_promise_prevents_duplicate_autonomous_shopping(self):
        from simulation.systems.campus_trade import make_procurement_selector
        self.request()
        state = self.bridge.kernel._state
        state.population[self.requester]["wealth"] = 100
        context = SimpleNamespace(state=state)
        fallback = {"activity_id": "SELF_STUDY"}
        selector = make_procurement_selector(lambda *args: fallback, self.graph, self.policy.protected_schedule_priority)
        selected = selector(context, self.requester, {"priority": 20}, Counter())
        self.assertEqual(fallback, selected)

    def test_meeting_candidates_use_agreed_venue_not_omniscient_remote_tracking(self):
        self.state.inventories["actors"][self.helper]["quantities"]["blank_notebook"] = 2
        self.request()
        state = self.bridge.kernel._state
        state.population[self.requester]["current_location_id"] = "hospital_clinic"
        context = SimpleNamespace(state=state)
        plan = {"priority": 20, "activity_id": "SELF_STUDY"}
        choices = assistance_candidates(context, self.helper, plan, self.graph, Counter(), self.policy, 40)
        self.assertEqual("library_reading_hall", choices[0]["location_id"])
        self.assertNotEqual(state.population[self.requester]["current_location_id"], choices[0]["location_id"])
        choices = assistance_candidates(context, self.requester, plan, self.graph, Counter(), self.policy, 40)
        self.assertEqual("WAIT_MATERIAL_HELP", choices[0]["activity_id"])

    def test_npc_can_initiate_without_player_and_shared_pair_cooldown_is_recorded(self):
        _add_contact(self.state, self.requester, self.helper)
        relation = relationship_between(self.state, self.requester, self.helper)
        relation.update(trust=100, closeness=100)
        context = SimpleNamespace(state=self.state, command=SimpleNamespace(command_id="autonomous-help"), emit=lambda *args, **kwargs: None)
        result = advance_assistance_requests(context, self.messaging)
        self.assertGreaterEqual(result["material_help_requested"], 1)
        request = next(r for r in self.state.cognition["material_assistance"]["requests"].values() if r["requester_id"] == self.requester)
        self.assertEqual(self.helper, request["helper_id"])
        self.assertEqual("accepted", request["status"])
        self.assertIn("|".join(sorted((self.requester, self.helper))), self.state.cognition["interactions"]["pair_last_phase"])

    def test_autonomous_phase_execution_physically_fulfills_npc_promise(self):
        self.state.inventories["actors"][self.helper]["quantities"]["blank_notebook"] = 2
        _add_contact(self.state, self.requester, self.helper)
        request = self.request()
        for _ in range(7):
            result = self.act("ADVANCE_PHASE")
            self.assertTrue(result["ok"], result)
            current = self.bridge.kernel.state.cognition["material_assistance"]["requests"][request["request_id"]]
            if current["status"] not in {"pending", "accepted"}:
                break
        self.assertEqual("fulfilled", current["status"], current)
        self.assertGreater(current["attempts"], 0)

    def test_spent_major_action_does_not_block_free_delivery_and_player_is_not_controlled(self):
        self.state.inventories["actors"][self.helper]["quantities"]["blank_notebook"] = 2
        request = self.request()
        state = self.bridge.kernel._state
        state.action_economy["actors"][self.helper]["major_remaining"] = 0
        before_budget = deepcopy(state.action_economy)
        context = SimpleNamespace(state=state, command=SimpleNamespace(command_id="after-duty"), emit=lambda *args, **kwargs: None)
        self.assertEqual(1, advance_assistance_deliveries(context, self.messaging)["material_help_delivered"])
        self.assertEqual(before_budget, state.action_economy)
        self.assertEqual("fulfilled", state.cognition["material_assistance"]["requests"][request["request_id"]]["status"])
        self.assertEqual(0, advance_assistance_deliveries(context, self.messaging)["material_help_delivered"])

        # A different explicit requester asks the player. No automatic handover.
        other = next(key for key in state.population if key not in {"player", self.helper, self.requester})
        state.population[other]["current_location_id"] = "south_gate_region"
        state.inventories["actors"][other]["quantities"].pop("blank_notebook", None)
        second = self.request(helper="player", requester=other)
        self.assertTrue(self.act("RESPOND_MATERIAL_HELP", request_id=second["request_id"], accepted=True)["ok"])
        context.state = self.bridge.kernel._state
        self.assertEqual(0, advance_assistance_deliveries(context, self.messaging)["material_help_delivered"])
        self.assertEqual(1, context.state.inventories["actors"]["player"]["quantities"]["blank_notebook"])

    def test_wrong_helper_or_malformed_response_is_atomic(self):
        request = self.request(helper="player")
        self.reject("invalid_response", "RESPOND_MATERIAL_HELP", self.requester, request_id=request["request_id"], accepted=True)
        self.reject("invalid_response", "RESPOND_MATERIAL_HELP", request_id=request["request_id"], accepted="yes")
        self.reject("not_accepted_helper", "DELIVER_MATERIAL_HELP", request_id=request["request_id"])

    def test_malformed_assistance_containers_are_rejected(self):
        for malformed in ([], {"schema_version": 1, "sequence": 0, "requests": []},
                          {"schema_version": 1, "sequence": 1, "requests": {"x": []}}):
            state = deepcopy(self.state)
            state.cognition["material_assistance"] = malformed
            self.assertTrue(assistance_invariant(state))

    def test_checkpoint_preserves_pending_assistance_and_false_receipt_is_invalid(self):
        request = self.request()
        state, rng = self.bridge.kernel.capture_checkpoint()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "assistance.json"
            save_kernel_checkpoint(path, state, rng)
            loaded = load_kernel_checkpoint(path, expected_content_version=state.content_version)
            self.assertEqual(state.cognition["material_assistance"], loaded.state.cognition["material_assistance"])
        state.cognition["material_assistance"]["requests"][request["request_id"]]["status"] = "fulfilled"
        self.assertTrue(assistance_invariant(state))


if __name__ == "__main__":
    unittest.main()
