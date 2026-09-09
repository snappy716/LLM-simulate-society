"""Optional choices, authoritative purchases, and continuation of primary plans."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from simulation.api.server import CampusKernelBridge
from simulation.actions.commands import SimulationCommand
from simulation.domain.cognition import BoundedDecisionResponse
from simulation.systems.campus_free_errands import make_free_errand_executor
from simulation.systems.campus_daily_plans import daily_plans_invariant
from simulation.systems.campus_trade import procurement_candidates
from simulation.systems.campus_inventory import make_campus_inventory_handler, campus_inventory_invariant
from simulation.systems.campus_locations import make_traverse_location_handler
from simulation.systems.campus_schedules import current_schedule_slot
from simulation.systems.randomness import DeterministicRngPool
from simulation.systems.transactions import TransactionContext, WorldKernel, TransactionOutcome
from tests.test_campus_cognition import LastLegalProvider, command


class ChoosingProvider(LastLegalProvider):
    def __init__(self, choices):
        super().__init__()
        self.choices = choices

    def decide(self, request, **kwargs):
        response = super().decide(request, **kwargs)
        response["free_choices"] = self.choices(request)
        return response


class FreeErrandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = CampusKernelBridge(42)
        cls.baseline = cls.bridge.kernel.state

    def setUp(self):
        self.state = self.baseline.clone()
        self.actor_id = self.state.cognition["focused_ids"][0]
        self.actor = self.state.population[self.actor_id]
        self.actor["current_location_id"] = "supermarket_sales_floor"
        self.actor["needs"]["food"] = 80
        self.actor["wealth"] = 500
        self.state.inventories["actors"][self.actor_id]["quantities"].pop("bread_loaf", None)
        self.errand = next(c for c in procurement_candidates(self.state, self.actor_id, self.bridge.location_graph)
            if c["parameters"]["item_id"] == "bread_loaf")
        self.slot = {**current_schedule_slot(self.state, self.actor_id), "planned_source": "llm",
            "free_errands": [deepcopy(self.errand)]}
        self.state.cognition["daily_plans"] = {"day": 1, "actors": {self.actor_id: {"morning": self.slot}}}
        self.request = SimulationCommand("errand-test", "player", "ADVANCE_PHASE", self.state.revision)
        self.context = TransactionContext(self.state, DeterministicRngPool(42), self.request)
        self.execute = make_free_errand_executor(self.bridge.location_graph,
            make_traverse_location_handler(self.bridge.location_graph), make_campus_inventory_handler(), 80)

    def run_errands(self):
        return self.execute(self.context, self.actor_id, {"priority": 90}, self.request)

    def test_candidates_are_read_only_and_show_actual_limits(self):
        before = self.state.to_dict()
        options = procurement_candidates(self.state, self.actor_id, self.bridge.location_graph)
        self.assertEqual(before, self.state.to_dict())
        self.assertTrue(options)
        for option in options:
            self.assertEqual("free", option["action_class"])
            self.assertLessEqual(option["max_unit_price"] * option["parameters"]["quantity"], 500)

    def test_purchase_keeps_budget_clock_primary_and_authorized_quantity(self):
        self.slot["free_errands"][0]["parameters"]["quantity"] = 1
        before = deepcopy((self.state.clock, self.state.action_economy, self.slot))
        counts = self.run_errands()
        self.assertEqual(1, counts["free_errand_count"])
        self.assertEqual(before, (self.state.clock, self.state.action_economy, self.slot))
        self.assertEqual(496, self.actor["wealth"])
        self.assertEqual(1, self.state.inventories["actors"][self.actor_id]["quantities"]["bread_loaf"])
        self.assertEqual([], list(campus_inventory_invariant(self.state)))
        self.assertNotIn("current_activity", self.actor)

    def test_omitted_empty_and_legacy_model_plan_do_not_force_shopping(self):
        for value in ([], None):
            if value is None:
                self.slot.pop("free_errands", None)
            else:
                self.slot["free_errands"] = value
            self.assertEqual(0, self.run_errands()["free_errand_count"])
        self.assertEqual(500, self.actor["wealth"])

    def test_changed_conditions_do_not_buy_alternative(self):
        original = deepcopy(self.state.inventories["shops"])
        for cause in ("stock", "money", "price", "need", "closed"):
            with self.subTest(cause=cause):
                self.state.inventories["shops"] = deepcopy(original)
                self.actor["wealth"], self.actor["needs"]["food"] = 500, 80
                self.state.inventories["catalog"]["bread_loaf"]["base_price"] = 4
                self.state.places["supermarket_sales_floor"]["open_phases"] = ["morning", "afternoon", "evening"]
                if cause == "stock":
                    self.state.inventories["shops"]["campus_market"]["quantities"]["bread_loaf"] = 0
                elif cause == "money":
                    self.actor["wealth"] = 0
                elif cause == "price":
                    self.state.inventories["catalog"]["bread_loaf"]["base_price"] = 5
                elif cause == "need":
                    self.actor["needs"]["food"] = 0
                else:
                    self.state.places["supermarket_sales_floor"]["open_phases"] = []
                before = deepcopy(self.state.inventories["actors"])
                counts = self.run_errands()
                self.assertEqual(0, counts["free_errand_count"])
                self.assertEqual(1, counts["free_errand_failed_count"])
                self.assertEqual(before, self.state.inventories["actors"])

    def test_lower_stock_reduces_quantity_and_repeat_rechecks_need(self):
        self.state.inventories["shops"]["campus_market"]["quantities"]["bread_loaf"] = 1
        self.slot["free_errands"].append(deepcopy(self.errand))
        counts = self.run_errands()
        self.assertEqual(1, counts["free_errand_count"])
        self.assertEqual(1, counts["free_errand_failed_count"])
        self.assertEqual(496, self.actor["wealth"])

    def test_reserved_commitment_skips_errands(self):
        with patch("simulation.systems.campus_anomaly_meetings.reserved_meeting", return_value=True):
            self.assertEqual(0, self.run_errands()["free_errand_count"])
        self.assertEqual(500, self.actor["wealth"])

    def test_unreachable_errand_does_not_move_or_spend(self):
        before = (self.actor["current_location_id"], self.actor["wealth"])
        with patch.object(type(self.bridge.location_graph), "shortest_route", return_value=None):
            counts = self.run_errands()
        self.assertEqual(1, counts["free_errand_failed_count"])
        self.assertEqual(before, (self.actor["current_location_id"], self.actor["wealth"]))

    def test_command_replay_and_checkpoint_preserve_optional_intentions(self):
        from simulation.persistence.kernel_checkpoint import build_kernel_checkpoint
        kernel = WorldKernel(self.state, rng=DeterministicRngPool(42))
        def action(context, request):
            counts = self.execute(context, self.actor_id, {}, request)
            return TransactionOutcome(True, True, "ok", "done", commit=True, payload=counts)
        kernel.register_handler("ADVANCE_PHASE", action)
        result = kernel.execute(self.request)
        self.assertTrue(result.success)
        checkpoint = build_kernel_checkpoint(*kernel.capture_checkpoint())
        again = kernel.execute(self.request)
        self.assertTrue(again.replayed)
        self.assertEqual(result.events, again.events)
        self.assertEqual(checkpoint, build_kernel_checkpoint(*kernel.capture_checkpoint()))
        self.assertEqual(self.slot, kernel.state.cognition["daily_plans"]["actors"][self.actor_id]["morning"])

    def test_invalid_persisted_errand_is_rejected(self):
        ledger = self.state.cognition["daily_plans"]
        ledger.update(schema_version=1)
        ledger["actors"][self.actor_id] = {p: dict(deepcopy(self.slot), day=1, phase=p)
            for p in ("morning", "afternoon", "evening", "late_night")}
        self.assertEqual([], list(daily_plans_invariant(self.state)))
        for invalid in ({"quantity": True}, {"shop_id": []}, {"item_id": "imaginary"}):
            slot = ledger["actors"][self.actor_id]["morning"]
            slot["free_errands"] = [deepcopy(self.errand)]
            slot["free_errands"][0]["parameters"].update(invalid)
            self.assertIn("invalid daily free errand", list(daily_plans_invariant(self.state)))

    def test_bad_response_shape_or_duplicate_is_rejected(self):
        for choices in (["a"], {"morning": "a"}, {"morning": ["a", "a"]}, {"morning": [{}]}):
            with self.assertRaises(ValueError):
                BoundedDecisionResponse.from_mapping({"npc_id": self.actor_id, "candidate_revision": 1,
                    "selected_action_id": None, "reason": "test", "free_choices": choices})

    def plan(self, choices):
        runtime = self.bridge.cognition_runtime
        runtime.provider = ChoosingProvider(choices)
        phases = ("morning", "afternoon", "evening", "late_night")
        options = {phase: [dict(self.slot, phase=phase)] for phase in phases}
        return runtime.plan_day(self.state, self.actor_id, options,
            free_options={phase: [deepcopy(self.errand)] for phase in phases})

    def test_model_selection_is_detached_and_opt_out_is_preserved(self):
        plans = self.plan(lambda r: {"morning": ["free:morning:0"]})
        self.assertEqual(self.errand["parameters"], plans["morning"]["free_errands"][0]["parameters"])
        self.assertEqual([], plans["afternoon"]["free_errands"])
        plans["morning"]["free_errands"][0]["parameters"]["quantity"] = 999
        self.assertNotEqual(999, self.errand["parameters"]["quantity"])

    def test_model_wrong_phase_or_invented_candidate_cannot_execute(self):
        for choices in ({"tomorrow": []}, {"morning": ["free:afternoon:0"]}, {"morning": ["invented"]}):
            with self.subTest(choices=choices):
                self.state.cognition["decision_cache"].clear()
                self.assertIsNone(self.plan(lambda r: choices))

    def test_full_phase_purchase_precedes_primary_and_chronicle_keeps_both(self):
        bridge = CampusKernelBridge(42)
        state = bridge.kernel._state
        # Bootstrap at a real prior phase, then explicitly select an afternoon
        # purchase in the cached model intention. This is not paid-model evidence.
        self.assertTrue(command(bridge, "ADVANCE_PHASE")["ok"])
        state = bridge.kernel._state
        who = self.actor_id
        actor = state.population[who]
        actor["needs"]["food"] = 80
        actor["wealth"] = 500
        state.inventories["actors"][who]["quantities"].pop("bread_loaf", None)
        state.clock.phase = "morning"
        slot = state.cognition["daily_plans"]["actors"][who]["afternoon"]
        selected = (slot["activity_id"], slot["location_id"])
        state.clock.phase = "afternoon"
        errand = next(c for c in procurement_candidates(state, who, bridge.location_graph)
            if c["parameters"]["item_id"] == "bread_loaf")
        state.clock.phase = "morning"
        slot.update(planned_source="llm", free_errands=[errand])
        result = command(bridge, "ADVANCE_PHASE")
        self.assertTrue(result["ok"], result)
        state = bridge.kernel.state
        own = [e for e in result["result"]["events"] if who in e["actor_ids"]]
        types = [e["event_type"] for e in own]
        self.assertIn("NPC_FREE_ERRAND_COMPLETED", types)
        self.assertLess(types.index("NPC_FREE_ERRAND_COMPLETED"), types.index("NPC_ACTIVITY_COMPLETED"))
        actual = state.population[who]["current_activity"]
        self.assertEqual(selected, (actual["activity_id"], actual["location_id"]))
        self.assertEqual(0, state.action_economy["actors"][who]["major_remaining"])
        entries = [state.chronicles["entries"][key] for key in state.chronicles["by_actor"][who]]
        self.assertTrue(any(e["event_type"] == "NPC_FREE_ERRAND_COMPLETED" for e in entries))
        self.assertEqual([], list(daily_plans_invariant(state)))


if __name__ == "__main__":
    unittest.main()
