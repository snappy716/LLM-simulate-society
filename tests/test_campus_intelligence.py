from __future__ import annotations

import json
import unittest
from pathlib import Path

from simulation.api.server import CampusKernelBridge
from simulation.systems import (
    ContentRegistry,
    DeterministicRngPool,
    campus_intelligence_invariant,
    create_campus_claim,
    load_campus_intelligence_policy,
    share_known_claim,
)


REPOSITORY_DIR = Path(__file__).resolve().parents[1]


def advance(bridge: CampusKernelBridge, step: int) -> dict:
    snapshot = bridge.snapshot()
    clock = snapshot["clock"]
    return bridge.execute({
        "command_id": f"intelligence-phase-{step}-{snapshot['revision']}",
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


class CampusIntelligenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = ContentRegistry.load_default(REPOSITORY_DIR / "content")
        cls.policy = load_campus_intelligence_policy(cls.registry)

    def setUp(self):
        self.state = CampusKernelBridge(41).kernel.state
        self.actor_ids = sorted(
            actor_id for actor_id in self.state.population if actor_id != "player"
        )[:3]

    def test_unknown_claim_cannot_be_shared(self):
        sender_id, receiver_id, owner_id = self.actor_ids
        self.state.knowledge["beliefs_by_actor"][sender_id].clear()
        claim = create_campus_claim(
            self.state,
            subject_id=owner_id,
            predicate="noticed",
            object_id="unusual_light",
            summary="有人在湖边看见了不寻常的微光。",
            secrecy=10,
            known_by=[owner_id],
        )
        receipt = share_known_claim(
            self.state,
            sender_id=sender_id,
            receiver_id=receiver_id,
            interaction_id="interaction:00000001",
            intent_id="exchange_ideas",
            policy=self.policy,
            rng=DeterministicRngPool(1).stream("test_unknown_claim"),
        )
        self.assertIsNone(receipt)
        self.assertNotIn(
            claim["claim_id"], self.state.knowledge["beliefs_by_actor"][receiver_id]
        )

    def test_secret_claim_needs_a_strong_relationship(self):
        sender_id, receiver_id, _ = self.actor_ids
        self.state.knowledge["beliefs_by_actor"][sender_id].clear()
        claim = create_campus_claim(
            self.state,
            subject_id=sender_id,
            predicate="keeps_secret",
            object_id="private_archive_note",
            summary="这是一条不应向陌生人透露的私人记录。",
            secrecy=95,
            known_by=[sender_id],
        )
        receipt = share_known_claim(
            self.state,
            sender_id=sender_id,
            receiver_id=receiver_id,
            interaction_id="interaction:00000001",
            intent_id="exchange_ideas",
            policy=self.policy,
            rng=DeterministicRngPool(2).stream("test_secret_claim"),
        )
        self.assertIsNone(receipt)
        self.assertNotIn(
            claim["claim_id"], self.state.knowledge["beliefs_by_actor"][receiver_id]
        )

    def test_share_copies_a_source_tagged_subjective_belief(self):
        sender_id, receiver_id, _ = self.actor_ids
        self.state.knowledge["beliefs_by_actor"][sender_id].clear()
        self.state.knowledge["beliefs_by_actor"][receiver_id].clear()
        claim = create_campus_claim(
            self.state,
            subject_id=sender_id,
            predicate="noticed",
            object_id="library_notice",
            summary="图书馆今天调整了借阅安排。",
            secrecy=0,
            known_by=[sender_id],
        )
        receipt = share_known_claim(
            self.state,
            sender_id=sender_id,
            receiver_id=receiver_id,
            interaction_id="interaction:00000001",
            intent_id="exchange_ideas",
            policy=self.policy,
            rng=DeterministicRngPool(3).stream("test_direct_share"),
        )
        self.assertIsNotNone(receipt)
        self.assertEqual(claim["claim_id"], receipt["claim_id"])
        belief = self.state.knowledge["beliefs_by_actor"][receiver_id][claim["claim_id"]]
        self.assertEqual(sender_id, belief["source_actor_id"])
        self.assertEqual("statement", belief["source_kind"])
        self.assertGreater(belief["confidence"], 0)
        self.assertLess(belief["confidence"], 1)
        self.assertGreater(belief["distortion"], 0)
        self.assertEqual([], list(campus_intelligence_invariant(self.state)))

    def test_phase_interactions_emit_bounded_information_events(self):
        bridge = CampusKernelBridge(19)
        events = []
        rejected_interactions = []
        schema = json.loads(
            (REPOSITORY_DIR / "contracts/npc_information_share.schema.json").read_text(
                encoding="utf-8"
            )
        )
        for step in range(12):
            result = advance(bridge, step)
            self.assertTrue(result["ok"])
            phase_events = [
                event for event in result["result"]["events"]
                if event["event_type"] == "NPC_INFORMATION_SHARED"
            ]
            events.extend(phase_events)
            rejected_interactions.extend(
                event for event in result["result"]["events"]
                if event["event_type"] == "NPC_INTERACTION_RESOLVED"
                and event["payload"]["outcome"] == "rejected"
            )
            phase_state = bridge.kernel.state
            for event in phase_events:
                self.assertEqual(set(schema["required"]), set(event["payload"]))
                payload = event["payload"]
                receiver_belief = phase_state.knowledge["beliefs_by_actor"][
                    payload["receiver_id"]
                ][payload["claim_id"]]
                self.assertEqual(payload["source_actor_id"], receiver_belief["source_actor_id"])
                self.assertEqual(payload["confidence"], receiver_belief["confidence"])
                self.assertIn("说：“", event["public_summary"])
                self.assertTrue(any(
                    memory["summary"] == event["public_summary"]
                    for memory in phase_state.cognition["memory_by_actor"][payload["receiver_id"]]
                ))
        self.assertGreater(len(events), 0)
        self.assertGreater(len(rejected_interactions), 0)
        self.assertTrue(all(
            event["payload"]["shared_claim_id"] is None
            for event in rejected_interactions
        ))
        state = bridge.kernel.state
        snapshot = bridge.snapshot()
        self.assertNotIn("claims", snapshot)
        self.assertFalse(any(
            "beliefs_by_actor" in actor for actor in snapshot["population"].values()
        ))
        self.assertEqual([], list(campus_intelligence_invariant(state)))


if __name__ == "__main__":
    unittest.main()
