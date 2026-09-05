from __future__ import annotations

import unittest
from pathlib import Path

from simulation.actions.commands import SimulationCommand
from simulation.api.server import CampusKernelBridge
from simulation.systems import (
    ContentRegistry,
    DeterministicRngPool,
    TransactionContext,
    complete_assigned_task,
    load_campus_activity_definitions,
    load_campus_forum_policy,
    load_surface_task_templates,
    publish_emergent_surface_tasks,
)


REPOSITORY_DIR = Path(__file__).resolve().parents[1]


def command_for(state, command_id: str) -> SimulationCommand:
    return SimulationCommand(
        command_id=command_id,
        actor_id="player",
        action_id="ADVANCE_PHASE",
        expected_world_revision=state.revision,
        issued_day=state.clock.day,
        issued_phase=state.clock.phase,
        issued_minute=0,
        source="rule",
    )


def advance(bridge: CampusKernelBridge, step: int) -> dict:
    snapshot = bridge.snapshot()
    clock = snapshot["clock"]
    return bridge.execute({
        "command_id": f"emergent-phase-{step}-{snapshot['revision']}",
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


class CampusEmergentTaskTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = ContentRegistry.load_default(REPOSITORY_DIR / "content")
        cls.policy = load_campus_forum_policy(cls.registry)
        cls.templates = load_surface_task_templates(cls.registry)
        definitions = load_campus_activity_definitions(cls.registry)
        for template in cls.templates.values():
            template["allowed_phases"] = list(
                definitions[template["activity_id"]].allowed_phases
            )

    def test_real_need_publishes_a_bounded_task_and_completion_relaxes_it(self):
        state = CampusKernelBridge(5).kernel.state
        state.clock.day = 2
        state.clock.phase = "morning"
        state.cognition["interactions"]["hooks"].clear()
        for actor_id, actor in state.population.items():
            if actor_id != "player":
                actor["needs"].update({
                    "social": 0, "curiosity": 0, "commitment_pressure": 0, "safety": 0,
                })
        issuer_id = sorted(actor_id for actor_id in state.population if actor_id != "player")[0]
        state.population[issuer_id]["needs"]["social"] = 100
        context = TransactionContext(
            state, DeterministicRngPool(5), command_for(state, "publish-real-need")
        )
        published = publish_emergent_surface_tasks(context, self.templates, self.policy)
        self.assertEqual(1, len(published))
        task = state.tasks[published[0]]
        self.assertEqual("need", task["origin_kind"])
        self.assertEqual(f"need:{issuer_id}:social", task["origin_ref_id"])
        self.assertEqual(100, task["issuer_need_before"])
        self.assertEqual(issuer_id, task["issuer_id"])
        self.assertEqual("NPC 根据自己的实际需求或约定发布了任务。", task["history"][0]["message"])

        task["state"] = "locked"
        task["assignee_id"] = "player"
        state.population["player"]["active_forum_task_id"] = task["task_id"]
        self.assertTrue(complete_assigned_task(context, "player", {"task_id": task["task_id"]}))
        self.assertEqual(78, state.population[issuer_id]["needs"]["social"])
        self.assertEqual(-22, task["issuer_need_result"]["delta"])
        completion = next(
            draft for draft in context.event_drafts
            if draft.event_type == "FORUM_TASK_COMPLETED"
        )
        self.assertEqual(task["issuer_need_result"], completion.payload["issuer_need_result"])

        state.clock.day = 3
        day_three = TransactionContext(
            state, DeterministicRngPool(51), command_for(state, "need-cooldown-day-three")
        )
        self.assertEqual(
            [], publish_emergent_surface_tasks(day_three, self.templates, self.policy)
        )
        state.clock.day = 4
        day_four = TransactionContext(
            state, DeterministicRngPool(52), command_for(state, "need-cooldown-day-four")
        )
        self.assertEqual(
            1, len(publish_emergent_surface_tasks(day_four, self.templates, self.policy))
        )

    def test_unresolved_promise_becomes_a_preferred_but_competitive_task(self):
        state = CampusKernelBridge(6).kernel.state
        state.clock.day = 2
        state.clock.phase = "morning"
        for actor_id, actor in state.population.items():
            if actor_id != "player":
                actor["needs"].update({
                    "social": 0, "curiosity": 0, "commitment_pressure": 0, "safety": 0,
                })
        actor_id, target_id = sorted(
            actor_id for actor_id in state.population if actor_id != "player"
        )[:2]
        hook = {
            "hook_id": "social_hook:999999",
            "hook_type": "task_help",
            "actor_id": actor_id,
            "target_id": target_id,
            "created_day": 1,
            "created_phase": "late_night",
            "expires_phase_index": 12,
            "state": "open",
        }
        state.cognition["interactions"]["hooks"] = [hook]
        context = TransactionContext(
            state, DeterministicRngPool(6), command_for(state, "publish-promise")
        )
        published = publish_emergent_surface_tasks(context, self.templates, self.policy)
        self.assertEqual(1, len(published))
        task = state.tasks[published[0]]
        self.assertEqual("interaction_hook", task["origin_kind"])
        self.assertEqual(target_id, task["preferred_assignee_id"])
        self.assertEqual("task_posted", hook["state"])
        self.assertEqual(task["task_id"], hook["linked_task_id"])

        task["state"] = "locked"
        task["assignee_id"] = "player"
        state.population["player"]["active_forum_task_id"] = task["task_id"]
        self.assertTrue(complete_assigned_task(context, "player", {"task_id": task["task_id"]}))
        self.assertEqual("completed", hook["state"])

    def test_daily_integration_limits_hooks_and_exposes_safe_origin_text(self):
        bridge = CampusKernelBridge(42)
        published_events = []
        for step in range(4):
            result = advance(bridge, step)
            self.assertTrue(result["ok"])
            published_events.extend(
                event for event in result["result"]["events"]
                if event["event_type"] == "FORUM_TASK_PUBLISHED"
                and event.get("payload", {}).get("forum") == "surface"
            )
        self.assertGreater(len(published_events), 0)
        self.assertLessEqual(len(published_events), 4)
        snapshot = bridge.snapshot()
        emergent = [task for task in snapshot["tasks"].values() if task.get("origin_kind")]
        self.assertEqual(len(published_events), len(emergent))
        self.assertLessEqual(
            sum(task["origin_kind"] == "interaction_hook" for task in emergent), 2
        )
        self.assertGreaterEqual(sum(task["origin_kind"] == "need" for task in emergent), 1)
        self.assertTrue(all(task.get("origin_summary") for task in emergent))
        self.assertTrue(all("issuer_need_before" not in task for task in emergent))
        self.assertTrue(all("origin_ref_id" not in task for task in emergent))


if __name__ == "__main__":
    unittest.main()
