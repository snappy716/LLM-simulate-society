"""Actual reservations at an explicit free-slot boundary, not natural evidence."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from simulation.actions.commands import SimulationCommand
from simulation.api.server import CampusKernelBridge
from simulation.systems.campus_anomalies import anomaly_view, make_anomaly_handler, advance_anomaly_support
from simulation.systems.campus_growth import _actor_growth, _topic_progress
from simulation.systems.campus_messaging import _add_contact
from simulation.systems.campus_outings import records
from simulation.systems.campus_social import DEFAULT_RELATIONSHIP
from simulation.systems.randomness import DeterministicRngPool
from simulation.systems.time import reset_all_actor_budgets, load_action_economy_policy
from simulation.systems.transactions import TransactionContext
from tests.test_campus_anomalies import prepare_anomaly_fixture
from tests.test_campus_contact_inquiries import as_npc
from tests.test_campus_combat_deployment import travel_to_location


def reserve_for_support(bridge, target, helper, reserved, kind="outing"):
    state = bridge.kernel._state
    for who in ("player", target, helper):
        state.population[who]["needs"].update(rest=20, food=20, safety=20, social=70)
        for day in state.population[who]["weekly_schedule"].values():
            for slot in day.values(): slot["priority"] = 10
    for who, other in ((reserved, helper), (helper, reserved)):
        _add_contact(state, who, other)
        state.relationships[who][other] = {**DEFAULT_RELATIONSHIP, "familiarity": 50, "closeness": 50, "trust": 70}
    for who in ("player", target, helper): travel_to_location(bridge, "mirror_lake_square", who)
    state = bridge.kernel._state
    if kind == "outing":
        result = as_npc(bridge, reserved, "INVITE_CAMPUS_OUTING", {"target_id": helper,
            "kind": "companionship", "day": state.clock.day, "phase": "afternoon", "location_id": "mirror_lake_square"})
    else:
        result = as_npc(bridge, reserved, "ENROLL_CAMPUS_OPPORTUNITY", {"session_id": f"life:{state.clock.day}:campus_walk"})
    assert result.success, result.code
    state = bridge.kernel._state
    # Simulate the start-of-phase boundary before scheduled NPC execution. The
    # reservations above were produced by real commands, not fabricated records.
    state.clock.phase = "afternoon"
    reset_all_actor_budgets(state, load_action_economy_policy(bridge.registry))
    for person in state.population.values():
        person.pop("current_activity", None)
        person.pop("current_decision", None)
    from simulation.systems.campus_forum_attention import _ledger
    _ledger(state)


class SupportReservationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = CampusKernelBridge(42)
        cls.target, cls.helper, cls.cid = prepare_anomaly_fixture(cls.bridge)
        cls.initial, cls.rng = cls.bridge.kernel.capture_checkpoint()

    def setUp(self):
        self.bridge.kernel.restore_checkpoint(self.initial, self.rng, expected_revision=self.bridge.kernel._state.revision)

    @property
    def state(self): return self.bridge.kernel._state

    def ask(self):
        self.assertTrue(as_npc(self.bridge, "player", "ASK_ANOMALY_EXPERIENCE", {"npc_id": self.target}).success)

    def params(self):
        case = self.state.situations["campus_anomalies"]["cases"][self.cid]
        return {"npc_id": self.target, "case_id": self.cid, "expected_case_revision": case["revision"]}

    def balances(self):
        return deepcopy((self.state.action_economy, self.state.relationships, self.state.situations))

    def check_reserved(self, kind):
        for reserved in ("player", self.target):
            with self.subTest(kind=kind, reserved=reserved):
                self.setUp()
                reserve_for_support(self.bridge, self.target, self.helper, reserved, kind)
                self.ask()
                before = self.balances()
                view = next(row for row in anomaly_view(self.state) if row["case_id"] == self.cid)
                self.assertFalse(view["can_support"])
                self.assertIn("未扣行动", view["support_hint"])
                result = as_npc(self.bridge, "player", "SUPPORT_ANOMALY", self.params())
                self.assertFalse(result.success)
                self.assertEqual("major_action_reserved", result.code)
                self.assertEqual(before, self.balances())

    def test_outing_of_either_participant_is_respected(self): self.check_reserved("outing")

    def test_life_booking_of_either_participant_is_respected(self): self.check_reserved("life")

    def test_atomic_preflight_even_if_earlier_projection_misses_a_reservation(self):
        reserve_for_support(self.bridge, self.target, self.helper, self.target)
        self.ask()
        before = self.balances()
        command = SimulationCommand("direct-cost-check", "player", "SUPPORT_ANOMALY", self.state.revision,
            parameters=self.params(), issued_day=self.state.clock.day, issued_phase=self.state.clock.phase)
        context = TransactionContext(self.state, DeterministicRngPool(42), command)
        with patch("simulation.systems.campus_anomalies._support_problem", return_value=None):
            result = make_anomaly_handler()(context, command)
        self.assertFalse(result.success)
        self.assertEqual("major_action_reserved", result.code)
        self.assertEqual(before, self.balances())
        self.assertFalse(context.event_drafts)

    def test_explicit_cancellation_releases_support_without_free_recovery(self):
        reserve_for_support(self.bridge, self.target, self.helper, "player")
        self.ask()
        row = list(records(self.state).values())[-1]
        self.assertTrue(as_npc(self.bridge, "player", "CANCEL_CAMPUS_OUTING", {
            "outing_id": row["outing_id"], "expected_revision": row["revision"]}).success)
        self.assertTrue(next(row for row in anomaly_view(self.state) if row["case_id"] == self.cid)["can_support"])
        before = deepcopy((self.state.clock, self.state.population))
        self.assertTrue(as_npc(self.bridge, "player", "SUPPORT_ANOMALY", self.params()).success)
        self.assertEqual(before, (self.state.clock, self.state.population))
        for who in ("player", self.target): self.assertEqual(0, self.state.action_economy["actors"][who]["major_remaining"])
        self.assertFalse(as_npc(self.bridge, "player", "SUPPORT_ANOMALY", self.params()).success)

    def test_autonomous_support_does_not_steal_reserved_actions(self):
        reserve_for_support(self.bridge, self.target, self.helper, self.target)
        case = self.state.situations["campus_anomalies"]["cases"][self.cid]
        _topic_progress(_actor_growth(self.state, self.helper), case["topic_id"])["theory"] = 20
        before = deepcopy(self.state.action_economy)
        command = SimulationCommand("boundary", "player", "ADVANCE_PHASE", self.state.revision)
        result = advance_anomaly_support(TransactionContext(self.state, DeterministicRngPool(42), command))
        self.assertEqual(0, result["anomaly_supports"])
        self.assertEqual(before, self.state.action_economy)
        self.assertFalse(case["history"])


if __name__ == "__main__": unittest.main()
