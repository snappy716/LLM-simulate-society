from copy import deepcopy
import unittest
from simulation.api.server import CampusKernelBridge
from simulation.actions.commands import SimulationCommand
from simulation.systems.transactions import TransactionContext
from simulation.systems.randomness import DeterministicRngPool
from simulation.systems.campus_anomaly_meetings import records, options, reserved_meeting, meetings_view, meetings_invariant, advance_meetings
from simulation.systems.campus_messaging import load_campus_messaging_policy, _add_contact
from simulation.systems.campus_growth import _actor_growth, _topic_progress
from simulation.systems.campus_social import DEFAULT_RELATIONSHIP
from tests.test_campus_anomalies import prepare_anomaly_fixture
from tests.test_campus_contact_inquiries import as_npc
from tests.test_campus_disputes import command
from tests.test_campus_combat_deployment import travel_to_location


def prepare_meeting_fixture(bridge):
    target, _, cid = prepare_anomaly_fixture(bridge)
    assert as_npc(bridge, "player", "ASK_ANOMALY_EXPERIENCE", {"npc_id": target}).success
    return target, cid


class AnomalyMeetingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = CampusKernelBridge(42)
        cls.target, cls.cid = prepare_meeting_fixture(cls.bridge)
        cls.initial, cls.rng = cls.bridge.kernel.capture_checkpoint()

    def setUp(self):
        self.bridge.kernel.restore_checkpoint(self.initial, self.rng, expected_revision=self.bridge.kernel.state.revision)

    @property
    def state(self): return self.bridge.kernel._state

    @property
    def case(self): return self.state.situations["campus_anomalies"]["cases"][self.cid]

    def propose(self, helper="player", proposer=None, **overrides):
        choice = options(self.state, self.case, helper, self.bridge.location_graph)[0]
        return as_npc(self.bridge, proposer or helper, "PROPOSE_ANOMALY_MEETING",
            {"case_id": self.cid, "helper_id": helper, **choice, **overrides})

    def row(self): return list(records(self.state).values())[-1]

    def operate(self, action, actor="player", **extra):
        row = self.row()
        return as_npc(self.bridge, actor, action, {"meeting_id": row["meeting_id"], "expected_revision": row["revision"], **extra})

    def advance(self):
        result = command(self.bridge, "ADVANCE_PHASE", {})
        self.assertTrue(result["ok"], result.get("result"))

    def test_booking_free_private_no_duplicate_or_forged_consent(self):
        before = deepcopy((self.state.clock, self.state.population, self.state.action_economy, self.case))
        self.assertTrue(self.propose().success)
        self.assertEqual("confirmed", self.row()["status"])
        self.assertEqual(before, (self.state.clock, self.state.population, self.state.action_economy, self.case))
        self.assertEqual("meeting_already_requested", self.propose().code)
        self.assertEqual([], meetings_view(self.state, "campus_student_010"))
        self.assertEqual("meeting_not_visible", self.operate("CANCEL_ANOMALY_MEETING", "campus_student_010").code)
        self.assertEqual("meeting_revision_conflict", self.operate("CANCEL_ANOMALY_MEETING", expected_revision=True).code)
        self.assertTrue(self.row()["message_ids"])
        self.assertEqual([], meetings_invariant(self.state))

    def test_actual_phase_road_travel_wait_and_player_support(self):
        self.assertTrue(self.propose().success)
        location = self.row()["location_id"]
        self.assertNotEqual(self.state.population[self.target]["current_location_id"], location)
        self.advance()
        self.assertEqual(location, self.state.population[self.target]["current_location_id"], self.row())
        activity = self.state.population[self.target]["current_activity"]
        self.assertEqual("WAIT_ANOMALY_MEETING", activity["activity_id"])
        self.assertGreater(activity["route_step_count"], 0)
        self.assertEqual(1, self.state.action_economy["actors"][self.target]["major_remaining"])
        self.assertEqual(0, self.case["revision"])
        self.assertEqual("confirmed", self.row()["status"])
        travel_to_location(self.bridge, location)
        self.assertTrue(as_npc(self.bridge, "player", "ASK_ANOMALY_EXPERIENCE", {"npc_id": self.target}).success)
        result = as_npc(self.bridge, "player", "SUPPORT_ANOMALY", {"npc_id": self.target,
            "case_id": self.cid, "expected_case_revision": self.case["revision"]})
        self.assertTrue(result.success, result.code)
        self.assertEqual("completed", self.row()["status"])
        for who in ("player", self.target): self.assertEqual(0, self.state.action_economy["actors"][who]["major_remaining"])
        self.assertEqual([], meetings_invariant(self.state))

    def test_player_must_accept_subject_request_and_can_decline(self):
        self.assertTrue(self.propose(proposer=self.target).success)
        self.assertEqual("pending", self.row()["status"])
        self.assertIsNone(reserved_meeting(self.state, "player", upcoming=True))
        self.assertEqual("recipient_required", self.operate("ACCEPT_ANOMALY_MEETING", self.target).code)
        self.assertTrue(self.operate("ACCEPT_ANOMALY_MEETING").success)
        self.assertTrue(self.operate("CANCEL_ANOMALY_MEETING").success)
        self.assertEqual("cancelled", self.row()["status"])
        self.assertEqual(0, self.case["revision"])

    def test_missing_player_does_not_heal_and_expires_once(self):
        self.propose()
        self.advance()
        self.assertEqual("confirmed", self.row()["status"])
        self.advance()
        self.assertEqual("missed", self.row()["status"])
        self.assertEqual(0, self.case["revision"])
        messages = list(self.row()["message_ids"])
        self.advance()
        self.assertEqual(messages, self.row()["message_ids"])

    def test_cancel_releases_major_reservation_without_refund(self):
        self.propose()
        self.advance()
        from simulation.systems.time import consume_major_action, load_action_economy_policy
        cmd = SimulationCommand("reserved-check", "player", "READ_KNOWLEDGE", self.state.revision,
            issued_day=self.state.clock.day, issued_phase=self.state.clock.phase)
        self.assertEqual("major_action_reserved", consume_major_action(self.state, load_action_economy_policy(self.bridge.registry), cmd).code)
        before = deepcopy(self.state.action_economy)
        self.assertTrue(self.operate("CANCEL_ANOMALY_MEETING").success)
        self.assertEqual(before, self.state.action_economy)
        self.assertIsNone(reserved_meeting(self.state, "player"))

    def test_obligations_invalid_slots_and_private_evidence(self):
        for override in ({"day": True}, {"day": []}, {"phase": []}, {"phase": "evening"}, {"location_id": []}, {"day": 2.5}, {"day": 20}):
            self.assertEqual("meeting_unavailable", self.propose(**override).code)
        self.assertEqual("meeting_unavailable", self.propose(day=3, phase="morning").code)
        self.assertEqual("experience_required", as_npc(self.bridge, "campus_student_010", "PROPOSE_ANOMALY_MEETING",
            {"case_id": self.cid, "helper_id": "player", "day": 2, "phase": "afternoon", "location_id": "mirror_lake_square"}).code)

    def test_autonomous_pair_uses_shared_action_after_real_arrival(self):
        helper = next(w for w in self.state.population if w not in {"player", self.target, "campus_student_002"}
            and not self.state.population[w].get("active_forum_task_id")
            and options(self.state, self.case, w, self.bridge.location_graph))
        # Explicit contact/knowledge fixture, not attendance or support outcomes.
        _add_contact(self.state, self.target, helper)
        for a, b in ((self.target, helper), (helper, self.target)):
            self.state.relationships[a][b] = {**DEFAULT_RELATIONSHIP, "trust": 75}
        _topic_progress(_actor_growth(self.state, helper), self.case["topic_id"])["theory"] = 20
        self.assertTrue(self.propose(helper, self.target).success)
        self.assertEqual("confirmed", self.row()["status"])
        self.advance()
        self.assertEqual("completed", self.row()["status"])
        self.assertEqual(helper, self.case["history"][-1]["helper_id"])
        for who in (helper, self.target):
            self.assertEqual(self.row()["location_id"], self.state.population[who]["current_location_id"])
            self.assertEqual(0, self.state.action_economy["actors"][who]["major_remaining"])
        self.assertEqual([], meetings_invariant(self.state))

    def test_checkpoint_roundtrip_and_forged_completion_rejected(self):
        self.propose()
        saved, rng = self.bridge.kernel.capture_checkpoint()
        self.bridge.kernel.restore_checkpoint(saved, rng, expected_revision=self.state.revision)
        self.assertEqual("confirmed", self.row()["status"])
        self.row().update(status="completed", attended=[self.target, "player"], support_revision=1)
        self.assertEqual(["appointment has no actual support receipt"], meetings_invariant(self.state))

    def test_dawn_once_and_no_hidden_mastery_selection(self):
        policy = load_campus_messaging_policy(self.bridge.registry)
        ctx = TransactionContext(self.state, DeterministicRngPool(42), SimulationCommand("dawn", "player", "ADVANCE_PHASE", self.state.revision))
        before = deepcopy(records(self.state))
        advance_meetings(ctx, self.bridge.location_graph, policy)
        advance_meetings(ctx, self.bridge.location_graph, policy)
        self.assertEqual(before, records(self.state))
        self.assertEqual("declined", next(iter(records(self.state).values()))["status"])
        self.assertEqual(0, self.case["revision"])

    def test_changed_consent_cancels_without_forcing_attendance(self):
        self.assertTrue(self.propose().success)
        self.state.relationships[self.target]["player"]["trust"] = 0
        self.advance()
        self.assertEqual("cancelled", self.row()["status"])
        self.assertEqual(0, self.case["revision"])
        self.assertIsNone(reserved_meeting(self.state, "player"))

    def test_pending_request_rechecks_knowledge_and_float_revision(self):
        self.assertTrue(self.propose(proposer=self.target).success)
        _topic_progress(_actor_growth(self.state, "player"), self.case["topic_id"])["theory"] = 0
        self.assertEqual("meeting_unavailable", self.operate("ACCEPT_ANOMALY_MEETING").code)
        self.assertEqual("pending", self.row()["status"])
        _topic_progress(_actor_growth(self.state, "player"), self.case["topic_id"])["theory"] = 20
        self.assertTrue(self.operate("ACCEPT_ANOMALY_MEETING", expected_revision=float(self.row()["revision"])).success)

    def test_closed_place_and_contract(self):
        import json
        from pathlib import Path
        self.state.places["library_reading_hall"]["open_phases"] = ["morning"]
        self.assertEqual("meeting_unavailable", self.propose(location_id="library_reading_hall").code)
        schema = json.loads((Path(__file__).resolve().parents[1] / "contracts/anomaly_meeting_request.schema.json").read_text())
        self.assertEqual(["morning", "afternoon"], schema["properties"]["parameters"]["properties"]["phase"]["enum"])
        self.assertEqual(3, len(schema["properties"]["action_id"]["enum"]))

    def test_future_appointment_survives_other_slots_unavailability(self):
        self.assertTrue(self.propose(day=3).success)
        # Controlled unavailable-now boundary; a future promise is not a demand
        # to stop living until tomorrow. Real due-slot cancellation tested above.
        self.state.population[self.target]["needs"]["safety"] = 95
        policy = load_campus_messaging_policy(self.bridge.registry)
        ctx = TransactionContext(self.state, DeterministicRngPool(42), SimulationCommand("future-slot", "player", "ADVANCE_PHASE", self.state.revision))
        advance_meetings(ctx, self.bridge.location_graph, policy)
        self.assertEqual("confirmed", self.row()["status"])
        self.assertEqual(0, self.case["revision"])


if __name__ == "__main__": unittest.main()
