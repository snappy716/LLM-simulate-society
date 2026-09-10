from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from simulation.api.server import CampusKernelBridge
from simulation.persistence.kernel_checkpoint import save_kernel_checkpoint, load_kernel_checkpoint, CheckpointError
from simulation.systems.campus_life import assessment, session, ledger, life_invariant
from simulation.systems.campus_study_work import course_progress, study_work_definition_errors
from tests.test_campus_disputes import command
from tests.test_campus_parties import execute
from tests.test_campus_contact_inquiries import as_npc
from tests.test_campus_combat_deployment import travel_to_location
from tests.test_campus_cognition import LastLegalProvider

ROOT = Path(__file__).resolve().parents[1]


class StudyWorkTests(unittest.TestCase):
    def setUp(self):
        self.bridge = CampusKernelBridge(42)

    @property
    def state(self):
        return self.bridge.kernel._state

    def op(self, action, sid):
        return command(self.bridge, action, {"session_id": sid})

    def advance(self, day, phase):
        for _ in range(20):
            if (self.state.clock.day, self.state.clock.phase) == (day, phase):
                return
            result = execute(self.bridge, "ADVANCE_PHASE")
            self.assertTrue(result["ok"], result)
        self.fail("target phase not reached")

    def test_course_three_actual_units_unlock_job_without_case_mastery(self):
        offer = "data_literacy_course"
        self.assertEqual("job_qualification", assessment(self.state, "player", session(self.state, "life:1:market_inventory_part_time"))[0])
        for day in (1, 2, 3):
            sid = f"life:{day}:{offer}"
            self.assertTrue(self.op("ENROLL_CAMPUS_OPPORTUNITY", sid)["ok"])
            self.assertEqual(day - 1, course_progress(self.state, "player", offer)["completed_units"])
            self.advance(day, "afternoon")
            travel_to_location(self.bridge, "science_classroom_pool")
            before = deepcopy(self.state.action_economy["actors"]["player"])
            result = self.op("ATTEND_CAMPUS_OPPORTUNITY", sid)
            self.assertTrue(result["ok"], result)
            receipt = result["result"]["payload"]["effects"]["life"]["course"]
            self.assertEqual(day - 1, receipt["unit_index"])
            self.assertEqual("course:data_literacy", receipt["topic"])
            self.assertEqual(before["major_remaining"] - 1, self.state.action_economy["actors"]["player"]["major_remaining"])
            self.assertFalse(self.op("ATTEND_CAMPUS_OPPORTUNITY", sid)["ok"])
        progress = course_progress(self.state, "player", offer)
        self.assertTrue(progress["complete"])
        self.assertEqual([0, 1, 2], [r["unit_index"] for r in progress["receipts"]])
        self.assertEqual(sum(r["knowledge_gain"] for r in progress["receipts"]), self.state.knowledge["actors"]["player"]["topics"]["course:data_literacy"])
        self.assertEqual("course_complete", self.op("ENROLL_CAMPUS_OPPORTUNITY", "life:4:data_literacy_course")["result"]["code"])
        self.assertTrue(self.op("ENROLL_CAMPUS_OPPORTUNITY", "life:3:market_inventory_part_time")["ok"])
        growth = self.state.knowledge.get("growth", {}).get("actors", {}).get("player", {})
        self.assertFalse(growth.get("case_records"))
        self.assertTrue(all(p["cases"] == 0 and p["application"] == 0 and p["reflection"] == 0 for p in growth.get("topics", {}).values()))
        state, rng = self.bridge.kernel.capture_checkpoint()
        with TemporaryDirectory() as directory:
            path = Path(directory) / "earned.json"
            save_kernel_checkpoint(path, state, rng, content_manifest=self.bridge.registry.manifest)
            loaded = load_kernel_checkpoint(path, expected_content_version=state.content_version)
            self.assertEqual(progress, course_progress(loaded.state, "player", offer))
            self.assertEqual(ledger(state)["records"], ledger(loaded.state)["records"])
            self.assertEqual(rng.snapshot(), loaded.rng.snapshot())

    def test_cancel_and_miss_do_not_earn_units(self):
        sid = "life:1:research_methods_course"
        self.assertTrue(self.op("ENROLL_CAMPUS_OPPORTUNITY", sid)["ok"])
        self.assertTrue(self.op("CANCEL_CAMPUS_OPPORTUNITY", sid)["ok"])
        self.assertTrue(self.op("ENROLL_CAMPUS_OPPORTUNITY", sid)["ok"])
        self.advance(1, "evening")
        self.assertEqual("missed", ledger(self.state)["records"][sid]["player"]["status"])
        self.assertEqual(0, course_progress(self.state, "player", "research_methods_course")["completed_units"])

    def test_wage_is_exact_atomic_transfer_not_generic_work_plus_wage(self):
        sid = "life:1:canteen_part_time"
        before_book = deepcopy((self.state.population, self.state.inventories, self.state.action_economy))
        self.assertTrue(self.op("ENROLL_CAMPUS_OPPORTUNITY", sid)["ok"])
        self.assertEqual(before_book, (self.state.population, self.state.inventories, self.state.action_economy))
        self.advance(1, "evening")
        self.assertEqual("activity_wrong_location", self.op("ATTEND_CAMPUS_OPPORTUNITY", sid)["result"]["code"])
        travel_to_location(self.bridge, "canteen_dining_hall")
        actor_before = self.state.population["player"]["wealth"]
        payer_before = self.state.inventories["shops"]["campus_canteen_counter"]["cash"]
        stock_before = deepcopy(self.state.inventories["shops"]["campus_canteen_counter"]["quantities"])
        result = command(self.bridge, "ATTEND_CAMPUS_OPPORTUNITY", {"session_id": sid, "wage": 999999, "shop_id": "campus_market"})
        self.assertTrue(result["ok"], result)
        self.assertEqual(actor_before + 12, self.state.population["player"]["wealth"])
        self.assertEqual(payer_before - 12, self.state.inventories["shops"]["campus_canteen_counter"]["cash"])
        self.assertEqual(stock_before, self.state.inventories["shops"]["campus_canteen_counter"]["quantities"])
        self.assertEqual(12, result["result"]["payload"]["effects"]["wealth"]["delta"])
        after = deepcopy((self.state.population, self.state.inventories, self.state.action_economy))
        self.assertFalse(self.op("ATTEND_CAMPUS_OPPORTUNITY", sid)["ok"])
        self.assertEqual(after, (self.state.population, self.state.inventories, self.state.action_economy))
        view = self.bridge.snapshot()["agenda"]["life"]
        self.assertNotIn("payer_before", json.dumps(view))
        self.assertNotIn("payer_after", json.dumps(view))
        self.assertEqual(12, next(r for r in view["history"] if r["session_id"] == sid)["result"]["job"]["wage"])
        receipt = ledger(self.state)["records"][sid]["player"]["result"]["job"]
        receipt["payer_after"] += 1  # Explicit forged payment receipt, not a gameplay outcome.
        self.assertIn("invalid wage receipt", list(life_invariant(self.state)))

    def test_cash_loss_after_booking_fails_without_cost_or_unpaid_attendance(self):
        sid = "life:1:canteen_part_time"
        self.assertTrue(self.op("ENROLL_CAMPUS_OPPORTUNITY", sid)["ok"])
        self.advance(1, "evening")
        travel_to_location(self.bridge, "canteen_dining_hall")
        self.state.inventories["shops"]["campus_canteen_counter"]["cash"] = 0  # Explicit depleted-payer boundary.
        before = deepcopy(self.state)
        self.assertEqual("job_funds_unavailable", self.op("ATTEND_CAMPUS_OPPORTUNITY", sid)["result"]["code"])
        for field in ("population", "inventories", "action_economy", "situations", "knowledge"):
            self.assertEqual(getattr(before, field), getattr(self.state, field))
        self.assertTrue(self.op("CANCEL_CAMPUS_OPPORTUNITY", sid)["ok"])

    def test_npcs_compete_for_same_real_job_slots_and_cancel_releases(self):
        sid = "life:1:canteen_part_time"
        row = session(self.state, sid)
        actors = [n for n in self.state.population if n != "player" and not assessment(self.state, n, row)[0]][:3]
        self.assertEqual(3, len(actors))
        for actor in actors[:2]:
            self.assertTrue(as_npc(self.bridge, actor, "ENROLL_CAMPUS_OPPORTUNITY", {"session_id": sid}).success)
        self.assertEqual("job_filled", self.op("ENROLL_CAMPUS_OPPORTUNITY", sid)["result"]["code"])
        self.assertEqual("job_filled", as_npc(self.bridge, actors[2], "ENROLL_CAMPUS_OPPORTUNITY", {"session_id": sid}).code)
        self.assertTrue(as_npc(self.bridge, actors[0], "CANCEL_CAMPUS_OPPORTUNITY", {"session_id": sid}).success)
        self.assertTrue(self.op("ENROLL_CAMPUS_OPPORTUNITY", sid)["ok"])

    def test_auto_night_entry_does_not_override_confirmed_surface_shift(self):
        from simulation.actions.commands import SimulationCommand
        from simulation.systems.campus_night_tasks import _eligible_night_npcs
        from simulation.systems.campus_night_world import night_world_policy_from_state
        from simulation.systems.transactions import TransactionContext
        # Read-only evening projection; formal enroll/cancel stays on the
        # real morning clock and budget. Never grant night access or rewards.
        def probe():
            draft = self.state.clone()
            draft.clock.phase = "evening"
            context = TransactionContext(draft, self.bridge.kernel._rng.clone(),
                SimulationCommand("entry-test", "player", "ADVANCE_PHASE", draft.revision))
            return [n for _,n in _eligible_night_npcs(context, policy)]
        policy = night_world_policy_from_state(self.state)
        sid = "life:1:canteen_part_time"
        eligible = [n for n in probe()
                    if not assessment(self.state, n, session(self.state, sid))[0]]
        self.assertTrue(eligible)
        actor = eligible[0]
        self.assertTrue(as_npc(self.bridge, actor, "ENROLL_CAMPUS_OPPORTUNITY", {"session_id": sid}).success)
        self.assertNotIn(actor, probe())
        self.assertEqual("surface", self.state.situations["night_world"]["actor_states"][actor]["layer"])
        self.assertTrue(as_npc(self.bridge, actor, "CANCEL_CAMPUS_OPPORTUNITY", {"session_id": sid}).success)
        self.assertIn(actor, probe())

    def test_job_qualification_and_malformed_content_rejected(self):
        self.assertEqual("job_qualification", self.op("ENROLL_CAMPUS_OPPORTUNITY", "life:1:market_inventory_part_time")["result"]["code"])
        definitions = deepcopy(ledger(self.state)["definitions"])
        for value in (True, -1, "12"):
            definitions["canteen_part_time"]["job"]["wage"] = value
            self.assertTrue(list(study_work_definition_errors(definitions, self.state.inventories["shops"])))

    def test_unattended_three_days_produces_actual_course_and_work_receipts(self):
        for _ in range(12):
            result = execute(self.bridge, "ADVANCE_PHASE")
            self.assertTrue(result["ok"], result)
        completed = [(sid,n,r) for sid, actors in ledger(self.state)["records"].items() for n,r in actors.items()
                     if r["status"] == "completed" and r.get("result")]
        self.assertTrue(any(r.get("result", {}).get("course") for _,_,r in completed))
        self.assertTrue(any(r.get("result", {}).get("job") for _,_,r in completed))
        self.assertTrue(all(n != "player" for _,n,_ in completed))
        self.assertEqual(0, self.state.cognition["usage"]["calls"])
        self.assertEqual([], list(life_invariant(self.state)))

    def test_fake_model_can_choose_named_course_in_existing_daily_plan(self):
        class StudyProvider(LastLegalProvider):
            def decide(self, request, *, max_output_tokens):
                answer = super().decide(request, max_output_tokens=max_output_tokens)
                if request.daily_options is not None:
                    answer["daily_choices"] = {phase: next((r["candidate_id"] for r in rows
                        if r.get("parameters", {}).get("life_session_id", "").endswith(":research_methods_course")), rows[-1]["candidate_id"])
                        for phase, rows in request.daily_options.items()}
                return answer
        provider = StudyProvider()
        self.bridge.cognition_runtime.provider = provider
        for _ in range(5):
            self.assertTrue(execute(self.bridge, "ADVANCE_PHASE")["ok"])
        daily = [r for r in provider.requests if r.daily_options is not None]
        self.assertEqual(20, len(daily))
        self.assertTrue(all(r.phase == "morning" for r in daily))
        requested = {r.npc_id for r in daily}
        records = ledger(self.state)["records"].get("life:2:research_methods_course", {})
        completed = [n for n,r in records.items() if n in requested and r["status"] == "completed"]
        self.assertTrue(completed)
        self.assertTrue(all(course_progress(self.state, n, "research_methods_course")["completed_units"] >= 1 for n in completed))

    def test_no_unearned_course_or_wage_receipts(self):
        sid = "life:1:research_methods_course"
        self.assertTrue(self.op("ENROLL_CAMPUS_OPPORTUNITY", sid)["ok"])
        ledger(self.state)["records"][sid]["player"]["result"] = {"course": {"unit_index": 0}}
        self.assertIn("unearned study/work receipt", list(life_invariant(self.state)))

    def test_current_roundtrip_and_previous_activity_ledger_preserved(self):
        self.assertTrue(self.op("ENROLL_CAMPUS_OPPORTUNITY", "life:1:campus_walk")["ok"])
        spec = json.loads((ROOT / "simulation/persistence/campus_courses_jobs_content.json").read_text())
        state, rng = self.bridge.kernel.capture_checkpoint()
        with TemporaryDirectory() as directory:
            path = Path(directory) / "save.json"
            save_kernel_checkpoint(path, state, rng, content_manifest=self.bridge.registry.manifest)
            current = load_kernel_checkpoint(path, expected_content_version=state.content_version)
            self.assertEqual(json.dumps(state.to_dict(), sort_keys=True), json.dumps(current.state.to_dict(), sort_keys=True))
            old = state.clone()
            old.content_version = spec["source_version"]
            ledger(old)["definitions"] = deepcopy(spec["source_definitions"])
            save_kernel_checkpoint(path, old, rng, content_manifest=spec["source_manifest"])
            original = path.read_bytes()
            migrated = load_kernel_checkpoint(path, expected_content_version=state.content_version)
            self.assertEqual(ledger(old)["records"], ledger(migrated.state)["records"])
            comparison = migrated.state.clone()
            ledger(comparison)["definitions"] = deepcopy(spec["source_definitions"])
            comparison.content_version = old.content_version
            self.assertEqual(json.dumps(old.to_dict(), sort_keys=True), json.dumps(comparison.to_dict(), sort_keys=True))
            self.assertEqual(rng.snapshot(), migrated.rng.snapshot())
            self.assertEqual(original, path.read_bytes())
            for key in ("research_methods_course", "data_literacy_course"):
                self.assertEqual(0, course_progress(migrated.state, "player", key)["completed_units"])
            self.assertIn(spec["migration_id"], migrated.migrations)
            ledger(old)["definitions"]["reading_exchange"]["name"] = "tampered"
            save_kernel_checkpoint(path, old, rng, content_manifest=spec["source_manifest"])
            with self.assertRaises(CheckpointError):
                load_kernel_checkpoint(path, expected_content_version=state.content_version)


if __name__ == "__main__":
    unittest.main()
