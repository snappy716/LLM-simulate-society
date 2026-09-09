"""Shared reservation projection; explicit fixtures are not natural LLM evidence."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from simulation.api.server import CampusKernelBridge
from simulation.cognition.action_rules import action_rule_context
from simulation.persistence.kernel_checkpoint import save_kernel_checkpoint, load_kernel_checkpoint
from simulation.systems.campus_commitments import commitments_for, commitments_at, agenda_view
from simulation.systems.campus_departures import assess_departure
from simulation.systems.campus_parties import party_policy_from_state
from simulation.systems.campus_social_coordination import coordinate_daily_social
from simulation.systems.campus_messaging import load_campus_messaging_policy
from tests.test_campus_parties import execute, accepted_candidate
from tests.test_campus_social_coordination import prepare_fixture


class CommitmentTests(unittest.TestCase):
    def setUp(self):
        self.bridge = CampusKernelBridge(46)

    @property
    def state(self):
        return self.bridge.kernel._state

    def reserve(self, day=1, phase="evening"):
        return execute(self.bridge, "RESERVE_PARTY_DEPARTURE", {"day": day, "phase": phase})

    def test_real_reservation_calendar_cancel_and_budget_unchanged(self):
        before = deepcopy(self.state.action_economy)
        self.assertTrue(self.reserve()["ok"])
        rows = self.bridge.snapshot()["agenda"]["commitments"]
        self.assertEqual([("departure", 1, "evening")], [(r["kind"], r["day"], r["phase"]) for r in rows])
        self.assertEqual(before, self.state.action_economy)
        self.assertTrue(execute(self.bridge, "CANCEL_PARTY_DEPARTURE")["ok"])
        self.assertEqual([], agenda_view(self.state)["commitments"])
        self.assertEqual(before, self.state.action_economy)

    def test_detached_party_assessment_ignores_only_own_booking(self):
        self.assertTrue(self.reserve()["ok"])
        party = deepcopy(self.state.parties["party:player"])
        policy = party_policy_from_state(self.state)
        self.assertTrue(assess_departure(self.state, party, 1, "evening", policy)["allowed"])
        other = deepcopy(party)
        other["party_id"] = "fixture:other"
        self.state.parties["fixture:other"] = other
        self.assertFalse(assess_departure(self.state, party, 1, "evening", policy)["allowed"])
        self.assertTrue(assess_departure(self.state, party, 2, "evening", policy)["allowed"])

    def test_social_booking_blocks_departure_atomically_for_either_member(self):
        target = accepted_candidate(self.bridge.snapshot())["actor_id"]
        self.assertTrue(execute(self.bridge, "INVITE_PARTY_MEMBER", {"target_id": target})["ok"])
        self.assertTrue(self.reserve(2)["ok"])
        for participant in ("player", target):
            with self.subTest(participant=participant):
                # Inject only the already-confirmed boundary, not a consent result.
                self.state.cognition["social_coordination"] = {"day": 1, "actors": {
                    participant: {"target_id": "campus_student_010", "phase": "evening", "status": "confirmed"}}}
                before = deepcopy((self.state.parties, self.state.action_economy))
                result = self.reserve()
                self.assertFalse(result["ok"])
                self.assertEqual("departure_conflict", result["result"]["code"])
                self.assertEqual(before, (self.state.parties, self.state.action_economy))

    def test_departure_blocks_social_invitation_for_sender_or_recipient(self):
        for owner in ("sender", "recipient"):
            with self.subTest(owner=owner):
                bridge = CampusKernelBridge(42)
                state, sender, target, plans, registry, context = prepare_fixture(bridge)
                actor = sender if owner == "sender" else target
                state.parties["fixture:departure"] = {"members": {actor: {"departure": {
                    "day": state.clock.day, "phase": "evening"}}}}
                before = deepcopy(plans)
                coordinate_daily_social(context, plans, load_campus_messaging_policy(registry))
                row = state.cognition["social_coordination"]["actors"][sender]
                self.assertEqual(("declined", "reserved"), (row["status"], row["reason"]))
                self.assertEqual(before, plans)

    def test_completed_declined_pending_and_past_not_reserved(self):
        self.state.situations["anomaly_meetings"] = {"records": {status: {
            "status": status, "subject_id": "player", "helper_id": "campus_student_010", "day": 1, "phase": "afternoon"
        } for status in ("pending", "completed", "missed", "cancelled", "confirmed")}}
        self.assertEqual(["confirmed"], [r["source_id"] for r in commitments_for(self.state, "player")])
        self.state.clock.phase = "evening"
        self.assertEqual([], commitments_for(self.state, "player"))
        self.state.cognition["social_coordination"] = {"day": 1, "actors": {"player": {
            "status": "declined", "phase": "evening", "target_id": "campus_student_010"}}}
        self.assertEqual([], commitments_for(self.state, "player"))

    def test_social_receipt_releases_slot_for_both_participants(self):
        self.state.cognition["social_coordination"] = {"day": 1, "actors": {"player": {
            "status": "confirmed", "phase": "evening", "target_id": "campus_student_010"}}}
        for who in ("player", "campus_student_010"):
            self.assertEqual(0, commitments_for(self.state, who)[0]["major_action_cost"])
        self.state.cognition["social_agenda_receipts"] = {"day": 1, "actors": {"player": {"status": "not_met"}}}
        for who in ("player", "campus_student_010"):
            self.assertEqual([], commitments_for(self.state, who))

    def test_support_ignore_and_privacy_read_only(self):
        self.state.situations["anomaly_meetings"] = {"records": {"private-case-meeting": {
            "status": "confirmed", "subject_id": "campus_student_010", "helper_id": "campus_student_011",
            "day": 2, "phase": "afternoon", "location_id": "library_reading_hall"}}}
        before = deepcopy(self.state)
        self.assertEqual([], agenda_view(self.state)["commitments"])
        self.assertEqual([], commitments_for(self.state, "unknown"))
        self.assertEqual([], commitments_at(self.state, "campus_student_010", 2, "afternoon", ignore=("support", "private-case-meeting")))
        context = action_rule_context(self.state, "campus_student_010")
        self.assertEqual([{"kind": "support", "day": 2, "phase": "afternoon", "major_action_cost": 1}], context["own_confirmed_slots"])
        for secret in ("private-case-meeting", "campus_student_011", "library_reading_hall"):
            self.assertNotIn(secret, repr(context))
        rows = commitments_for(self.state, "campus_student_010")
        rows[0]["day"] = 900
        self.assertEqual(before, self.state)

    def test_disk_restore_rebuilds_projection_without_second_ledger(self):
        self.assertTrue(self.reserve(2)["ok"])
        expected = agenda_view(self.state)
        state, rng = self.bridge.kernel.capture_checkpoint()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "calendar.json"
            save_kernel_checkpoint(path, state, rng)
            restored = load_kernel_checkpoint(path).state
        self.assertEqual(expected, agenda_view(restored))
        self.assertEqual(state.action_economy, restored.action_economy)


if __name__ == "__main__":
    unittest.main()
