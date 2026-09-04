from __future__ import annotations

import json
import unittest
from pathlib import Path

from simulation.actions.commands import SimulationCommand
from simulation.api.server import CampusKernelBridge
from simulation.systems import (
    ContentRegistry,
    DeterministicRngPool,
    TransactionContext,
    advance_campus_interactions,
    campus_interaction_invariant,
    load_campus_intelligence_policy,
    load_campus_interaction_policy,
)
from simulation.systems.campus_social import DEFAULT_RELATIONSHIP
from simulation.systems.campus_tasks import phase_index


REPOSITORY_DIR = Path(__file__).resolve().parents[1]


def advance(bridge: CampusKernelBridge, step: int = 0) -> dict:
    snapshot = bridge.snapshot()
    clock = snapshot["clock"]
    return bridge.execute({
        "command_id": f"interaction-phase-{step}-{snapshot['revision']}",
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


class CampusInteractionIntegrationTests(unittest.TestCase):
    def test_phase_creates_colocated_atomic_interactions_memories_and_logs(self):
        bridge = CampusKernelBridge(42)
        result = advance(bridge)
        self.assertTrue(result["ok"])
        execution = result["result"]["payload"]["phase_execution"]
        events = [
            event for event in result["result"]["events"]
            if event["event_type"] == "NPC_INTERACTION_RESOLVED"
        ]
        self.assertEqual(execution["interaction_count"], len(events))
        self.assertGreater(len(events), 0)
        self.assertLessEqual(len(events), 12)
        schema = json.loads(
            (REPOSITORY_DIR / "contracts/npc_interaction.schema.json").read_text(encoding="utf-8")
        )
        state = bridge.kernel.state
        for event in events:
            actor_id = event["actor_ids"][0]
            target_id = event["target_ids"][0]
            self.assertNotEqual(actor_id, target_id)
            self.assertEqual(event["scene_id"], state.population[actor_id]["current_location_id"])
            self.assertEqual(event["scene_id"], state.population[target_id]["current_location_id"])
            self.assertIn(target_id, state.relationships[actor_id])
            self.assertIn(actor_id, state.relationships[target_id])
            self.assertEqual(set(schema["required"]), set(event["payload"]))
            self.assertTrue(any(
                state.chronicles["entries"][entry_id]["event_type"] == "NPC_INTERACTION_RESOLVED"
                for entry_id in state.chronicles["by_actor"][actor_id]
            ))
            self.assertTrue(any(
                memory["summary"] == event["public_summary"]
                for memory in state.cognition["memory_by_actor"][target_id]
            ))
        self.assertEqual([], list(campus_interaction_invariant(state)))

    def test_pair_cooldown_and_seeded_trace_are_deterministic(self):
        def trace(seed: int):
            bridge = CampusKernelBridge(seed)
            rows = []
            for step in range(8):
                result = advance(bridge, step)
                self.assertTrue(result["ok"])
                rows.extend(
                    (
                        event["day"], event["phase"],
                        tuple(sorted((*event["actor_ids"], *event["target_ids"]))),
                        event["payload"]["intent_id"], event["payload"]["outcome"],
                    )
                    for event in result["result"]["events"]
                    if event["event_type"] == "NPC_INTERACTION_RESOLVED"
                )
            return rows

        first = trace(19)
        second = trace(19)
        self.assertEqual(first, second)
        self.assertGreater(len(first), 20)
        self.assertGreaterEqual(len({row[3] for row in first}), 3)
        by_pair = {}
        for day, phase, pair, _, _ in first:
            current = phase_index(day, phase)
            if pair in by_pair:
                self.assertGreaterEqual(current - by_pair[pair], 2)
            by_pair[pair] = current

    def test_support_hook_can_be_revisited_and_resolved(self):
        bridge = CampusKernelBridge(7)
        state = bridge.kernel.state
        policy = load_campus_interaction_policy(
            ContentRegistry.load_default(REPOSITORY_DIR / "content")
        )
        intelligence_policy = load_campus_intelligence_policy(
            ContentRegistry.load_default(REPOSITORY_DIR / "content")
        )
        actor_id, target_id = sorted(
            actor_id for actor_id in state.population if actor_id != "player"
        )[:2]
        for candidate_id, actor in state.population.items():
            if candidate_id == "player" or not isinstance(actor, dict):
                continue
            actor["current_activity"] = {"status": "blocked", "effects": {"category": "personal"}}
        actor = state.population[actor_id]
        target = state.population[target_id]
        actor["current_activity"]["status"] = "completed"
        target["current_activity"]["status"] = "completed"
        actor["current_location_id"] = target["current_location_id"] = "mirror_lake_square"
        actor["club_ids"] = []
        target["club_ids"] = []
        actor["needs"]["social"] = 100
        actor["personality"].update({"extraversion": 100, "altruism": 100})
        actor["attributes"]["expression"] = 10
        target["emotions"]["sadness"] = 100
        target["personality"]["agreeableness"] = 100
        target["needs"]["social"] = 100
        state.relationships[target_id][actor_id] = {
            **DEFAULT_RELATIONSHIP, "trust": 100, "familiarity": 100,
        }
        command = SimulationCommand(
            command_id="direct-interaction", actor_id="player", action_id="ADVANCE_PHASE",
            expected_world_revision=state.revision, issued_day=state.clock.day,
            issued_phase=state.clock.phase, issued_minute=0, source="rule",
        )
        context = TransactionContext(state, DeterministicRngPool(7), command)
        first = advance_campus_interactions(context, policy, intelligence_policy)
        self.assertEqual(1, first["interaction_count"])
        hook = state.cognition["interactions"]["hooks"][0]
        self.assertEqual("check_in", hook["hook_type"])
        self.assertEqual("open", hook["state"])
        first_record = state.cognition["interactions"]["recent"][-1]
        self.assertEqual("created", first_record["hook_transition"])
        self.assertEqual(1, len(first_record["outcome_claim_ids"]))
        created_claim_id = first_record["outcome_claim_ids"][0]
        self.assertEqual(
            "social_commitment_opened", state.knowledge["claims"][created_claim_id]["predicate"]
        )
        self.assertIn(created_claim_id, state.knowledge["beliefs_by_actor"][actor_id])
        self.assertIn(created_claim_id, state.knowledge["beliefs_by_actor"][target_id])

        for _ in range(policy.pair_cooldown_phases + 1):
            state.clock.advance_phase()
        actor["personality"]["altruism"] = 0
        target["emotions"]["sadness"] = 0
        second = advance_campus_interactions(context, policy, intelligence_policy)
        self.assertEqual(1, second["interaction_hook_resolved_count"])
        self.assertEqual("completed", hook["state"])
        second_record = state.cognition["interactions"]["recent"][-1]
        self.assertEqual("completed", second_record["hook_transition"])
        resolved_claim_id = second_record["outcome_claim_ids"][0]
        self.assertEqual(
            "social_commitment_completed", state.knowledge["claims"][resolved_claim_id]["predicate"]
        )
        self.assertEqual([], list(campus_interaction_invariant(state)))


if __name__ == "__main__":
    unittest.main()
