"""Read-only candidate/motive fixtures, not natural social-frequency evidence."""
from collections import Counter
from copy import deepcopy
from types import SimpleNamespace
import unittest

from simulation.api.server import CampusKernelBridge
from simulation.systems import load_campus_location_graph, load_campus_activity_definitions, load_campus_decision_policy
from simulation.systems.campus_outings import outing_candidates, companionship_motivation, willing


class SocialPacingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = CampusKernelBridge(42)
        cls.initial = cls.bridge.kernel.state
        cls.graph = load_campus_location_graph(cls.bridge.registry)
        definitions = load_campus_activity_definitions(cls.bridge.registry)
        cls.policy = load_campus_decision_policy(cls.bridge.registry, definitions, cls.graph)

    def setUp(self):
        self.state = self.initial.clone()
        self.state.clock.phase = "evening"
        contacts = self.state.cognition["messaging"]["contacts_by_actor"]
        self.actor, self.other = next((actor, other) for actor, others in contacts.items() for other in others
            if actor != "player" and other != "player"
            and self.state.population[actor]["role_kind"] == self.state.population[other]["role_kind"] == "student"
            and self.state.population[actor]["college_id"] == self.state.population[other]["college_id"])
        for who in (self.actor, self.other):
            self.state.population[who]["needs"].update(rest=20, food=20, safety=20, social=60)
            self.state.population[who]["personality"]["extraversion"] = 60
            self.state.action_economy["actors"][who]["major_remaining"] = 1
            for day in self.state.population[who]["weekly_schedule"].values():
                for slot in day.values(): slot["priority"] = 10
        self.state.relationships[self.actor].pop(self.other, None)
        self.state.relationships[self.other].pop(self.actor, None)
        # Isolate one real existing contact so unrelated, higher-scored peers
        # do not consume the intentionally bounded three-person candidate pool.
        self.state.cognition["messaging"]["contacts_by_actor"][self.actor] = [self.other]

    def choices(self, priority=10):
        return outing_candidates(SimpleNamespace(state=self.state), self.actor, {"priority": priority},
            self.graph, Counter(), self.policy, 100)

    def test_existing_cohort_contact_without_affinity_row_can_be_invited(self):
        before = deepcopy(self.state.relationships)
        self.assertTrue(willing(self.state, self.actor, self.other, "companionship"))
        self.assertTrue(any(r["parameters"]["outing_intent"]["target_id"] == self.other for r in self.choices()))
        self.assertEqual(before, self.state.relationships)
        self.assertFalse(willing(self.state, self.actor, self.other, "date"))

    def test_no_stranger_or_automatic_contact_creation(self):
        other = next(n for n in self.state.population if n not in self.state.cognition["messaging"]["contacts_by_actor"][self.actor]
            and n != self.actor)
        self.state.relationships[self.actor][other] = {"closeness": 100, "familiarity": 100}
        contacts = deepcopy(self.state.cognition["messaging"]["contacts_by_actor"])
        self.assertFalse(any(r["parameters"]["outing_intent"]["target_id"] == other for r in self.choices()))
        self.assertEqual(contacts, self.state.cognition["messaging"]["contacts_by_actor"])

    def test_emergency_distrust_and_protected_duties_still_block(self):
        self.assertEqual([], self.choices(90))
        self.state.population[self.actor]["needs"]["safety"] = 95
        self.assertFalse(willing(self.state, self.actor, self.other, "companionship"))
        self.state.population[self.actor]["needs"]["safety"] = 20
        self.state.relationships[self.actor][self.other] = {"familiarity": 80, "trust": 20}
        self.assertFalse(willing(self.state, self.actor, self.other, "companionship"))

    def test_shared_time_not_short_chat_meter_changes_motivation(self):
        first = companionship_motivation(self.state, self.actor, self.other)
        self.state.clock.day = 7
        later = companionship_motivation(self.state, self.actor, self.other)
        self.assertGreater(later["meaningful_shared_time"], first["meaningful_shared_time"])
        self.state.population[self.actor]["needs"]["social"] = 0
        self.assertEqual(later, companionship_motivation(self.state, self.actor, self.other))

    def test_only_completed_shared_time_reduces_maintenance_pressure(self):
        self.state.clock.day = 7
        # Minimal records exercise the pure projection, not the transaction
        # invariant. Natural audits use exclusively real settled receipts.
        row = {"proposer_id": self.actor, "recipient_id": self.other, "status": "pending", "day": 7}
        self.state.situations["campus_outings"] = {"records": {"fixture": row}}
        pending = companionship_motivation(self.state, self.actor, self.other)
        row["status"] = "declined"
        self.assertEqual(pending, companionship_motivation(self.state, self.actor, self.other))
        row["status"] = "completed"
        completed = companionship_motivation(self.state, self.actor, self.other)
        self.assertEqual(0, completed["meaningful_shared_time"])
        self.assertLess(sum(completed.values()), sum(pending.values()))

    def test_existing_contact_order_does_not_change_candidates(self):
        before = self.choices()
        self.state.cognition["messaging"]["contacts_by_actor"][self.actor].reverse()
        self.assertEqual(before, self.choices())
        self.assertTrue(all(r["action_class"] == "major" for r in before))


if __name__ == "__main__": unittest.main()
