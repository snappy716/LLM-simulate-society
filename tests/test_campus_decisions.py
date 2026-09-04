from __future__ import annotations

import tempfile
import unittest
from collections import Counter
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from simulation.api.server import CampusKernelBridge
from simulation.systems import (
    ContentRegistry,
    DeterministicRngPool,
    choose_campus_npc_activity,
    current_schedule_slot,
    load_campus_activity_definitions,
    load_campus_decision_policy,
    load_campus_location_graph,
)


REPOSITORY_DIR = Path(__file__).resolve().parents[1]


class CampusDecisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = ContentRegistry.load_default(REPOSITORY_DIR / "content")
        cls.graph = load_campus_location_graph(cls.registry)
        cls.definitions = load_campus_activity_definitions(cls.registry)
        cls.policy = replace(
            load_campus_decision_policy(cls.registry, cls.definitions, cls.graph),
            score_jitter=0,
        )

    def decision_for(self, state, actor_id: str, plan: dict) -> dict:
        context = SimpleNamespace(
            state=state,
            rng=DeterministicRngPool(state.master_seed),
        )
        result = choose_campus_npc_activity(
            context,
            actor_id,
            plan,
            self.graph,
            self.definitions,
            self.policy,
            Counter(),
        )
        self.assertIsNotNone(result)
        return result

    def test_policy_declares_legal_data_driven_candidates(self):
        self.assertEqual(9, len(self.policy.alternatives))
        self.assertEqual(
            {
                "REST",
                "SELF_STUDY",
                "SOCIAL_OR_SELF_STUDY",
                "CLUB_OR_PERSONAL_ACTIVITY",
                "CLUB_OR_SELF_STUDY",
                "CLUB_ACTIVITY",
                "PERSONAL_ACTIVITY",
                "CAMPUS_EXPLORATION",
                "CAMPUS_SERVICE_SHIFT",
            },
            {item.activity_id for item in self.policy.alternatives},
        )

    def test_high_priority_duty_is_protected_but_emergency_rest_can_override(self):
        bridge = CampusKernelBridge(42)
        state = bridge.kernel.state
        actor_id = next(
            actor_id
            for actor_id, actor in state.population.items()
            if isinstance(actor, dict) and actor.get("occupation_id") == "administration_staff"
        )
        plan = current_schedule_slot(state, actor_id)
        self.assertGreaterEqual(plan["priority"], 90)
        protected = self.decision_for(state, actor_id, plan)
        self.assertEqual("schedule", protected["decision_source"])
        self.assertEqual(plan["activity_id"], protected["activity_id"])

        actor = state.population[actor_id]
        actor["needs"].update({
            "rest": 100,
            "food": 0,
            "safety": 0,
            "money": 0,
            "achievement": 0,
            "curiosity": 0,
            "commitment_pressure": 0,
        })
        actor["emotions"].update({"fear": 0, "anger": 0, "sadness": 0, "shame": 0})
        actor["personality"]["conscientiousness"] = 0
        actor["core_values"] = ["freedom", "security"]
        emergency = self.decision_for(state, actor_id, plan)
        self.assertEqual("REST", emergency["activity_id"])
        self.assertEqual("rest_need", emergency["decision_reason"])

    def test_social_need_can_replace_a_low_priority_personal_plan(self):
        bridge = CampusKernelBridge(7)
        state = bridge.kernel.state
        actor_id = "campus_student_001"
        actor = state.population[actor_id]
        actor["needs"].update({
            "rest": 0,
            "food": 0,
            "safety": 0,
            "social": 100,
            "money": 0,
            "achievement": 0,
            "curiosity": 0,
            "commitment_pressure": 0,
        })
        actor["personality"]["extraversion"] = 100
        plan = {
            "activity_id": "REST",
            "action_class": "free",
            "location_id": actor["home_location_id"],
            "priority": 20,
        }
        chosen = self.decision_for(state, actor_id, plan)
        self.assertEqual("SOCIAL_OR_SELF_STUDY", chosen["activity_id"])
        self.assertEqual("social_need", chosen["decision_reason"])

    def test_seven_day_cycle_is_deterministic_legal_and_mixed(self):
        first = CampusKernelBridge(42)
        first_trace: list[tuple] = []
        totals = Counter()
        for step in range(28):
            snapshot = first.snapshot()
            clock = snapshot["clock"]
            result = first.execute({
                "command_id": f"seven-day-{step}",
                "actor_id": "player",
                "action_id": "ADVANCE_PHASE",
                "target_ids": [],
                "parameters": {},
                "expected_world_revision": snapshot["revision"],
                "issued_day": clock["day"],
                "issued_phase": clock["phase"],
                "issued_minute": clock["minute"],
                "source": "player",
            })
            self.assertTrue(result["ok"])
            execution = result["result"]["payload"]["phase_execution"]
            self.assertEqual(200, execution["planned_actor_count"])
            self.assertEqual(0, execution["blocked_actor_count"])
            self.assertEqual(
                200,
                execution["major_activity_count"] + execution["free_activity_count"],
            )
            first_trace.append((
                execution["schedule_follow_count"],
                execution["rule_choice_count"],
                execution["task_choice_count"],
                tuple(sorted(execution["decision_reason_counts"].items())),
            ))
            totals.update({
                "schedule": execution["schedule_follow_count"],
                "rule": execution["rule_choice_count"],
                "task": execution["task_choice_count"],
            })
            state = first.kernel.state
            for actor_id, actor in state.population.items():
                if actor_id == "player":
                    continue
                decision = actor["current_decision"]
                activity = actor["current_activity"]
                self.assertEqual("completed", activity["status"], actor_id)
                self.assertEqual(decision["activity_id"], activity["activity_id"], actor_id)
                self.assertEqual(decision["location_id"], actor["current_location_id"], actor_id)
        second = CampusKernelBridge(42)
        second_trace: list[tuple] = []
        for step in range(4):
            snapshot = second.snapshot()
            clock = snapshot["clock"]
            result = second.execute({
                "command_id": f"seven-day-{step}",
                "actor_id": "player",
                "action_id": "ADVANCE_PHASE",
                "target_ids": [],
                "parameters": {},
                "expected_world_revision": snapshot["revision"],
                "issued_day": clock["day"],
                "issued_phase": clock["phase"],
                "issued_minute": clock["minute"],
                "source": "player",
            })
            execution = result["result"]["payload"]["phase_execution"]
            second_trace.append((
                execution["schedule_follow_count"],
                execution["rule_choice_count"],
                execution["task_choice_count"],
                tuple(sorted(execution["decision_reason_counts"].items())),
            ))
        self.assertEqual(first_trace[:4], second_trace)
        self.assertGreater(totals["schedule"], 0)
        self.assertGreater(totals["rule"], 0)

        public_plan = first.snapshot()["population"]["campus_student_001"]["current_plan"]
        self.assertNotIn("score", public_plan)
        self.assertNotIn("score_contributions", public_plan)


if __name__ == "__main__":
    unittest.main()
