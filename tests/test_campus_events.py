"""Boundary contracts use explicit fixtures; natural multi-day evidence is separate."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from simulation.actions.commands import SimulationCommand
from simulation.api.server import CampusKernelBridge
from simulation.systems.campus_events import (event_board, event_options, event_view, finalize_events,
    performance_inputs, event_definition_errors, event_motivation, own_event_context)
from simulation.systems.campus_life import ledger, session, assessment, life_invariant
from simulation.systems.time import reset_all_actor_budgets, load_action_economy_policy
from simulation.systems.transactions import TransactionContext
from simulation.persistence.kernel_checkpoint import save_kernel_checkpoint, load_kernel_checkpoint, CheckpointError
from tests.test_campus_contact_inquiries import as_npc
from tests.test_campus_combat_deployment import travel_to_location

ROOT = Path(__file__).resolve().parents[1]


def event_boundary(bridge, kind="competition"):
    state = bridge.kernel._state
    # Explicit start-of-session boundary. No fabricated entries, scores or awards.
    state.clock.day, state.clock.phase = (3, "afternoon") if kind == "competition" else (6, "evening")
    reset_all_actor_budgets(state, load_action_economy_policy(bridge.registry))
    for actor in state.population.values():
        actor.pop("current_activity", None)
        actor.pop("current_decision", None)
    from simulation.systems.campus_forum_attention import _ledger
    _ledger(state)
    return "life:3:observation_challenge" if kind == "competition" else "life:6:club_exchange_festival"


class CampusEventTests(unittest.TestCase):
    def setUp(self): self.bridge = CampusKernelBridge(42)

    @property
    def state(self): return self.bridge.kernel._state

    def op(self, action, sid, actor="player", **parameters):
        return as_npc(self.bridge, actor, action, {"session_id": sid, **parameters})

    def participate(self, sid, actor="player", **options):
        row = session(self.state, sid)
        result = self.op("ENROLL_CAMPUS_OPPORTUNITY", sid, actor, event_options=options)
        self.assertTrue(result.success, result)
        travel_to_location(self.bridge, row["location_id"], actor)
        result = self.op("ATTEND_CAMPUS_OPPORTUNITY", sid, actor)
        self.assertTrue(result.success, result)
        self.last_performance_result = result
        return ledger(self.state)["records"][sid][actor]["result"]["event"]

    def finish_boundary(self, advance=True):
        if advance:
            self.state.clock.phase = "evening" if self.state.clock.phase == "afternoon" else "late_night"
        command = SimulationCommand("finalize", "player", "ADVANCE_PHASE", self.state.revision)
        context = TransactionContext(self.state, self.bridge.kernel._rng, command)
        return finalize_events(context)

    def test_booking_is_free_and_performance_uses_pre_action_inputs_once(self):
        sid = event_boundary(self.bridge)
        before = deepcopy((self.state.clock, self.state.inventories, self.state.population))
        self.assertTrue(self.op("ENROLL_CAMPUS_OPPORTUNITY", sid).success)
        self.assertEqual(before, (self.state.clock, self.state.inventories, self.state.population))
        self.assertEqual("activity_wrong_location", self.op("ATTEND_CAMPUS_OPPORTUNITY", sid).code)
        travel_to_location(self.bridge, "indoor_sports_hall")
        expected = performance_inputs(self.state, "player", session(self.state, sid), {})
        budget = self.state.action_economy["actors"]["player"]["major_remaining"]
        receipt = self.participate(sid)
        for key in expected: self.assertEqual(expected[key], receipt[key])
        self.assertFalse(receipt["finalized"])
        self.assertEqual(budget - 1, self.state.action_economy["actors"]["player"]["major_remaining"])
        self.assertEqual([], event_board(self.state)[0]["results"])
        self.assertFalse(self.op("ATTEND_CAMPUS_OPPORTUNITY", sid, score=999, winner=True).success)
        self.assertEqual([], list(life_invariant(self.state)))

    def test_results_wait_for_all_actors_ties_not_arrival_order_and_idempotent(self):
        sid = event_boundary(self.bridge)
        row = session(self.state, sid)
        actor = next(a for a in self.state.population if a != "player" and not assessment(self.state, a, row)[0]
            and self.state.population[a]["college_id"] == self.state.population["player"]["college_id"])
        # Controlled equal skill/preparation fixture, not natural progression.
        for who in ("player", actor):
            self.state.population[who]["attributes"].update(focus=8, insight=8)
            self.state.population[who]["needs"]["rest"] = 20
            self.state.population[who].pop("activity_progress", None)
            self.state.knowledge.get("actors", {}).pop(who, None)
            self.state.inventories["actors"][who]["quantities"]["blank_notebook"] = 1
        self.participate(sid, actor)
        self.participate(sid)
        self.assertEqual([], event_board(self.state)[0]["results"])
        self.assertEqual(2, self.finish_boundary()["campus_event_results"])
        rows = event_board(self.state)[0]["results"]
        self.assertEqual([1, 1], [r["rank"] for r in rows])
        self.assertTrue(all(r["outcome"] == "placed" for r in rows))
        before = self.state.to_dict()
        self.assertEqual(0, self.finish_boundary(advance=False)["campus_event_results"])
        self.assertEqual(before, self.state.to_dict())
        self.assertEqual([], list(life_invariant(self.state)))

    def test_festival_has_real_collective_outcome_and_club_contribution(self):
        sid = event_boundary(self.bridge, "festival")
        row = session(self.state, sid)
        people = [a for a in self.state.population if a != "player" and not assessment(self.state, a, row)[0]][:3]
        for who in people:
            # Controlled high-skill fixture for the collective-success branch.
            self.state.population[who]["attributes"].update(expression=10, empathy=10)
            self.state.population[who]["needs"]["rest"] = 0
            self.participate(sid, who)
        self.finish_boundary()
        rows = event_board(self.state)[0]["results"]
        self.assertEqual(3, len(rows))
        self.assertTrue(all(r["outcome"] == "full_festival" for r in rows))
        self.assertNotIn("player", [r["actor_id"] for r in rows])
        self.assertEqual([], list(life_invariant(self.state)))

    def test_low_participation_is_small_exchange_not_fabricated_festival(self):
        sid = event_boundary(self.bridge, "festival")
        self.participate(sid)
        self.finish_boundary()
        row = event_board(self.state)[0]["results"][0]
        self.assertEqual("small_exchange", row["outcome"])
        self.assertIn("1 人", row["summary"])

    def test_organization_options_permission_recheck_real_spend_and_no_double_charge(self):
        sid = event_boundary(self.bridge, "festival")
        club = next(c for c in self.state.organizations.values() if c.get("memberships"))
        club_id = club["organization_id"]
        actor = club["leader_id"]
        # Permission boundary fixture: clear only this actor's routine duty.
        for slots in self.state.population[actor]["weekly_schedule"].values():
            for slot in slots.values(): slot["priority"] = 10
        options = {"club_id": club_id, "use_club_resources": True}
        before = deepcopy(club["resources"])
        self.assertTrue(self.op("ENROLL_CAMPUS_OPPORTUNITY", sid, actor, event_options=options).success)
        self.assertEqual(before, self.state.organizations[club_id]["resources"])
        travel_to_location(self.bridge, "mirror_lake_square", actor)
        current_club = self.state.organizations[club_id]
        original_resource = deepcopy(current_club["resources"])
        current_club["resources"]["current"] = 0  # Deliberate depletion after booking.
        budget = deepcopy(self.state.action_economy)
        self.assertEqual("event_resource_unavailable", self.op("ATTEND_CAMPUS_OPPORTUNITY", sid, actor).code)
        self.assertEqual(budget, self.state.action_economy)
        self.state.organizations[club_id]["resources"] = original_resource
        result = self.op("ATTEND_CAMPUS_OPPORTUNITY", sid, actor)
        self.assertTrue(result.success, result)
        current_club = self.state.organizations[club_id]
        self.assertEqual(original_resource["current"] - 3, current_club["resources"]["current"])
        self.assertEqual(original_resource["spent_total"] + 3, current_club["resources"]["spent_total"])
        self.assertFalse(self.op("ATTEND_CAMPUS_OPPORTUNITY", sid, actor).success)
        before_contribution = current_club["memberships"][actor]["contribution"]
        self.finish_boundary()
        self.assertEqual(before_contribution + 1, self.state.organizations[club_id]["memberships"][actor]["contribution"])
        self.assertEqual([], list(life_invariant(self.state)))

    def test_unauthorized_options_and_forged_results_cannot_buy_success(self):
        sid = event_boundary(self.bridge)
        before = deepcopy((self.state.population, self.state.action_economy, self.state.inventories))
        for options in ([], {"score": 999}, {"use_club_resources": "yes"}, {"club_id": "invented"}, {"use_club_resources": True}):
            self.assertFalse(self.op("ENROLL_CAMPUS_OPPORTUNITY", sid, event_options=options).success)
        self.assertEqual(before, (self.state.population, self.state.action_economy, self.state.inventories))
        self.participate(sid)
        receipt = ledger(self.state)["records"][sid]["player"]["result"]["event"]
        receipt["score"] += 1
        self.assertIn("invalid campus event performance", list(life_invariant(self.state)))

    def test_private_preparation_stays_private_and_public_results_not_contacts(self):
        sid = event_boundary(self.bridge)
        self.participate(sid)
        row = session(self.state, sid)
        actor = next(a for a in self.state.population if a != "player" and not assessment(self.state, a, row)[0])
        self.participate(sid, actor)
        # Both direct activity receipts and the scheduled activity cache use
        # the same authoritative effects; exercise every existing UI outlet.
        self.state.population[actor]["current_activity"] = {"effects": deepcopy(self.state.population[actor]["last_activity_effects"])}
        snapshot = self.bridge.snapshot()
        encoded_actor = json.dumps(snapshot["population"][actor])
        self.assertNotIn("ability_ranks", encoded_actor)
        self.assertNotIn("resource_before", encoded_actor)
        from simulation.api.views import npc_chronicle_view
        public = npc_chronicle_view(self.state, actor)
        private = npc_chronicle_view(self.state, actor, viewer_id=actor)
        self.assertNotIn("ability_ranks", json.dumps(public))
        self.assertIn("ability_ranks", json.dumps(private))
        self.assertIn("ability_ranks", str(ledger(self.state)["records"][sid][actor]))
        from simulation.api.commands import command_result_view
        from simulation.actions.commands import CommandResult
        event_payloads = [e for e in self.last_performance_result.events if e.actor_ids == (actor,) and e.event_type in {"CAMPUS_ACTIVITY_EFFECT_APPLIED", "CAMPUS_LIFE_ATTENDED"}]
        outcome = CommandResult("projection", True, True, True, "success", "done", self.state.revision, events=tuple(event_payloads))
        self.assertNotIn("ability_ranks", json.dumps(command_result_view(outcome, viewer_id="player")))
        self.assertIn("ability_ranks", json.dumps(command_result_view(outcome, viewer_id=actor)))
        contacts = deepcopy(self.state.relationships)
        self.finish_boundary()
        board = event_board(self.state)
        encoded = json.dumps(board)
        for key in ("inputs", "components", "resource_before", "rest_need", "event_options"):
            self.assertNotIn(key, encoded)
        self.assertEqual(contacts, self.state.relationships)
        from simulation.systems.campus_life import life_view
        schema = json.loads((ROOT / "contracts/campus_life.schema.json").read_text())
        allowed = schema["properties"]["event_board"]["items"]["properties"]["results"]["items"]["properties"]
        self.assertTrue(all(set(r) <= set(allowed) for event in board for r in event["results"]))
        self.assertEqual(board, life_view(self.state)["event_board"])

    def test_score_changes_with_real_inputs_not_claimed_result_and_view_is_read_only(self):
        sid = event_boundary(self.bridge)
        row = session(self.state, sid)
        before = self.state.to_dict()
        base = performance_inputs(self.state, "player", row, {})
        event_view(self.state, "player", row)
        self.assertEqual(before, self.state.to_dict())
        self.state.knowledge.setdefault("actors", {}).setdefault("player", {"topics": {}})["topics"]["course:research_methods"] = 24
        self.state.population["player"].setdefault("activity_progress", {})["by_category"] = {"study": 6}
        stronger = performance_inputs(self.state, "player", row, {})
        self.assertGreater(stronger["score"], base["score"])
        from simulation.systems.campus_abilities import grant_ability_experience
        ability = base["inputs"]["ability"]["contributions"][0]["ability_id"]
        grant_ability_experience(self.state, "player", ability, 700)
        trained = performance_inputs(self.state, "player", row, {})
        self.assertGreater(trained["components"]["ability"], stronger["components"]["ability"])
        invalid = deepcopy(ledger(self.state)["definitions"])
        invalid["observation_challenge"]["event"]["attributes"] = {"invented": 5}
        self.assertTrue(list(event_definition_errors(invalid, self.state.inventories["catalog"])))

    def test_save_roundtrip_additive_migration_preserves_history_rng_and_source(self):
        sid = event_boundary(self.bridge)
        self.participate(sid)
        state, rng = self.bridge.kernel.capture_checkpoint()
        spec = json.loads((ROOT / "simulation/persistence/campus_events_content.json").read_text())
        with TemporaryDirectory() as directory:
            path = Path(directory) / "save.json"
            save_kernel_checkpoint(path, state, rng, content_manifest=self.bridge.registry.manifest)
            loaded = load_kernel_checkpoint(path, expected_content_version=state.content_version)
            self.assertEqual(json.dumps(state.to_dict(), sort_keys=True), json.dumps(loaded.state.to_dict(), sort_keys=True))
            old = state.clone()
            old.content_version = spec["source_version"]
            ledger(old)["definitions"] = deepcopy(spec["source_definitions"])
            ledger(old)["records"].pop(sid)
            save_kernel_checkpoint(path, old, rng, content_manifest=spec["source_manifest"])
            original = path.read_bytes()
            migrated = load_kernel_checkpoint(path, expected_content_version=state.content_version)
            comparison = migrated.state.clone()
            ledger(comparison)["definitions"] = deepcopy(spec["source_definitions"])
            self.assertEqual({"day": old.clock.day, "phase": old.clock.phase}, ledger(comparison).pop("events_available_from"))
            comparison.content_version = old.content_version
            self.assertEqual(json.dumps(old.to_dict(), sort_keys=True), json.dumps(comparison.to_dict(), sort_keys=True))
            self.assertEqual(rng.snapshot(), migrated.rng.snapshot())
            self.assertEqual(original, path.read_bytes())
            ledger(old)["definitions"]["campus_walk"]["name"] = "tampered"
            save_kernel_checkpoint(path, old, rng, content_manifest=spec["source_manifest"])
            with self.assertRaises(CheckpointError):
                load_kernel_checkpoint(path, expected_content_version=state.content_version)

    def test_own_results_and_personal_motivation_do_not_imply_forced_participation(self):
        sid = event_boundary(self.bridge, "festival")
        row = session(self.state, sid)
        actor = next(a for a in self.state.population if a != "player")
        before = self.state.to_dict()
        event_options(self.state, actor, row)
        event_motivation(self.state, actor, row)
        self.assertEqual(before, self.state.to_dict())
        self.assertEqual([], own_event_context(self.state, actor))
        self.participate(sid)
        self.finish_boundary()
        self.assertEqual([], own_event_context(self.state, actor))
        self.assertEqual("completed", own_event_context(self.state, "player")[0]["status"])
        self.assertNotIn("resource_before", str(own_event_context(self.state, "player")))
        from simulation.domain.cognition import BoundedDialogueRequest
        from simulation.systems.campus_cognition import bind_cognition_identity
        for who in ("player", actor):
            request = BoundedDialogueRequest(who, actor, 1, self.state.clock.day, self.state.clock.phase, {}, {}, {}, (), "近况怎样？", (), "player", {})
            bound = bind_cognition_identity(self.state, request)
            self.assertEqual(who == "player", "own_campus_event_results" in bound.state)

    def test_cancelled_and_missed_entries_never_receive_performance_or_award(self):
        from simulation.systems.campus_life import expire_life
        sid = event_boundary(self.bridge)
        self.assertTrue(self.op("ENROLL_CAMPUS_OPPORTUNITY", sid).success)
        self.assertTrue(self.op("CANCEL_CAMPUS_OPPORTUNITY", sid).success)
        row = session(self.state, sid)
        actor = next(a for a in self.state.population if a != "player" and not assessment(self.state, a, row)[0])
        self.assertTrue(self.op("ENROLL_CAMPUS_OPPORTUNITY", sid, actor).success)
        before = deepcopy((self.state.population, self.state.inventories, self.state.action_economy))
        self.state.clock.phase = "evening"
        context = TransactionContext(self.state, self.bridge.kernel._rng, SimulationCommand("expire", "player", "ADVANCE_PHASE", self.state.revision))
        expire_life(context)
        self.assertEqual("missed", ledger(self.state)["records"][sid][actor]["status"])
        self.assertNotIn("result", ledger(self.state)["records"][sid][actor])
        self.assertEqual([], event_board(self.state)[0]["results"])
        self.assertEqual(before, (self.state.population, self.state.inventories, self.state.action_economy))

    def test_model_can_choose_events_in_existing_dawn_call_and_execute_same_rules(self):
        from tests.test_campus_cognition import LastLegalProvider
        from tests.test_campus_parties import execute
        class ChooseEvent(LastLegalProvider):
            def decide(self, request, *, max_output_tokens):
                answer = super().decide(request, max_output_tokens=max_output_tokens)
                if request.daily_options is not None:
                    answer["daily_choices"] = {phase: next((r["candidate_id"] for r in rows
                        if "observation_challenge" in r.get("parameters", {}).get("life_session_id", "")), rows[0]["candidate_id"])
                        for phase,rows in request.daily_options.items()}
                return answer
        provider = ChooseEvent()
        self.bridge.cognition_runtime.provider = provider
        for _ in range(9):
            result = execute(self.bridge, "ADVANCE_PHASE")
            self.assertTrue(result["ok"], result)
        daily = [r for r in provider.requests if r.daily_options is not None]
        self.assertEqual(40, len(daily))
        self.assertTrue(all(r.phase == "morning" for r in provider.requests))
        plans = self.state.cognition["daily_plans"]["actors"]
        selected = [(actor, plan) for actor, slots in plans.items() for plan in slots.values()
            if plan.get("planned_source") == "llm" and "observation_challenge" in plan.get("parameters", {}).get("life_session_id", "")]
        self.assertTrue(selected)
        self.assertTrue(any(ledger(self.state)["records"].get(plan["parameters"]["life_session_id"], {}).get(actor, {}).get("status") == "completed" for actor,plan in selected))
        self.assertEqual([], list(life_invariant(self.state)))


if __name__ == "__main__": unittest.main()
