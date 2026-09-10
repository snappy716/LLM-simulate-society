"""Clinic integration fixtures; no external model or real medical claims."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from simulation.api.server import CampusKernelBridge
from simulation.systems.campus_medical import ACTION, LOCATION, SHOP, SUPPLIES, ledger, price, medical_view, medical_invariant
from tests.test_campus_contact_inquiries import as_npc
from tests.test_campus_disputes import command


class MedicalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = CampusKernelBridge(42)
        cls.initial, cls.rng = cls.bridge.kernel.capture_checkpoint()
        cls.provider = cls.bridge.cognition_runtime.provider

    def setUp(self):
        self.bridge.kernel.restore_checkpoint(self.initial, self.rng, expected_revision=self.bridge.kernel.state.revision)
        self.bridge.cognition_runtime.provider = self.provider
        self.staff = next(who for who, p in self.state.population.items() if p.get("occupation_id") == "medical_staff")

    @property
    def state(self):
        return self.bridge.kernel._state

    def prepare(self, actor="player"):
        self.state.population[actor]["current_location_id"] = LOCATION
        self.state.population[actor]["wealth"] = 500
        vitals = self.state.population[actor]["vitals"]
        vitals.update(health=1, focus=1)
        self.state.population[self.staff]["current_location_id"] = LOCATION
        result = as_npc(self.bridge, self.staff, "MEDICAL_SHIFT", {})
        self.assertTrue(result.success, result)

    def visit(self, **parameters):
        return command(self.bridge, ACTION, parameters)["result"]

    def test_actual_shift_cash_stock_healing_and_no_patient_action_cost(self):
        self.prepare()
        patient = deepcopy(self.state.population["player"])
        stock = deepcopy(self.state.inventories["shops"][SHOP])
        budget = deepcopy(self.state.action_economy)
        result = self.visit()
        self.assertTrue(result["success"], result)
        actual = self.state.population["player"]
        self.assertEqual(patient["wealth"] - price(self.state), actual["wealth"])
        self.assertEqual(stock["cash"] + price(self.state), self.state.inventories["shops"][SHOP]["cash"])
        for item, quantity in SUPPLIES.items():
            self.assertEqual(stock["quantities"][item] - quantity, self.state.inventories["shops"][SHOP]["quantities"][item])
        self.assertEqual(1 + actual["vitals"]["max_health"] // 2, actual["vitals"]["health"])
        self.assertEqual(1, actual["vitals"]["focus"])
        self.assertEqual(budget, self.state.action_economy)
        self.assertEqual([], medical_invariant(self.state))
        before = self.state.clone()
        self.assertEqual("clinic_already_treated", self.visit()["code"])
        self.assertEqual(before.inventories, self.state.inventories)
        self.assertEqual(before.situations, self.state.situations)

    def test_no_staff_wrong_location_funds_and_stock_fail_without_mutation(self):
        self.state.population["player"]["vitals"]["health"] = 1
        self.assertEqual("clinic_arrival_required", self.visit()["code"])
        self.state.population["player"]["current_location_id"] = LOCATION
        self.state.population["player"]["wealth"] = 500
        self.assertEqual("clinic_no_staff", self.visit()["code"])
        self.prepare()
        for change, expected in (("funds", "insufficient_funds"), ("stock", "clinic_supply_shortage")):
            with self.subTest(change=change):
                self.state.population["player"]["wealth"] = 0 if change == "funds" else 500
                self.state.inventories["shops"][SHOP]["quantities"]["bandage_roll"] = 0 if change == "stock" else 5
                before = deepcopy((self.state.population, self.state.inventories, self.state.situations, self.state.action_economy))
                self.assertEqual(expected, self.visit()["code"])
                self.assertEqual(before, (self.state.population, self.state.inventories, self.state.situations, self.state.action_economy))

    def test_capacity_real_staff_location_and_patient_privacy(self):
        self.prepare()
        people = [who for who in self.state.population if who not in ("player", self.staff)][:5]
        for who in people[:4]:
            self.state.population[who]["current_location_id"] = LOCATION
            self.state.population[who]["vitals"]["health"] = 1
            self.state.population[who]["wealth"] = 500
            self.assertTrue(as_npc(self.bridge, who, ACTION, {}).success)
        self.assertEqual("clinic_no_staff", self.visit()["code"])
        self.assertEqual([], medical_view(self.state)["receipts"])
        self.assertEqual(1, len(medical_view(self.state, people[0])["receipts"]))
        self.assertNotIn(next(iter(ledger(self.state)["receipts"])), str(self.bridge.snapshot()))
        self.assertEqual([], medical_invariant(self.state))

    def test_no_fake_medical_shift_or_parameter_override(self):
        self.prepare()
        self.assertEqual("medical_shift_unavailable", command(self.bridge, "MEDICAL_SHIFT", {})["result"]["code"])
        self.assertEqual("invalid_clinic_request", self.visit(target_id=self.staff)["code"])
        self.state.population[self.staff]["current_location_id"] = "south_gate"
        self.assertEqual("clinic_no_staff", self.visit()["code"])

    def test_full_health_is_not_diagnosed_from_focus_or_stress(self):
        self.prepare()
        vitals = self.state.population["player"]["vitals"]
        vitals["health"] = vitals["max_health"]
        self.state.population["player"]["needs"]["safety"] = 100
        self.assertEqual("clinic_no_injury", self.visit()["code"])
        self.assertFalse(ledger(self.state)["receipts"])

    def test_optional_old_ledger_and_tampered_capacity(self):
        self.assertEqual([], medical_invariant(self.state))
        self.prepare()
        row = next(iter(ledger(self.state)["shifts"].values()))
        row["used"] = 1
        self.assertTrue(medical_invariant(self.state))

    def test_bad_saved_ledger_is_rejected_without_crashing(self):
        self.prepare()
        self.assertTrue(self.visit()["success"])
        initial = deepcopy(ledger(self.state))
        for category, field, value in (("shifts", "staff_id", []), ("shifts", "day", True),
                ("receipts", "patient_id", []), ("receipts", "shift_id", []),
                ("receipts", "health", []), ("receipts", "source_command_id", {})):
            self.state.situations["campus_medical"] = deepcopy(initial)
            row = next(iter(ledger(self.state)[category].values()))
            row[field] = value
            self.assertTrue(medical_invariant(self.state), (category, field))

    def test_real_phase_execution_supplies_clinic_and_keeps_normal_staff_budget(self):
        result = command(self.bridge, "ADVANCE_PHASE", {})
        self.assertTrue(result["ok"], result)
        from simulation.systems.campus_medical import ready_shifts
        ready = ready_shifts(self.state)
        self.assertTrue(ready)
        for row in ready:
            person = self.state.population[row["staff_id"]]
            self.assertEqual(LOCATION, person["current_location_id"])
            self.assertEqual("completed", person["current_activity"]["status"])
            self.assertEqual(0, self.state.action_economy["actors"][row["staff_id"]]["major_remaining"])

    def test_checkpoint_replay_no_second_charge_and_previous_shift_expiry(self):
        from simulation.persistence.kernel_checkpoint import save_kernel_checkpoint, load_kernel_checkpoint
        from simulation.actions.commands import SimulationCommand
        self.prepare()
        request = SimulationCommand("medical-idempotent", "player", ACTION, self.state.revision,
            issued_day=self.state.clock.day, issued_phase=self.state.clock.phase, source="player")
        self.assertTrue(self.bridge.kernel.execute(request).success)
        before = deepcopy((self.state.inventories, ledger(self.state), self.state.population["player"]))
        with TemporaryDirectory() as directory:
            path = Path(directory) / "checkpoint.json"
            save_kernel_checkpoint(path, *self.bridge.kernel.capture_checkpoint(), content_manifest=self.bridge.registry.manifest)
            loaded = load_kernel_checkpoint(path, expected_content_version=self.state.content_version)
            self.bridge.kernel.restore_checkpoint(loaded.state, loaded.rng, expected_revision=self.state.revision)
            self.assertEqual(before, (self.state.inventories, ledger(self.state), self.state.population["player"]))
        self.assertTrue(self.bridge.kernel.execute(request).success)
        self.assertEqual(before, (self.state.inventories, ledger(self.state), self.state.population["player"]))
        self.state.clock.phase = "afternoon"
        self.assertEqual(0, medical_view(self.state)["available_visits"])

    def test_whole_phase_clinic_errand_then_actual_primary_and_three_day_capacity(self):
        from simulation.systems.campus_medical import clinic_candidates
        self.assertTrue(command(self.bridge, "ADVANCE_PHASE", {})["ok"])
        actor = next(who for who in self.state.cognition["focused_ids"] if "student" in who)
        person = self.state.population[actor]
        person["vitals"]["health"] = 1
        person["wealth"] = 500
        person["current_location_id"] = "campus_hospital"
        slot = self.state.cognition["daily_plans"]["actors"][actor]["evening"]
        slot.update(activity_id="SELF_STUDY", location_id="library_reading_hall", action_class="major",
                    planned_source="llm", decision_source="llm", parameters={})
        # Explicit intention fixture, with unchanged real NPC arrival/execution.
        preview = self.state.clone()
        preview.clock.phase = "evening"
        slot["free_errands"] = clinic_candidates(preview, actor, self.bridge.location_graph)
        self.assertTrue(slot["free_errands"])
        self.assertTrue(command(self.bridge, "ADVANCE_PHASE", {})["ok"])
        person = self.state.population[actor]
        self.assertEqual("SELF_STUDY", person["current_activity"]["activity_id"])
        self.assertEqual("completed", person["current_activity"]["status"])
        self.assertEqual("library_reading_hall", person["current_location_id"])
        self.assertEqual(1, len(medical_view(self.state, actor)["receipts"]))
        self.assertEqual(0, self.state.action_economy["actors"][actor]["major_remaining"])
        for _ in range(10):
            self.assertTrue(command(self.bridge, "ADVANCE_PHASE", {})["ok"])
            self.assertEqual([], medical_invariant(self.state))
        self.assertGreaterEqual(self.state.clock.day, 4)

    def test_model_can_choose_care_or_opt_out_without_new_daytime_calls(self):
        from tests.test_campus_free_errands import ChoosingProvider
        from simulation.systems.campus_medical import clinic_candidates
        from simulation.systems.campus_free_errands import make_free_errand_executor
        from simulation.systems.campus_inventory import make_campus_inventory_handler
        from simulation.systems.campus_locations import make_traverse_location_handler
        from simulation.systems.transactions import TransactionContext
        from simulation.actions.commands import SimulationCommand
        actor = self.state.cognition["focused_ids"][0]
        self.prepare(actor)
        candidate = clinic_candidates(self.state, actor, self.bridge.location_graph)[0]
        self.state.population[actor]["current_location_id"] = "campus_hospital"
        slot = {"activity_id": "SELF_STUDY", "action_class": "major", "location_id": "library_reading_hall",
                "decision_reason": "study", "priority": 20}
        options = {phase: [slot] for phase in ("morning", "afternoon", "evening", "late_night")}
        free = {phase: [candidate] for phase in options}
        runtime = self.bridge.cognition_runtime
        runtime.provider = ChoosingProvider(lambda request: {"morning": [request.free_options["morning"][0]["candidate_id"]]})
        plan = runtime.plan_day(self.state, actor, options, free_options=free)
        self.assertIsNotNone(plan)
        self.assertEqual(ACTION, plan["morning"]["free_errands"][0]["activity_id"])
        plan["morning"]["planned_source"] = "llm"
        self.state.cognition["daily_plans"] = {"day": self.state.clock.day, "actors": {actor: plan}}
        command_ = SimulationCommand("medical-errand", "player", "ADVANCE_PHASE", self.state.revision)
        context = TransactionContext(self.state, self.rng.clone(), command_)
        execute = make_free_errand_executor(self.bridge.location_graph, make_traverse_location_handler(self.bridge.location_graph), make_campus_inventory_handler(), 80)
        budget, original = deepcopy(self.state.action_economy), deepcopy(plan["morning"])
        counts = execute(context, actor, slot, command_)
        self.assertEqual(1, counts["free_errand_count"])
        self.assertGreater(counts["free_errand_route_steps"], 0)
        self.assertEqual(budget, self.state.action_economy)
        self.assertEqual(original, plan["morning"])
        self.assertEqual(LOCATION, self.state.population[actor]["current_location_id"])
        # An explicit empty plan never causes rule-selected healthcare.
        plan["morning"]["free_errands"] = []
        self.assertEqual(0, execute(context, actor, slot, command_)["free_errand_count"])

    def test_rules_respect_economic_pressure_risk_and_candidates_do_not_peek_staff_plans(self):
        from simulation.systems.campus_medical import clinic_candidates, optional_errand_candidates
        self.state.population["player"]["vitals"]["health"] = 1
        self.state.population["player"]["wealth"] = 500
        original = self.state.to_dict()
        candidates = clinic_candidates(self.state, "player", self.bridge.location_graph)
        self.assertTrue(candidates)  # Public conditional service, even before staff has arrived.
        self.assertEqual(original, self.state.to_dict())
        self.assertNotIn(self.staff, str(candidates))
        self.state.population["player"]["personality"]["risk_tolerance"] = 0
        self.assertEqual(ACTION, optional_errand_candidates(self.state, "player", self.bridge.location_graph, rule_choice=True)[0]["activity_id"])
        for wealth, risk in ((price(self.state), 0), (500, 100)):
            self.state.population["player"]["wealth"] = wealth
            self.state.population["player"]["personality"]["risk_tolerance"] = risk
            self.assertFalse(any(c["activity_id"] == ACTION for c in optional_errand_candidates(self.state, "player", self.bridge.location_graph, rule_choice=True)))


if __name__ == "__main__":
    unittest.main()
