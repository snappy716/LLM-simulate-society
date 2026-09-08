from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from simulation.api.server import CampusKernelBridge
from simulation.actions.commands import SimulationCommand
from simulation.systems import ContentRegistry, DeterministicRngPool
from simulation.systems.transactions import TransactionContext
from simulation.systems.campus_disputes import record_dispute, advance_dispute_mediation, disputes_invariant, dispute_view
from simulation.systems.campus_interactions import _resolve_interaction, load_campus_interaction_policy
from simulation.systems.campus_intelligence import load_campus_intelligence_policy
from simulation.systems.campus_messaging import _add_contact, load_campus_messaging_policy
from simulation.systems.campus_social import DEFAULT_RELATIONSHIP
from simulation.persistence.kernel_checkpoint import save_kernel_checkpoint, load_kernel_checkpoint
from simulation.domain.cognition import BoundedDecisionRequest, BoundedDialogueRequest
from simulation.systems.campus_cognition import bind_cognition_identity


def command(bridge, action_id, parameters):
    snapshot = bridge.snapshot()
    clock = snapshot["clock"]
    return bridge.execute({
        "command_id": f"dispute-{uuid4()}",
        "actor_id": "player", "action_id": action_id, "target_ids": [],
        "parameters": parameters, "expected_world_revision": snapshot["revision"],
        "issued_day": clock["day"], "issued_phase": clock["phase"],
        "issued_minute": clock["minute"], "source": "player",
    })


def prepare_dispute_fixture(bridge):
    """Explicit strained relationship; the actual resolver produces the dispute."""
    state = bridge.kernel._state
    first, second, helper = [n for n in state.population if n != "player"][:3]
    registry = ContentRegistry.load_default(Path(__file__).resolve().parents[1] / "content")
    context = TransactionContext(state, DeterministicRngPool(42), SimulationCommand("dispute-fixture", "player", "ADVANCE_PHASE", state.revision))
    for n in (first, second, helper):
        state.population[n]["current_location_id"] = state.population["player"]["current_location_id"]
        state.population[n]["current_activity"] = {"status": "completed", "day": state.clock.day,
            "phase": state.clock.phase, "route_step_count": 0,
            "location_id": state.population[n]["current_location_id"]}
    state.relationships[first][second] = {**DEFAULT_RELATIONSHIP, "conflict": 35}
    state.relationships[second][first] = {**DEFAULT_RELATIONSHIP, "conflict": 35}
    state.population[second]["personality"]["agreeableness"] = 0
    policy = load_campus_interaction_policy(registry)
    result = _resolve_interaction(context, first, second, {"intent_id": "confront"}, policy,
        source="rule", model_reason="", now=0, intelligence_policy=load_campus_intelligence_policy(registry))
    assert result["outcome"] == "rejected"
    case = next(iter(state.situations["campus_disputes"]["cases"].values()))
    for party in (first, second):
        state.population[party]["emotions"]["anger"] = 20
        for mediator in ("player", helper):
            state.relationships[party][mediator] = {**DEFAULT_RELATIONSHIP, "trust": 70, "closeness": 30}
            _add_contact(state, party, mediator)
    state.population[helper]["personality"]["altruism"] = 90
    return state, first, second, helper, case, context, registry


