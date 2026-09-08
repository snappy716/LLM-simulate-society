"""Explicit compatible-schedule fixtures; natural simulations are tested separately."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from simulation.api.server import CampusKernelBridge
from simulation.actions.commands import SimulationCommand
from simulation.systems import ContentRegistry, DeterministicRngPool
from simulation.systems.transactions import TransactionContext
from simulation.systems.campus_messaging import load_campus_messaging_policy
from simulation.systems.campus_social import DEFAULT_RELATIONSHIP
from simulation.systems.campus_social_coordination import (
    coordinate_daily_social, coordination_invariant, describe_confirmed_arrangement)
from simulation.systems.campus_interactions import advance_campus_interactions, load_campus_interaction_policy
from simulation.systems.campus_intelligence import load_campus_intelligence_policy
from simulation.persistence.kernel_checkpoint import save_kernel_checkpoint, load_kernel_checkpoint
from tests.test_campus_cognition import command
from tests.test_campus_social_planning import SocialProvider


def prepare_fixture(bridge):
    if "daily_plans" not in bridge.kernel._state.cognition:
        assert command(bridge, "ADVANCE_PHASE")["ok"]
    state = bridge.kernel._state
    contacts = state.cognition["messaging"]["contacts_by_actor"]
    free = lambda n: n != "player" and not state.population[n].get("active_forum_task_id")
    actor = next(n for n in state.population if free(n) and any(free(t) for t in contacts[n]))
    target = next(t for t in contacts[actor] if free(t))
    plans = state.cognition["daily_plans"]["actors"]
    phase = "evening"
    location = plans[target][phase]["location_id"]
    plans[actor][phase]["location_id"] = location
    plans[actor][phase]["social_intent"] = {"target_id": target, "target_name": state.population[target]["display_name"],
        "phase": phase, "location_id": location, "intent_id": "small_talk", "reason": "聊聊近况",
        "candidate_id": "fixture", "model_reason": "explicit_test_fixture", "fallback": "wait_next_day"}
    state.relationships[target][actor] = {**DEFAULT_RELATIONSHIP, "trust": 80, "closeness": 50}
    state.population[target]["needs"].update(rest=0, food=0, safety=0)
    registry = ContentRegistry.load_default(Path(__file__).resolve().parents[1] / "content")
    context = TransactionContext(state, DeterministicRngPool(42), SimulationCommand("coordination-fixture", "player", "ADVANCE_PHASE", state.revision))
    return state, actor, target, plans, registry, context


class CoordinationTests(unittest.TestCase):
    def setUp(self):
        self.bridge = CampusKernelBridge(42)
        self.state, self.actor, self.target, self.plans, self.registry, self.context = prepare_fixture(self.bridge)
        self.policy = load_campus_messaging_policy(self.registry)

    def coordinate(self):
        coordinate_daily_social(self.context, self.plans, self.policy)
        return self.state.cognition.get("social_coordination", {}).get("actors", {}).get(self.actor, {})

    def test_confirmed_private_messages_immutable_plans_and_single_shot(self):
        before = deepcopy(self.plans)
        self.assertEqual("confirmed", self.coordinate()["status"])
        sequence = self.state.cognition["messaging"]["message_sequence"]
        self.coordinate()
        self.assertEqual(sequence, self.state.cognition["messaging"]["message_sequence"])
        self.assertEqual(before, self.plans)
        self.assertEqual([], list(coordination_invariant(self.state)))
        self.assertTrue(all(e.visibility == "private" and "player" not in (*e.actor_ids, *e.target_ids) for e in self.context.event_drafts))
        self.assertIn("已经和一位认识的人约好", describe_confirmed_arrangement(self.state, self.actor))
        self.assertIn(self.state.population[self.actor]["display_name"], describe_confirmed_arrangement(self.state, self.target, True))
        self.assertEqual("", describe_confirmed_arrangement(self.state, "player", True))

    def test_schedule_and_relationship_declines_do_not_force_change(self):
        self.plans[self.target]["evening"]["location_id"] = next(p for p in self.state.places if p != self.plans[self.actor]["evening"]["location_id"])
        before = deepcopy(self.plans)
        self.assertEqual("schedule_conflict", self.coordinate()["reason"])
        self.assertEqual(before, self.plans)
        self.state.cognition.pop("social_coordination")
        self.plans[self.target]["evening"]["location_id"] = self.plans[self.actor]["evening"]["location_id"]
        self.state.relationships[self.target][self.actor]["trust"] = 0
        self.assertEqual("unwilling", self.coordinate()["reason"])

    def test_missing_contacts_never_send_or_add(self):
        contacts = self.state.cognition["messaging"]["contacts_by_actor"]
        contacts[self.actor].remove(self.target)
        before = deepcopy(self.state.cognition["messaging"])
        self.assertEqual({}, self.coordinate())
        self.assertEqual(before, self.state.cognition["messaging"])

    def test_reciprocal_invitations_do_not_double_book(self):
        social = deepcopy(self.plans[self.actor]["evening"]["social_intent"])
        social.update(target_id=self.actor, target_name=self.state.population[self.actor]["display_name"])
        self.plans[self.target]["evening"]["social_intent"] = social
        self.state.relationships[self.actor][self.target] = {**DEFAULT_RELATIONSHIP, "trust": 80, "closeness": 50}
        self.state.population[self.actor]["needs"].update(rest=0, food=0, safety=0)
        self.coordinate()
        records = self.state.cognition["social_coordination"]["actors"]
        self.assertEqual(1, sum(r["status"] == "confirmed" for r in records.values()))
        self.assertEqual([], list(coordination_invariant(self.state)))

    def test_interruption_cancels_once_without_teleport_and_roundtrips(self):
        self.coordinate()
        self.state.clock.phase = "evening"
        for person in self.state.population.values():
            person["current_activity"] = {"status": "blocked"}
        location = next(p for p in self.state.places if p != self.plans[self.actor]["evening"]["location_id"])
        self.state.population[self.target]["current_location_id"] = location
        policy = load_campus_interaction_policy(self.registry)
        intelligence = load_campus_intelligence_policy(self.registry)
        for _ in range(2):
            advance_campus_interactions(self.context, policy, intelligence)
        self.assertEqual(location, self.state.population[self.target]["current_location_id"])
        self.assertEqual("not_met", self.state.cognition["social_agenda_receipts"]["actors"][self.actor]["status"])
        cancelled = [m for m in self.state.cognition["messaging"]["messages"].values() if m["source"] == "social_appointment_cancelled"]
        self.assertEqual(1, len(cancelled))
        self.assertEqual("", describe_confirmed_arrangement(self.state, self.target, True))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "coordinated.json"
            state, rng = self.bridge.kernel.capture_checkpoint()
            save_kernel_checkpoint(path, state, rng)
            restored = load_kernel_checkpoint(path).state
            self.assertEqual(self.state.cognition["social_coordination"], restored.cognition["social_coordination"])
        self.state.cognition["social_coordination"]["actors"][self.actor]["target_id"] = "player"
        self.assertIn("invalid social coordination record", list(coordination_invariant(self.state)))

    def test_multiday_feedback_and_no_daytime_model_requests(self):
        bridge = CampusKernelBridge(42)
        provider = SocialProvider()
        bridge.cognition_runtime.provider = provider
        for _ in range(4):
            self.assertTrue(command(bridge, "ADVANCE_PHASE")["ok"])
        count = len(provider.requests), len(provider.dialogue_requests)
        for _ in range(3):
            self.assertTrue(command(bridge, "ADVANCE_PHASE")["ok"])
        self.assertEqual(count, (len(provider.requests), len(provider.dialogue_requests)))
        previous = deepcopy(bridge.kernel.state.cognition["social_agenda_receipts"])
        start = len(provider.requests)
        self.assertTrue(command(bridge, "ADVANCE_PHASE")["ok"])
        requests = [r for r in provider.requests[start:] if r.daily_options is not None]
        self.assertEqual(20, len(requests))
        self.assertTrue(any("previous_social_attempt" in r.state for r in requests))
        for request in requests:
            if "previous_social_attempt" in request.state:
                self.assertEqual({"day": previous["day"], **previous["actors"][request.npc_id]}, request.state["previous_social_attempt"])


if __name__ == "__main__":
    unittest.main()
