"""Explicit consenting fixtures; not evidence of natural model behavior."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from simulation.api.server import CampusKernelBridge
from simulation.persistence.kernel_checkpoint import save_kernel_checkpoint, load_kernel_checkpoint
from simulation.systems.campus_messaging import _add_contact
from simulation.systems.campus_social import DEFAULT_RELATIONSHIP
from simulation.systems.campus_outings import records, outing_view, outings_invariant
from simulation.systems.campus_relationship_anchors import sources, source_valid
from simulation.systems.campus_commitments import commitments_for
from tests.test_campus_disputes import command
from tests.test_campus_contact_inquiries import as_npc
from tests.test_campus_combat_deployment import travel_to_location
from tests.test_campus_cognition import LastLegalProvider


class OutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = CampusKernelBridge(42)
        state = cls.bridge.kernel._state
        cls.people = [who for who in state.population if who.startswith("campus_student_")][:3]
        pair = ["player", *cls.people]
        for who in pair:
            assert not state.population[who].get("active_forum_task_id")
            for day in state.population[who].get("weekly_schedule", {}).values():
                for slot in day.values():
                    slot["priority"] = 10  # Explicit uncommitted availability fixture.
            state.population[who]["needs"].update(rest=20, food=20, safety=20, social=70)
            for other in pair:
                if who != other:
                    _add_contact(state, who, other)
                    state.relationships.setdefault(who, {})[other] = {**DEFAULT_RELATIONSHIP,
                        "familiarity": 50, "closeness": 50, "trust": 70}
        cls.initial, cls.rng = cls.bridge.kernel.capture_checkpoint()

    def setUp(self):
        self.bridge.kernel.restore_checkpoint(self.initial, self.rng, expected_revision=self.bridge.kernel.state.revision)

    @property
    def state(self):
        return self.bridge.kernel._state

    def invite(self, actor="player", target=None, **overrides):
        return as_npc(self.bridge, actor, "INVITE_CAMPUS_OUTING", {"target_id": target or self.people[0],
            "day": 1, "phase": "afternoon", "location_id": "mirror_lake_square", **overrides})

    def row(self):
        return list(records(self.state).values())[-1]

    def op(self, action, actor="player", **overrides):
        row = self.row()
        p = {"outing_id": row["outing_id"], "expected_revision": row["revision"], **overrides}
        if actor == "player":
            result = command(self.bridge, action, p)
            return result["result"]
        result = as_npc(self.bridge, actor, action, p)
        return {"success": result.success, "code": result.code, "payload": result.payload}

    def advance(self):
        result = command(self.bridge, "ADVANCE_PHASE", {})
        self.assertTrue(result["ok"], result.get("result"))

    def test_invite_reserves_both_without_reward_and_is_private(self):
        before = deepcopy((self.state.population, self.state.relationships, self.state.action_economy))
        result = self.invite(kind="date")
        self.assertTrue(result.success, result.code)
        self.assertEqual("confirmed", self.row()["status"])
        self.assertEqual(before, (self.state.population, self.state.relationships, self.state.action_economy))
        for who in ("player", self.people[0]):
            self.assertTrue(any(r["kind"] == "outing" for r in commitments_for(self.state, who)))
        self.assertFalse(outing_view(self.state, self.people[1]))
        self.assertEqual("outing_not_visible", self.op("CANCEL_CAMPUS_OUTING", actor=self.people[1])["code"])
        self.assertEqual("outing_revision_conflict", self.op("CANCEL_CAMPUS_OUTING", expected_revision=True)["code"])
        self.assertEqual("outing_pair_cooldown", self.invite(day=2).code)
        self.assertEqual([], outings_invariant(self.state))

    def test_untrusted_parameters_do_not_create_invitations(self):
        for fields in ({"day": True}, {"day": float("inf")}, {"phase": []}, {"location_id": {}},
                       {"target_id": []}, {"kind": {}}, {"day": 99}):
            with self.subTest(fields=fields):
                before = deepcopy((self.state.situations, self.state.relationships, self.state.action_economy))
                self.assertFalse(self.invite(**fields).success)
                self.assertEqual(before, (self.state.situations, self.state.relationships, self.state.action_economy))

    def test_npc_invitation_requires_player_response_and_refusal_no_penalty(self):
        before = deepcopy(self.state.relationships)
        self.assertTrue(self.invite(actor=self.people[0], target="player").success)
        self.assertEqual("pending", self.row()["status"])
        self.assertFalse(any(r["kind"] == "outing" for r in commitments_for(self.state, "player")))
        self.assertEqual("recipient_required", self.op("ACCEPT_CAMPUS_OUTING", actor=self.people[0])["code"])
        self.assertTrue(self.op("DECLINE_CAMPUS_OUTING")["success"])
        self.assertEqual("declined", self.row()["status"])
        self.assertEqual(before, self.state.relationships)

    def test_actual_road_arrival_and_atomic_shared_cost(self):
        self.assertTrue(self.invite().success)
        self.advance()
        target = self.people[0]
        self.assertEqual("mirror_lake_square", self.state.population[target]["current_location_id"])
        self.assertEqual([target], self.row()["attended"])
        self.assertEqual("confirmed", self.row()["status"])
        self.assertEqual(1, self.state.action_economy["actors"][target]["major_remaining"])
        self.assertEqual("outing_wrong_location", self.op("ATTEND_CAMPUS_OUTING")["code"])
        travel_to_location(self.bridge, "mirror_lake_square")
        before = deepcopy(self.state.relationships)
        result = self.op("ATTEND_CAMPUS_OUTING")
        self.assertTrue(result["success"], result)
        self.assertEqual("completed", self.row()["status"])
        for who, other in (("player", target), (target, "player")):
            self.assertEqual(0, self.state.action_economy["actors"][who]["major_remaining"])
            self.assertEqual(before[who][other]["closeness"] + 2, self.state.relationships[who][other]["closeness"])
        saved = deepcopy((self.state.action_economy, self.state.relationships))
        self.assertEqual("outing_revision_conflict", self.op("ATTEND_CAMPUS_OUTING")["code"])
        self.assertEqual(saved, (self.state.action_economy, self.state.relationships))
        self.assertEqual([], outings_invariant(self.state))
        view = outing_view(self.state, "player")[-1]
        self.assertEqual({"player"}, set(view["receipt"]["costs"]))
        self.assertEqual({"player"}, set(view["receipt"]["relationship_deltas"]))
        case = {"actor_id": target, "history": []}
        shared = sources(self.state, case, "player")
        source_id = "outing:" + self.row()["outing_id"]
        self.assertTrue(any(r["source_id"] == source_id for r in shared))
        self.assertTrue(source_valid(self.state, case, {"source_id": source_id, "helper_id": "player",
            "day": 1, "phase": "afternoon"}))

    def test_npc_pair_can_complete_without_player_attendance(self):
        first, second = self.people[:2]
        self.assertTrue(self.invite(actor=first, target=second).success)
        before = deepcopy(self.state.population["player"])
        self.advance()
        self.assertEqual("completed", self.row()["status"])
        self.assertEqual({first, second}, set(self.row()["receipt"]["costs"]))
        self.assertEqual(before["current_location_id"], self.state.population["player"]["current_location_id"])
        self.assertEqual(1, self.state.action_economy["actors"]["player"]["major_remaining"])

    def test_missing_player_expires_without_consuming_partner_budget(self):
        self.invite()
        self.advance()
        self.assertEqual(1, self.state.action_economy["actors"][self.people[0]]["major_remaining"])
        self.assertIsNone(self.row()["receipt"])
        self.advance()
        self.assertEqual("missed", self.row()["status"])
        self.assertIsNone(self.row()["receipt"])

    def test_conflicts_in_both_directions_and_cancel_releases(self):
        self.invite()
        blocked = command(self.bridge, "ENROLL_CAMPUS_OPPORTUNITY", {"session_id": "life:1:research_methods_course"})
        self.assertFalse(blocked["ok"])
        self.assertTrue(self.op("CANCEL_CAMPUS_OUTING")["success"])
        self.assertTrue(command(self.bridge, "ENROLL_CAMPUS_OPPORTUNITY", {"session_id": "life:1:research_methods_course"})["ok"])
        self.assertEqual("outing_unavailable", self.invite(target=self.people[1]).code)

    def test_changed_willingness_cancels_without_partial_cost(self):
        self.invite()
        self.advance()
        travel_to_location(self.bridge, "mirror_lake_square")
        self.state.relationships[self.people[0]]["player"]["conflict"] = 60
        before = deepcopy((self.state.relationships, self.state.action_economy))
        self.assertTrue(self.op("ATTEND_CAMPUS_OUTING")["success"])
        self.assertEqual("cancelled", self.row()["status"])
        self.assertEqual(before, (self.state.relationships, self.state.action_economy))

    def test_reserved_budget_and_partner_cost_failure_are_atomic(self):
        self.invite()
        self.advance()
        from simulation.actions.commands import SimulationCommand
        from simulation.systems.time import consume_major_action, load_action_economy_policy
        policy = load_action_economy_policy(self.bridge.registry)
        probe = self.state.clone()
        attempted = consume_major_action(probe, policy, SimulationCommand("reserved-probe", "player", "SELF_STUDY",
            probe.revision, issued_day=probe.clock.day, issued_phase=probe.clock.phase))
        self.assertEqual("major_action_reserved", attempted.code)
        self.assertEqual(self.state.action_economy, probe.action_economy)
        travel_to_location(self.bridge, "mirror_lake_square")
        # Explicit exhausted partner boundary. Do not fabricate a completed outing.
        self.state.action_economy["actors"][self.people[0]]["major_remaining"] = 0
        before = deepcopy((self.state.action_economy, self.state.relationships))
        self.assertTrue(self.op("ATTEND_CAMPUS_OUTING")["success"])
        self.assertEqual("confirmed", self.row()["status"])
        self.assertIsNone(self.row()["receipt"])
        self.assertEqual(before, (self.state.action_economy, self.state.relationships))

    def test_save_roundtrip_and_forged_receipt_rejected(self):
        self.invite()
        self.advance()
        travel_to_location(self.bridge, "mirror_lake_square")
        self.op("ATTEND_CAMPUS_OUTING")
        state, rng = self.bridge.kernel.capture_checkpoint()
        with TemporaryDirectory() as folder:
            path = Path(folder) / "outing.json"
            save_kernel_checkpoint(path, state, rng, content_manifest=self.bridge.registry.manifest)
            loaded = load_kernel_checkpoint(path, expected_content_version=state.content_version)
            self.assertEqual(records(state), records(loaded.state))
            self.assertEqual(rng.snapshot(), loaded.rng.snapshot())
        self.row()["receipt"]["costs"]["player"]["after"] += 1
        self.assertEqual(["invalid shared outing cost"], outings_invariant(self.state))

    def test_fake_daily_model_can_choose_optional_outings_without_extra_calls(self):
        class OutingProvider(LastLegalProvider):
            def decide(self, request, *, max_output_tokens):
                answer = super().decide(request, max_output_tokens=max_output_tokens)
                if request.daily_options is not None:
                    answer["daily_choices"] = {phase: next((r["candidate_id"] for r in rows
                        if r.get("parameters", {}).get("outing_intent")), rows[0]["candidate_id"])
                        for phase, rows in request.daily_options.items()}
                return answer
        # Explicit social interest and trusted contacts; no decisions/results injected.
        focused = list(self.state.cognition["focused_ids"])
        for index, who in enumerate(focused):
            other = focused[(index + 1) % len(focused)]
            _add_contact(self.state, who, other)
            for a, b in ((who, other), (other, who)):
                self.state.relationships.setdefault(a, {})[b] = {**DEFAULT_RELATIONSHIP,
                    "trust": 80, "closeness": 80, "familiarity": 80}
            person = self.state.population[who]
            person["needs"].update(rest=20, food=20, safety=20, social=100)
            person["personality"]["extraversion"] = 100
            for day in person.get("weekly_schedule", {}).values():
                for slot in day.values(): slot["priority"] = 10
        provider = OutingProvider()
        self.bridge.cognition_runtime.provider = provider
        unavailable_night_shift = False
        for _ in range(5):
            self.advance()
            unavailable_night_shift |= any(person.get("current_activity", {}).get("block_code") == "clinic_layer_unavailable"
                for person in self.state.population.values())
        self.assertTrue(unavailable_night_shift, "off-duty medic in night world must not abort the shared phase")
        requests = [r for r in provider.requests if r.daily_options is not None]
        self.assertEqual(20, len(requests))
        self.assertTrue(all(r.phase == "morning" for r in requests))
        self.assertTrue(any(option.get("parameters", {}).get("outing_intent")
            for r in requests for rows in r.daily_options.values() for option in rows))
        chosen = [r for r in records(self.state).values() if r["created_day"] == 2 and r["proposer_id"] in focused]
        self.assertTrue(chosen)
        self.assertTrue(any(r["status"] == "completed" for r in chosen), chosen)
        self.assertTrue(all("player" not in (r["proposer_id"], r["recipient_id"]) for r in chosen))
