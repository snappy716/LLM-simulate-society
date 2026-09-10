from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from simulation.api.server import CampusKernelBridge
from simulation.systems.campus_life import (assessment, session, ledger, life_invariant, life_candidates, booking_plan)
from simulation.systems.campus_commitments import commitments_at
from simulation.cognition.action_rules import action_rule_context
from simulation.persistence.kernel_checkpoint import save_kernel_checkpoint, load_kernel_checkpoint, CheckpointError
from simulation.systems.transactions import TransactionContext
from tests.test_campus_parties import execute
from tests.test_campus_contact_inquiries import as_npc
from tests.test_campus_combat_deployment import travel_to_location
from tests.test_campus_cognition import LastLegalProvider
from tests.test_campus_disputes import command

ROOT = Path(__file__).resolve().parents[1]


class LifeTests(unittest.TestCase):
    def setUp(self):
        self.bridge = CampusKernelBridge(42)

    @property
    def state(self):
        return self.bridge.kernel._state

    def op(self, action, sid="life:1:campus_walk"):
        return command(self.bridge, action, {"session_id": sid})

    def test_browse_and_enroll_cancel_do_not_pay_or_advance(self):
        before = deepcopy(self.state)
        view = self.bridge.snapshot()["agenda"]["life"]
        # Weekly competitions are not offered on every calendar day.
        expected = [session(self.state, f"life:{day}:{key}") for day in range(1, 4) for key in ledger(self.state)["definitions"]]
        self.assertEqual(sum(row is not None for row in expected), len(view["offers"]))
        self.assertEqual(before.to_dict(), self.state.to_dict())
        self.assertTrue(self.op("ENROLL_CAMPUS_OPPORTUNITY")["ok"])
        self.assertTrue(self.op("ENROLL_CAMPUS_OPPORTUNITY")["ok"])
        self.assertEqual(1, len(ledger(self.state)["records"]["life:1:campus_walk"]["player"]["history"]))
        self.assertTrue(commitments_at(self.state, "player", 1, "afternoon"))
        self.assertTrue(self.op("CANCEL_CAMPUS_OPPORTUNITY")["ok"])
        self.assertEqual([], commitments_at(self.state, "player", 1, "afternoon"))
        for field in ("clock", "population", "action_economy", "inventories"):
            self.assertEqual(getattr(before, field), getattr(self.state, field))

    def test_attend_actual_time_location_cost_effect_and_exactly_once(self):
        self.assertTrue(self.op("ENROLL_CAMPUS_OPPORTUNITY")["ok"])
        self.assertEqual("opportunity_wrong_time", self.op("ATTEND_CAMPUS_OPPORTUNITY")["result"]["code"])
        self.assertTrue(execute(self.bridge, "ADVANCE_PHASE")["ok"])
        self.assertEqual("activity_wrong_location", self.op("ATTEND_CAMPUS_OPPORTUNITY")["result"]["code"])
        travel_to_location(self.bridge, "indoor_sports_hall")
        before = deepcopy((self.state.clock, self.state.action_economy["actors"]["player"], self.state.population["player"]))
        result = self.op("ATTEND_CAMPUS_OPPORTUNITY")
        self.assertTrue(result["ok"], result)
        self.assertEqual(before[0], self.state.clock)
        self.assertEqual(before[1]["major_remaining"] - 1, self.state.action_economy["actors"]["player"]["major_remaining"])
        self.assertGreater(self.state.population["player"]["activity_progress"]["total"], before[2].get("activity_progress", {}).get("total", 0))
        self.assertEqual([], commitments_at(self.state, "player", 1, "afternoon"))
        after = deepcopy(self.state)
        self.assertFalse(self.op("ATTEND_CAMPUS_OPPORTUNITY")["ok"])
        self.assertFalse(self.op("ENROLL_CAMPUS_OPPORTUNITY")["ok"])
        self.assertEqual(after.population, self.state.population)
        self.assertEqual(after.action_economy, self.state.action_economy)
        self.assertEqual("completed", ledger(self.state)["records"]["life:1:campus_walk"]["player"]["status"])

    def test_reservation_blocks_other_major_action_until_cancelled(self):
        self.assertTrue(self.op("ENROLL_CAMPUS_OPPORTUNITY")["ok"])
        self.assertTrue(execute(self.bridge, "ADVANCE_PHASE")["ok"])
        self.assertTrue(action_rule_context(self.state, "player")["own_current_budget"]["reserved_for_existing_commitment"])
        self.assertEqual("major_action_reserved", execute(self.bridge, "PERSONAL_ACTIVITY")["result"]["code"])
        self.assertTrue(self.op("CANCEL_CAMPUS_OPPORTUNITY")["ok"])
        self.assertFalse(action_rule_context(self.state, "player")["own_current_budget"]["reserved_for_existing_commitment"])
        self.assertTrue(execute(self.bridge, "PERSONAL_ACTIVITY")["ok"])
        self.assertEqual("major_action_exhausted", self.op("ENROLL_CAMPUS_OPPORTUNITY")["result"]["code"])

    def test_departure_and_other_opportunity_conflicts_both_directions(self):
        sid = "life:1:reading_exchange"
        self.assertTrue(self.op("ENROLL_CAMPUS_OPPORTUNITY", sid)["ok"])
        self.assertFalse(execute(self.bridge, "RESERVE_PARTY_DEPARTURE", {"day": 1, "phase": "evening"})["ok"])
        self.assertTrue(self.op("CANCEL_CAMPUS_OPPORTUNITY", sid)["ok"])
        self.assertTrue(execute(self.bridge, "RESERVE_PARTY_DEPARTURE", {"day": 1, "phase": "evening"})["ok"])
        self.assertEqual("opportunity_conflict", self.op("ENROLL_CAMPUS_OPPORTUNITY", sid)["result"]["code"])
        self.assertTrue(self.op("ENROLL_CAMPUS_OPPORTUNITY")["ok"])
        self.assertEqual("opportunity_conflict", self.op("ENROLL_CAMPUS_OPPORTUNITY", "life:1:reference_practice")["result"]["code"])

    def test_tools_rechecked_no_invented_materials_and_failure_atomic(self):
        sid = "life:1:reference_practice"
        self.assertTrue(self.op("ENROLL_CAMPUS_OPPORTUNITY", sid)["ok"])
        self.assertTrue(execute(self.bridge, "ADVANCE_PHASE")["ok"])
        travel_to_location(self.bridge, "library_reading_hall")
        # Explicit vanished-tool boundary, not a free item creation workflow.
        self.state.inventories["actors"]["player"]["quantities"].pop("blank_notebook", None)
        before = deepcopy(self.state)
        self.assertEqual("opportunity_materials", self.op("ATTEND_CAMPUS_OPPORTUNITY", sid)["result"]["code"])
        self.assertEqual(before.action_economy, self.state.action_economy)
        self.assertEqual(before.population, self.state.population)
        self.assertEqual(before.inventories, self.state.inventories)
        self.assertTrue(self.op("CANCEL_CAMPUS_OPPORTUNITY", sid)["ok"])

    def test_missed_not_attendance_not_reward(self):
        self.assertTrue(self.op("ENROLL_CAMPUS_OPPORTUNITY")["ok"])
        for _ in range(2): self.assertTrue(execute(self.bridge, "ADVANCE_PHASE")["ok"])
        record = ledger(self.state)["records"]["life:1:campus_walk"]["player"]
        self.assertEqual("missed", record["status"])
        self.assertNotIn("completed_day", record)
        self.assertFalse(self.op("ATTEND_CAMPUS_OPPORTUNITY")["ok"])

    def test_forged_ids_action_or_target_do_not_settle(self):
        for sid in (None, [], "life:01:campus_walk", "life:99:campus_walk", "life:1:invented"):
            self.assertFalse(self.op("ENROLL_CAMPUS_OPPORTUNITY", sid)["ok"])
        self.assertTrue(self.op("ENROLL_CAMPUS_OPPORTUNITY")["ok"])
        self.assertFalse(execute(self.bridge, "SELF_STUDY", {"life_session_id": "life:1:campus_walk"})["ok"])
        self.assertEqual("enrolled", ledger(self.state)["records"]["life:1:campus_walk"]["player"]["status"])

    def test_public_projection_hides_names_and_llm_only_own_slots(self):
        self.assertTrue(self.op("ENROLL_CAMPUS_OPPORTUNITY")["ok"])
        actor = next(n for n,a in self.state.population.items() if n != "player" and a["role_kind"] == "student")
        view = self.bridge.snapshot()["agenda"]["life"]
        self.assertNotIn(actor, str(view))
        self.assertNotIn("life:1:campus_walk", str(action_rule_context(self.state, actor)))
        own = action_rule_context(self.state, "player")
        self.assertIn({"kind": "life", "day": 1, "phase": "afternoon", "major_action_cost": 1}, own["own_confirmed_slots"])
        self.assertNotIn("life:1:campus_walk", str(own))

    def test_three_day_unattended_world_participates_and_records_without_player(self):
        for _ in range(12):
            result = execute(self.bridge, "ADVANCE_PHASE")
            self.assertTrue(result["ok"], result)
        records = ledger(self.state)["records"]
        completed = [(sid, actor) for sid, entries in records.items() for actor,r in entries.items() if r["status"] == "completed"]
        self.assertGreater(len(completed), 0)
        self.assertTrue(all(actor != "player" for _,actor in completed))
        self.assertEqual([], list(life_invariant(self.state)))
        self.assertEqual(0, self.state.cognition["usage"]["calls"])

    def test_personality_changes_candidate_score_not_eligibility(self):
        from simulation.systems.campus_decisions import load_campus_decision_policy
        from simulation.systems.campus_activity_effects import load_campus_activity_definitions
        from simulation.actions.commands import SimulationCommand
        self.state.clock.phase = "evening"  # Read-only candidate fixture only.
        actor = next(n for n,a in self.state.population.items() if n != "player" and a["role_kind"] == "student")
        self.state.population[actor]["weekly_schedule"]["0"]["evening"]["priority"] = 20
        context = TransactionContext(self.state, self.bridge.kernel._rng, SimulationCommand("fixture", "player", "ADVANCE_PHASE", self.state.revision))
        defs = load_campus_activity_definitions(self.bridge.registry)
        policy = load_campus_decision_policy(self.bridge.registry, defs, self.bridge.location_graph)
        scores = []
        for trait in (10, 90):
            self.state.population[actor]["personality"]["extraversion"] = trait
            candidates = life_candidates(context, actor, {"priority": 20}, self.bridge.location_graph, Counter(), policy, 100)
            scores.append(next(c["score"] for c in candidates if c["parameters"]["life_session_id"] == "life:1:reading_exchange"))
        self.assertLess(scores[0], scores[1])

    def test_npc_duties_and_identity_requirements_not_bypassed(self):
        staff = next(n for n,a in self.state.population.items() if a["role_kind"] == "staff")
        self.assertEqual("opportunity_ineligible", as_npc(self.bridge, staff, "ENROLL_CAMPUS_OPPORTUNITY", {"session_id": "life:1:campus_walk"}).code)
        actor = next(n for n,a in self.state.population.items() if n != "player" and a["role_kind"] == "student")
        self.state.population[actor]["weekly_schedule"]["0"]["afternoon"]["priority"] = 95
        self.assertEqual("opportunity_duty", assessment(self.state, actor, session(self.state, "life:1:campus_walk"))[0])

    def test_checkpoint_roundtrip_and_allowlisted_old_save_add_empty_ledger(self):
        self.assertTrue(self.op("ENROLL_CAMPUS_OPPORTUNITY")["ok"])
        state, rng = self.bridge.kernel.capture_checkpoint()
        spec = json.loads((ROOT / "simulation/persistence/campus_life_content.json").read_text())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "save.json"
            save_kernel_checkpoint(path, state, rng, content_manifest=self.bridge.registry.manifest)
            loaded = load_kernel_checkpoint(path, expected_content_version=state.content_version)
            self.assertEqual(json.dumps(state.to_dict(), sort_keys=True), json.dumps(loaded.state.to_dict(), sort_keys=True))
            old = state.clone()
            old.situations.pop("campus_life")
            old.content_version = spec["source_version"]
            save_kernel_checkpoint(path, old, rng, content_manifest=spec["source_manifest"])
            original_bytes = path.read_bytes()
            migrated = load_kernel_checkpoint(path, expected_content_version=spec["target_version"])
            self.assertEqual({}, ledger(migrated.state)["records"])
            self.assertEqual(old.population, migrated.state.population)
            self.assertEqual(old.action_economy, migrated.state.action_economy)
            self.assertEqual(rng.snapshot(), migrated.rng.snapshot())
            self.assertEqual(original_bytes, path.read_bytes())
            self.assertIn(spec["migration_id"], migrated.migrations)

    def test_invalid_ledger_is_rejected(self):
        ledger(self.state)["records"]["invented"] = {"player": {"status": "completed"}}
        self.assertIn("invalid campus life session", list(life_invariant(self.state)))

    def test_model_can_select_opportunities_without_extra_planning_calls(self):
        class ChooseLife(LastLegalProvider):
            def decide(self, request, *, max_output_tokens):
                answer = super().decide(request, max_output_tokens=max_output_tokens)
                if request.daily_options is not None:
                    answer["daily_choices"] = {phase: next((r["candidate_id"] for r in rows
                        if r.get("parameters", {}).get("life_session_id")), rows[-1]["candidate_id"])
                        for phase, rows in request.daily_options.items()}
                return answer
        provider = ChooseLife()
        self.bridge.cognition_runtime.provider = provider
        for _ in range(5): self.assertTrue(execute(self.bridge, "ADVANCE_PHASE")["ok"])
        daily = [r for r in provider.requests if r.daily_options is not None]
        self.assertEqual(20, len(daily))
        self.assertTrue(all(r.phase == "morning" for r in provider.requests))
        selected = [(actor, plan) for actor, slots in self.state.cognition["daily_plans"]["actors"].items()
                    for plan in slots.values() if plan.get("planned_source") == "llm" and plan.get("parameters", {}).get("life_session_id")]
        self.assertTrue(selected)
        finished = [(actor,plan) for actor,plan in selected if
                    ledger(self.state)["records"].get(plan["parameters"]["life_session_id"], {}).get(actor, {}).get("status") == "completed"]
        self.assertTrue(finished)
        self.assertTrue(any(self.state.population[actor]["current_decision"]["decision_source"] == "llm" for actor,_ in finished))

    def test_later_forum_task_does_not_revoke_already_confirmed_attendance(self):
        actor = next(n for n,a in self.state.population.items() if n != "player" and a["role_kind"] == "student")
        self.state.population[actor]["weekly_schedule"]["0"]["afternoon"]["priority"] = 20
        self.assertTrue(as_npc(self.bridge, actor, "ENROLL_CAMPUS_OPPORTUNITY", {"session_id": "life:1:campus_walk"}).success)
        # Only inspect the conflict boundary; no fake task gets executed.
        self.state.population[actor]["active_forum_task_id"] = "fixture:newly-accepted-task"
        self.assertEqual("", assessment(self.state, actor, session(self.state, "life:1:campus_walk"))[0])
        self.assertEqual("opportunity_duty", assessment(self.state, actor, session(self.state, "life:2:campus_walk"))[0])

    def test_duplicate_slot_tampering_rejected(self):
        self.assertTrue(self.op("ENROLL_CAMPUS_OPPORTUNITY")["ok"])
        ledger(self.state)["records"]["life:1:reference_practice"] = deepcopy(ledger(self.state)["records"]["life:1:campus_walk"])
        self.assertIn("duplicate campus life reservation", list(life_invariant(self.state)))

    def test_stale_clock_cannot_enroll_without_spending(self):
        from simulation.actions.commands import SimulationCommand
        before = deepcopy((ledger(self.state), self.state.action_economy))
        result = self.bridge.kernel.execute(SimulationCommand("stale-life", "player", "ENROLL_CAMPUS_OPPORTUNITY", self.state.revision,
            parameters={"session_id": "life:1:campus_walk"}, issued_day=1, issued_phase="evening"))
        self.assertEqual("command_clock_mismatch", result.code)
        self.assertEqual(before, (ledger(self.state), self.state.action_economy))

    def test_cancelled_cached_intent_uses_existing_schedule_without_model_replan(self):
        self.assertTrue(execute(self.bridge, "ADVANCE_PHASE")["ok"])
        enrolled = [(sid, actor) for sid, records in ledger(self.state)["records"].items()
                    for actor,record in records.items() if record["status"] == "enrolled" and session(self.state, sid)["phase"] == "evening"]
        self.assertTrue(enrolled)
        sid, actor = enrolled[0]
        self.assertTrue(as_npc(self.bridge, actor, "CANCEL_CAMPUS_OPPORTUNITY", {"session_id": sid}).success)
        self.assertTrue(execute(self.bridge, "ADVANCE_PHASE")["ok"])
        self.assertEqual("cancelled", ledger(self.state)["records"][sid][actor]["status"])
        self.assertNotEqual(sid, self.state.population[actor]["current_decision"].get("parameters", {}).get("life_session_id"))
        self.assertEqual(0, self.state.cognition["usage"]["calls"])


if __name__ == "__main__": unittest.main()
