from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from simulation.api.server import CampusKernelBridge
from simulation.actions.commands import SimulationCommand
from simulation.systems import DeterministicRngPool
from simulation.systems.transactions import TransactionContext
from simulation.systems.campus_anomalies import (sync_anomaly_cases, anomaly_view, anomalies_invariant,
    advance_anomaly_support, make_anomaly_handler)
from simulation.systems.campus_growth import _actor_growth, _topic_progress
from simulation.systems.time import reset_all_actor_budgets, load_action_economy_policy
from simulation.persistence.kernel_checkpoint import save_kernel_checkpoint, load_kernel_checkpoint
from tests.test_campus_welfare import prepare_welfare_fixture
from tests.test_campus_disputes import command
from tests.test_campus_contact_inquiries import as_npc
from tests.test_campus_combat_deployment import travel_to_location


def prepare_anomaly_fixture(bridge):
    """Real stranded-site release; explicit knowledge and appointment boundaries."""
    _, target, helper, *_ = prepare_welfare_fixture(bridge)
    for _ in range(2):
        result = command(bridge, "ADVANCE_PHASE", {})
        assert result["ok"], result["result"]
    state = bridge.kernel._state
    case = next(c for c in state.situations["campus_anomalies"]["cases"].values() if c["actor_id"] == target)
    for who in (target, helper):
        travel_to_location(bridge, state.population["player"]["current_location_id"], who)
        state = bridge.kernel._state
    case = state.situations["campus_anomalies"]["cases"][case["case_id"]]
    # Fixture appointment/understanding, not invented production receipts.
    for who in ("player", target, helper):
        state.population[who].pop("current_activity", None)
        state.population[who].pop("current_decision", None)
        assert not state.population[who].get("active_forum_task_id")
        state.action_economy["actors"][who]["major_remaining"] = 1
    _topic_progress(_actor_growth(state, "player"), case["topic_id"])["theory"] = 20
    return target, helper, case["case_id"]


class AnomalyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = CampusKernelBridge(42)
        cls.target, cls.helper, cls.case_id = prepare_anomaly_fixture(cls.bridge)
        cls.initial, cls.rng = cls.bridge.kernel.capture_checkpoint()

    def setUp(self):
        self.bridge.kernel.restore_checkpoint(self.initial, self.rng, expected_revision=self.bridge.kernel.state.revision)

    @property
    def state(self):
        return self.bridge.kernel._state

    @property
    def case(self):
        return self.state.situations["campus_anomalies"]["cases"][self.case_id]

    def ask(self, actor="player"):
        return as_npc(self.bridge, actor, "ASK_ANOMALY_EXPERIENCE", {"npc_id": self.target})

    def support(self, actor="player", **extra):
        return as_npc(self.bridge, actor, "SUPPORT_ANOMALY", {"npc_id": self.target,
            "case_id": self.case_id, "expected_case_revision": self.case["revision"], **extra})

    def context(self):
        return TransactionContext(self.state, DeterministicRngPool(42), SimulationCommand("fixture", "player", "ADVANCE_PHASE", self.state.revision))

    def test_real_incident_not_personality_or_unanswered_message(self):
        self.assertEqual([], anomaly_view(self.state))
        self.assertEqual([], anomalies_invariant(self.state))
        site = self.state.situations["night_sites"]["sites"][self.case_id]
        self.assertEqual(self.target, site["victim_id"])
        self.assertEqual("expired", site["status"])
        self.assertEqual("no_reported_episode", as_npc(self.bridge, "player", "ASK_ANOMALY_EXPERIENCE", {"npc_id": self.helper}).code)
        original = deepcopy(self.state.situations["campus_anomalies"])
        sync_anomaly_cases(self.context())
        self.assertEqual(original, self.state.situations["campus_anomalies"])

    def test_listening_is_free_private_source_bound_and_idempotent(self):
        before = deepcopy((self.state.clock, self.state.population, self.state.action_economy))
        helper_before = deepcopy(anomaly_view(self.state, self.helper))
        result = self.ask()
        self.assertTrue(result.success, result.code)
        self.assertEqual(before, (self.state.clock, self.state.population, self.state.action_economy))
        row = anomaly_view(self.state)[0]
        for secret in ("shell", "core", "coherence", "source_task_id", "status"):
            self.assertNotIn(secret, row)
        # The helper may already have heard a separate voluntary request at dawn;
        # the player's new private statement must not leak into that knowledge.
        self.assertEqual(helper_before, anomaly_view(self.state, self.helper))
        self.assertNotIn(row["report"]["claim_id"], self.state.knowledge["beliefs_by_actor"][self.helper])
        self.assertEqual("already_heard", self.ask().code)
        self.assertEqual([], anomalies_invariant(self.state))

    def test_support_costs_both_not_clock_or_health_and_cannot_farm(self):
        self.assertTrue(self.ask().success)
        before = deepcopy((self.state.clock, self.state.population, self.state.inventories))
        result = self.support()
        self.assertTrue(result.success, result.code)
        self.assertEqual(before, (self.state.clock, self.state.population, self.state.inventories))
        self.assertEqual((20, 40, 40, "easing"), tuple(self.case[k] for k in ("shell", "core", "coherence", "status")))
        for who in ("player", self.target):
            self.assertEqual(0, self.state.action_economy["actors"][who]["major_remaining"])
        self.assertTrue(self.ask().success)
        self.assertEqual("support_today_complete", self.support().code)
        self.assertEqual(1, len(self.case["history"]))
        self.assertEqual([], anomalies_invariant(self.state))

    def test_consent_freshness_knowledge_and_bad_commands_do_not_mutate(self):
        self.assertTrue(self.ask().success)
        self.assertEqual("case_revision_conflict", self.support(expected_case_revision=True).code)
        self.state.relationships[self.target]["player"]["trust"] = 0
        original = deepcopy((self.state.situations, self.state.action_economy, self.state.population))
        self.assertEqual("report_withheld", self.support().code)
        self.assertEqual(original, (self.state.situations, self.state.action_economy, self.state.population))
        self.state.relationships[self.target]["player"]["trust"] = 75
        _topic_progress(_actor_growth(self.state, "player"), self.case["topic_id"])["theory"] = 0
        self.assertEqual("knowledge_required", self.support().code)
        self.assertEqual("unknown_npc", as_npc(self.bridge, "player", "ASK_ANOMALY_EXPERIENCE", {"npc_id": []}).code)
        self.assertEqual(0, self.case["revision"])

    def test_remote_night_closed_place_busy_and_target_budget_boundaries(self):
        self.ask()
        self.state.population[self.target]["current_location_id"] = "library_reading_hall"
        self.assertEqual("same_location_required", self.support().code)
        self.state.population[self.target]["current_location_id"] = self.state.population["player"]["current_location_id"]
        self.state.action_economy["actors"][self.target]["major_remaining"] = 0
        self.assertEqual("major_action_exhausted", self.support().code)
        self.assertEqual(1, self.state.action_economy["actors"]["player"]["major_remaining"])
        self.state.action_economy["actors"][self.target]["major_remaining"] = 1
        self.state.places[self.state.population["player"]["current_location_id"]]["open_phases"] = ["afternoon"]
        self.assertEqual("location_closed", self.support().code)
        self.state.clock.phase = "evening"
        outcome = make_anomaly_handler()(self.context(), SimulationCommand("night", "player", "SUPPORT_ANOMALY", self.state.revision,
            parameters={"npc_id": self.target, "case_id": self.case_id, "expected_case_revision": 0},
            issued_day=self.state.clock.day, issued_phase="evening"))
        self.assertEqual("daytime_required", outcome.code)

    def test_three_day_support_and_stale_statements_need_renewal(self):
        # Controlled multi-day handler boundary; natural clock/AI is exercised
        # separately by the complete unattended soak. Do not falsify world clocks
        # inside a kernel transaction whose other systems have not advanced.
        policy = load_action_economy_policy(self.bridge.registry)
        def execute(action):
            return make_anomaly_handler()(self.context(), SimulationCommand("dated-support", "player", action, self.state.revision,
                parameters={"npc_id": self.target, "case_id": self.case_id, "expected_case_revision": self.case["revision"]},
                issued_day=self.state.clock.day, issued_phase=self.state.clock.phase))
        for index in range(3):
            if index:
                self.state.clock.day += 1
                reset_all_actor_budgets(self.state, policy)
                self.assertEqual("fresh_report_required", execute("SUPPORT_ANOMALY").code)
            self.assertTrue(execute("ASK_ANOMALY_EXPERIENCE").success)
            result = execute("SUPPORT_ANOMALY")
            self.assertTrue(result.success, result.code)
        self.assertEqual("resolved", self.case["status"])
        self.assertEqual([2, 3, 4], [r["day"] for r in self.case["history"]])
        self.assertEqual([], anomalies_invariant(self.state))
        execute("ASK_ANOMALY_EXPERIENCE")
        self.assertIn("正常生活", anomaly_view(self.state)[0]["report"]["summary"])

    def test_npc_same_handler_and_cost_without_player_participation(self):
        _topic_progress(_actor_growth(self.state, self.helper), self.case["topic_id"])["theory"] = 20
        # Explicit free-slot boundary, after verifying that auto-support never
        # displaces a protected class. The original fixture is a weekday dawn.
        weekly = str((self.state.clock.day - 1) % 7)
        self.state.population[self.target]["weekly_schedule"][weekly][self.state.clock.phase]["priority"] = 95
        self.assertEqual(0, advance_anomaly_support(self.context())["anomaly_supports"])
        for who in (self.target, self.helper):
            self.state.population[who]["weekly_schedule"][weekly][self.state.clock.phase]["priority"] = 20
        before = deepcopy(self.state.population["player"])
        result = advance_anomaly_support(self.context())
        self.assertEqual(1, result["anomaly_supports"])
        self.assertEqual(self.helper, self.case["history"][0]["helper_id"])
        self.assertEqual([], anomaly_view(self.state))
        self.assertEqual(0, self.state.action_economy["actors"][self.helper]["major_remaining"])
        self.assertEqual(before, self.state.population["player"])
        self.assertEqual(0, advance_anomaly_support(self.context())["anomaly_supports"])
        self.assertEqual([], anomalies_invariant(self.state))

    def test_checkpoint_integrity_and_no_legacy_backlog(self):
        self.ask()
        self.support()
        with TemporaryDirectory() as directory:
            path = Path(directory) / "anomaly.json"
            save_kernel_checkpoint(path, self.state, DeterministicRngPool(42))
            restored = load_kernel_checkpoint(path).state
            self.assertEqual(self.state.situations["campus_anomalies"], restored.situations["campus_anomalies"])
            self.assertEqual([], anomalies_invariant(restored))
            restored.situations["campus_anomalies"]["cases"][self.case_id]["core"] = 0
            self.assertTrue(anomalies_invariant(restored))
        self.state.situations.pop("campus_anomalies")
        self.state.clock.day = 12
        self.assertEqual({}, sync_anomaly_cases(self.context())["cases"])

    def test_uninformed_person_cannot_act_using_leaked_case_id(self):
        self.assertEqual("fresh_report_required", self.support().code)
        self.ask()
        self.state.knowledge["beliefs_by_actor"]["player"][self.case["reports"]["player"]["claim_id"]]["distortion"] = .7
        self.assertEqual("reliable_report_required", self.support().code)
        self.assertEqual(0, self.case["revision"])

    def test_actual_reading_supplies_required_understanding_and_cost(self):
        _topic_progress(_actor_growth(self.state, "player"), self.case["topic_id"])["theory"] = 0
        self.ask()
        self.assertEqual("knowledge_required", self.support().code)
        travel_to_location(self.bridge, "library_reading_hall")
        result = command(self.bridge, "READ_KNOWLEDGE", {"topic_id": self.case["topic_id"]})
        self.assertTrue(result["ok"], result["result"])
        self.assertEqual(20, result["result"]["payload"]["mastery"])
        self.assertEqual(0, self.state.action_economy["actors"]["player"]["major_remaining"])
        self.assertEqual(0, self.case["revision"])


if __name__ == "__main__":
    unittest.main()