class DisputeTests(unittest.TestCase):
    def setUp(self):
        self.bridge = CampusKernelBridge(42)
        self.state, self.first, self.second, self.helper, self.case, self.context, self.registry = prepare_dispute_fixture(self.bridge)

    def ask(self, who):
        return command(self.bridge, "ASK_NPC_DISPUTE", {"npc_id": who, "case_id": self.case["case_id"]})

    def mediate(self):
        current = self.bridge.kernel._state.situations["campus_disputes"]["cases"][self.case["case_id"]]
        return command(self.bridge, "MEDIATE_DISPUTE", {"case_id": current["case_id"], "expected_case_revision": current["revision"]})

    def test_only_actual_unresolved_confrontation_creates_private_case(self):
        self.assertEqual([], dispute_view(self.state))
        record = deepcopy(self.state.cognition["interactions"]["recent"][-1])
        count = self.state.situations["campus_disputes"]["sequence"]
        record_dispute(self.context, record)
        self.assertEqual(count, self.state.situations["campus_disputes"]["sequence"])
        record.update(interaction_id="ordinary-refusal", intent_id="small_talk")
        record_dispute(self.context, record)
        self.assertEqual(count, self.state.situations["campus_disputes"]["sequence"])
        self.assertEqual([], list(disputes_invariant(self.state)))
        self.assertTrue(any(e.event_type == "CAMPUS_DISPUTE_OPENED" and e.visibility == "private" for e in self.context.event_drafts))

    def test_two_statements_required_free_mediation_reduces_conflict_no_rewards(self):
        before = self.bridge.kernel.state
        self.assertTrue(self.ask(self.first)["ok"])
        self.assertEqual("both_statements_required", self.mediate()["result"]["code"])
        self.assertTrue(self.ask(self.second)["ok"])
        self.assertTrue(self.mediate()["ok"])
        after = self.bridge.kernel.state
        self.assertLess(after.relationships[self.first][self.second]["conflict"], before.relationships[self.first][self.second]["conflict"])
        self.assertEqual(before.clock, after.clock)
        self.assertEqual(before.action_economy, after.action_economy)
        self.assertEqual(before.inventories, after.inventories)
        self.assertEqual(before.population["player"]["wealth"], after.population["player"]["wealth"])
        self.assertEqual("dispute_cooldown", self.mediate()["result"]["code"])

    def test_refusal_does_not_leak_other_party_and_changed_consent_has_no_effect(self):
        self.state.relationships[self.first]["player"]["trust"] = 0
        refused = self.ask(self.first)
        self.assertFalse(refused["ok"])
        self.assertEqual([], refused["snapshot"]["social"]["disputes"])
        self.state.relationships[self.first]["player"]["trust"] = 70
        self.assertTrue(self.ask(self.first)["ok"])
        self.assertTrue(self.ask(self.second)["ok"])
        self.bridge.kernel._state.population[self.second]["emotions"]["anger"] = 90
        before = deepcopy(self.bridge.kernel._state.relationships)
        result = self.mediate()
        self.assertEqual("declined", result["result"]["code"])
        self.assertEqual(before, self.bridge.kernel._state.relationships)

    def test_no_remote_interview_without_contacts_or_colocation(self):
        state = self.state
        state.cognition["messaging"]["contacts_by_actor"]["player"].remove(self.first)
        state.population[self.first]["current_location_id"] = next(p for p in state.places if p != state.population["player"]["current_location_id"])
        self.assertEqual("not_available", self.ask(self.first)["result"]["code"])
        self.assertEqual([], dispute_view(self.bridge.kernel.state))

    def test_new_confrontation_invalidates_old_statements_and_checkpoint(self):
        self.assertTrue(self.ask(self.first)["ok"])
        self.assertTrue(self.ask(self.second)["ok"])
        state = self.bridge.kernel._state
        context = TransactionContext(state, DeterministicRngPool(42), self.context.command)
        record = {**state.cognition["interactions"]["recent"][-1], "interaction_id": "controlled-second-confrontation"}
        record_dispute(context, record)
        self.assertEqual("both_statements_required", self.mediate()["result"]["code"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "disputes.json"
            saved, rng = self.bridge.kernel.capture_checkpoint()
            save_kernel_checkpoint(path, saved, rng)
            loaded = load_kernel_checkpoint(path).state
            self.assertEqual(saved.situations["campus_disputes"], loaded.situations["campus_disputes"])
        state.situations["campus_disputes"]["cases"][self.case["case_id"]]["parties"] = [self.first, "player"]
        self.assertIn("invalid dispute case", list(disputes_invariant(state)))

    def test_npc_help_and_mediation_use_same_handler_without_player(self):
        self.state.clock.phase = "afternoon"
        policy = load_campus_messaging_policy(self.registry)
        before = self.state.relationships[self.first][self.second]["conflict"]
        result = advance_dispute_mediation(self.context, policy)
        self.assertEqual(1, result["npc_dispute_attempts"])
        self.assertLess(self.state.relationships[self.first][self.second]["conflict"], before)
        messages = self.state.cognition["messaging"]["messages"].values()
        self.assertTrue(any(m["source"] == "dispute_help_request" and m["receiver_id"] == self.helper for m in messages))
        self.assertFalse(any("player" in (m["sender_id"], m["receiver_id"]) for m in messages))
        self.assertEqual([], dispute_view(self.state))
        self.assertEqual(0, advance_dispute_mediation(self.context, policy)["npc_dispute_attempts"])

    def test_parameters_and_integral_godot_version(self):
        self.assertEqual("invalid_parameters", command(self.bridge, "MEDIATE_DISPUTE", {"case_id": []})["result"]["code"])
        self.assertEqual("unknown_npc", command(self.bridge, "ASK_NPC_DISPUTE", {"npc_id": []})["result"]["code"])
        self.ask(self.first)
        self.ask(self.second)
        for revision in (True, "1", 1.5):
            self.assertEqual("dispute_revision_conflict", command(self.bridge, "MEDIATE_DISPUTE",
                {"case_id": self.case["case_id"], "expected_case_revision": revision})["result"]["code"])
        self.assertTrue(command(self.bridge, "MEDIATE_DISPUTE",
            {"case_id": self.case["case_id"], "expected_case_revision": 1.0})["ok"])

    def test_settlement_cannot_be_farmed_or_reopened_by_same_source(self):
        self.state.relationships[self.first][self.second]["conflict"] = 11
        self.state.relationships[self.second][self.first]["conflict"] = 11
        source = deepcopy(self.state.cognition["interactions"]["recent"][-1])
        self.ask(self.first)
        self.ask(self.second)
        self.assertEqual("settled", self.mediate()["result"]["code"])
        before = deepcopy(self.bridge.kernel._state.relationships)
        self.assertEqual("dispute_closed", self.mediate()["result"]["code"])
        self.assertEqual(before, self.bridge.kernel._state.relationships)
        state = self.bridge.kernel._state
        context = TransactionContext(state, DeterministicRngPool(42), self.context.command)
        record_dispute(context, source)
        self.assertEqual(1, len(state.situations["campus_disputes"]["cases"]))
        self.assertFalse(context.event_drafts)
        self.assertEqual("settled", dispute_view(state)[0]["status"])

    def test_overnight_context_contains_only_own_disputes_not_dialogue_leak(self):
        def request(actor):
            return BoundedDecisionRequest(actor, 1, 1, "morning", {}, {}, "", (), ())
        own = bind_cognition_identity(self.state, request(self.first))
        self.assertEqual(self.second, own.state["own_open_disputes"][0]["other_id"])
        other = bind_cognition_identity(self.state, request(self.helper))
        self.assertEqual([], other.state["own_open_disputes"])
        dialogue = BoundedDialogueRequest(self.first, "player", 1, 1, "morning", {}, {}, {}, (), "你好", (), "player", {})
        self.assertNotIn("own_open_disputes", bind_cognition_identity(self.state, dialogue).state)


if __name__ == "__main__":
    unittest.main()
