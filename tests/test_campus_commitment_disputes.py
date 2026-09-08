from copy import deepcopy
import unittest
from uuid import uuid4

from simulation.api.server import CampusKernelBridge
from simulation.actions.commands import SimulationCommand
from simulation.systems import DeterministicRngPool
from simulation.systems.transactions import TransactionContext
from simulation.systems.campus_disputes import record_failed_commitment, dispute_view, disputes_invariant, advance_dispute_mediation
from simulation.systems.campus_messaging import _add_contact
from simulation.systems.campus_social import DEFAULT_RELATIONSHIP
from simulation.systems.campus_schedules import current_schedule_slot
from tests.test_campus_disputes import command


def prepare_commitment_fixture(bridge):
    state = bridge.kernel._state
    task = next(iter(state.tasks.values()))
    assignee = next(n for n, p in state.population.items() if n not in ("player", task["issuer_id"])
        and p.get("role_kind") == "student" and current_schedule_slot(state, n).get("priority", 0) < 90)
    result = bridge.execute({"command_id": str(uuid4()), "actor_id": assignee, "source": "rule", "action_id": "CLAIM_FORUM_TASK",
        "parameters": {"task_id": task["task_id"], "expected_task_revision": task["lock_revision"]}, "target_ids": [],
        "expected_world_revision": state.revision, "issued_day": state.clock.day, "issued_phase": state.clock.phase, "issued_minute": 0})
    assert result["ok"], result["result"]["code"]
    state = bridge.kernel._state
    task = state.tasks[task["task_id"]]
    # Explicit delayed execution boundary, not a claim that this happens naturally.
    task["npc_execute_after_phase_index"] = 100
    task_id, issuer, expires = task["task_id"], task["issuer_id"], task["expires_day"]
    while bridge.kernel._state.clock.day <= expires:
        assert command(bridge, "ADVANCE_PHASE", {})["ok"]
    state = bridge.kernel._state
    case = next(c for c in state.situations["campus_disputes"]["cases"].values()
        if any(r.get("task_id") == task_id for r in c.get("source_refs", [])))
    for who in (issuer, assignee):
        _add_contact(state, "player", who)
        state.relationships[who]["player"] = {**DEFAULT_RELATIONSHIP, "trust": 70}
        state.population[who]["emotions"]["anger"] = 20
    return state, task_id, issuer, assignee, case


class CommitmentDisputesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        bridge = CampusKernelBridge(42)
        _, cls.task_id, cls.issuer, cls.assignee, case = prepare_commitment_fixture(bridge)
        cls.case_id = case["case_id"]
        cls.baseline, cls.rng = bridge.kernel.capture_checkpoint()

    def setUp(self):
        self.bridge = CampusKernelBridge(42)
        self.bridge.kernel.restore_checkpoint(self.baseline, self.rng, expected_revision=self.bridge.kernel.state.revision)

    def ask(self, who):
        return command(self.bridge, "ASK_NPC_DISPUTE", {"npc_id": who, "case_id": self.case_id})

    def review(self):
        return command(self.bridge, "REVIEW_DISPUTE_RECORD", {"case_id": self.case_id})

    def mediate(self):
        case = self.bridge.kernel._state.situations["campus_disputes"]["cases"][self.case_id]
        return command(self.bridge, "MEDIATE_DISPUTE", {"case_id": self.case_id, "expected_case_revision": case["revision"]})

    def test_actual_claim_expiry_private_source_no_extra_penalty(self):
        state = self.bridge.kernel._state
        task = state.tasks[self.task_id]
        self.assertEqual("expired", task["state"])
        self.assertIn("claimed", [r["kind"] for r in task["history"]])
        self.assertIn("expired", [r["kind"] for r in task["history"]])
        self.assertEqual([], dispute_view(state))
        before = deepcopy(state.relationships)
        count = len(state.situations["campus_disputes"]["cases"])
        context = TransactionContext(state, DeterministicRngPool(42), SimulationCommand("repeat", "player", "ADVANCE_PHASE", state.revision))
        record_failed_commitment(context, task)
        self.assertEqual(before, state.relationships)
        self.assertEqual(count, len(state.situations["campus_disputes"]["cases"]))
        self.assertFalse(context.event_drafts)
        self.assertEqual([], list(disputes_invariant(state)))

    def test_no_unclaimed_or_player_or_nonexpired_cases(self):
        state = self.bridge.kernel._state
        before = len(state.situations["campus_disputes"]["cases"])
        context = TransactionContext(state, DeterministicRngPool(42), SimulationCommand("ignored", "player", "ADVANCE_PHASE", state.revision))
        task = state.tasks[self.task_id]
        original = deepcopy(task)
        for changes in ({"assignee_id": None}, {"assignee_id": "player"}, {"state": "completed"}, {"forum": "night"}):
            task.update(changes)
            record_failed_commitment(context, task)
            task.clear()
            task.update(deepcopy(original))
        self.assertEqual(before, len(state.situations["campus_disputes"]["cases"]))
        self.assertFalse(context.event_drafts)

    def test_review_and_both_statements_required_no_fake_completion_or_reward(self):
        self.assertEqual("unknown_dispute", self.review()["result"]["code"])
        self.assertTrue(self.ask(self.issuer)["ok"])
        self.assertTrue(self.ask(self.assignee)["ok"])
        self.assertEqual("public_record_required", self.mediate()["result"]["code"])
        before = self.bridge.kernel.state
        self.assertTrue(self.review()["ok"])
        reviewed = self.bridge.kernel.state
        row = reviewed.situations["campus_disputes"]["cases"][self.case_id]["record_reviews"]["player"]
        self.assertTrue(row["claim_ids"])
        self.assertEqual(self.task_id, reviewed.knowledge["claims"][row["claim_ids"][0]]["object_id"])
        self.assertEqual("already_reviewed", self.review()["result"]["code"])
        self.assertTrue(self.mediate()["ok"])
        after = self.bridge.kernel.state
        self.assertEqual(before.clock, after.clock)
        self.assertEqual(before.action_economy, after.action_economy)
        self.assertEqual(before.inventories, after.inventories)
        self.assertEqual(before.tasks, after.tasks)
        self.assertEqual([p["wealth"] for p in before.population.values()], [p["wealth"] for p in after.population.values()])

    def test_declined_statement_does_not_disclose_task_record(self):
        self.bridge.kernel._state.relationships[self.issuer]["player"]["trust"] = 0
        self.assertEqual("statement_withheld", self.ask(self.issuer)["result"]["code"])
        self.assertEqual("unknown_dispute", self.review()["result"]["code"])
        self.assertEqual([], self.bridge.snapshot()["social"]["disputes"])

    def test_npc_mediator_reviews_public_source_before_same_rule_settlement(self):
        state = self.bridge.kernel._state
        helper = next(n for n in state.population if n not in ("player", self.issuer, self.assignee))
        for party in (self.issuer, self.assignee):
            _add_contact(state, party, helper)
            state.relationships[party][helper] = {**DEFAULT_RELATIONSHIP, "trust": 80}
        state.population[helper]["personality"]["altruism"] = 100
        state.population[helper]["attributes"]["empathy"] = 10
        self.assertTrue(command(self.bridge, "ADVANCE_PHASE", {})["ok"])
        state = self.bridge.kernel.state
        case = state.situations["campus_disputes"]["cases"][self.case_id]
        self.assertTrue(case["record_reviews"])
        self.assertIn(case["status"], ("settled", "easing"))
        self.assertEqual("expired", state.tasks[self.task_id]["state"])
        self.assertEqual([], dispute_view(state))

    def test_unknown_record_source_is_not_authoritative(self):
        state = self.bridge.kernel._state
        context = TransactionContext(state, DeterministicRngPool(42), SimulationCommand("forged", "player", "ADVANCE_PHASE", state.revision))
        record_failed_commitment(context, {**state.tasks[self.task_id], "task_id": "fake-claim"})
        self.assertFalse(context.event_drafts)


if __name__ == "__main__":
    unittest.main()
