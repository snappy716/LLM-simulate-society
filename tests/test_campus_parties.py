from __future__ import annotations

import json
import unittest
from pathlib import Path

from simulation.actions import SimulationCommand
from simulation.api.server import CampusKernelBridge
from simulation.systems import (
    DeterministicRngPool,
    TransactionContext,
    advance_party_commitments,
    campus_party_invariant,
    invitation_assessment,
    party_policy_from_state,
)


REPOSITORY_DIR = Path(__file__).resolve().parents[1]


def execute(bridge: CampusKernelBridge, action_id: str, parameters=None, actor_id="player"):
    snapshot = bridge.snapshot()
    clock = snapshot["clock"]
    return bridge.execute({
        "command_id": f"party-{action_id}-{actor_id}-{snapshot['revision']}",
        "actor_id": actor_id,
        "action_id": action_id,
        "target_ids": [],
        "parameters": parameters or {},
        "expected_world_revision": snapshot["revision"],
        "issued_day": clock["day"],
        "issued_phase": clock["phase"],
        "issued_minute": clock["minute"],
        "source": "player" if actor_id == "player" else "rule",
    })


def accepted_candidate(snapshot: dict) -> dict:
    return next(
        candidate for candidate in snapshot["party"]["candidates"]
        if candidate["expected_response"] == "likely_accept" and candidate["can_invite"]
    )


class CampusPartyRuntimeTests(unittest.TestCase):
    def test_player_party_is_installed_with_derived_stability_and_candidates(self):
        bridge = CampusKernelBridge(42)
        party = bridge.snapshot()["party"]
        self.assertEqual("party:player", party["party_id"])
        self.assertEqual("player", party["leader_id"])
        self.assertEqual(1, party["member_count"])
        self.assertEqual(3, party["max_members"])
        self.assertFalse(party["is_full"])
        self.assertEqual("leader", party["members"][0]["status"])
        self.assertEqual(200, len(party["candidates"]))
        self.assertIn(party["stability"]["band"], {"fragile", "uncertain", "steady", "cohesive"})
        self.assertEqual([], list(campus_party_invariant(bridge.kernel.state)))
        schema = json.loads(
            (REPOSITORY_DIR / "contracts/campus_party.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(set(schema["required"]), set(party))
        self.assertLessEqual(len(party["members"]), schema["properties"]["members"]["maxItems"])

    def test_invitation_acceptance_creates_commitment_relationships_and_chronicle(self):
        bridge = CampusKernelBridge(42)
        before = bridge.snapshot()
        candidate = accepted_candidate(before)
        budget = before["player"]["action_budget"].copy()
        clock = before["clock"].copy()
        result = execute(bridge, "INVITE_PARTY_MEMBER", {"target_id": candidate["actor_id"]})
        self.assertTrue(result["ok"], result)
        self.assertEqual("committed", result["result"]["payload"]["membership"]["status"])
        self.assertIn("PARTY_MEMBER_COMMITTED", [event["event_type"] for event in result["result"]["events"]])
        final = result["snapshot"]
        self.assertEqual(2, final["party"]["member_count"])
        self.assertEqual(clock, final["clock"])
        self.assertEqual(budget, final["player"]["action_budget"])
        state = bridge.kernel.state
        self.assertEqual(51, state.relationships[candidate["actor_id"]]["player"]["trust"])
        self.assertEqual(2, state.relationships[candidate["actor_id"]]["player"]["obligation"])
        entries = bridge.chronicle(candidate["actor_id"], filter_name="important", limit=20)["items"]
        self.assertTrue(any(entry["event_type"] == "PARTY_MEMBER_COMMITTED" for entry in entries))

    def test_decline_is_recorded_and_same_day_repeat_has_a_cooldown(self):
        bridge = CampusKernelBridge(42)
        candidate = next(
            item for item in bridge.snapshot()["party"]["candidates"]
            if item["expected_response"] == "unavailable"
        )
        declined = execute(bridge, "INVITE_PARTY_MEMBER", {"target_id": candidate["actor_id"]})
        self.assertFalse(declined["ok"])
        self.assertTrue(declined["result"]["performed"])
        self.assertEqual("invitation_declined", declined["result"]["code"])
        self.assertEqual(1, declined["snapshot"]["party"]["member_count"])
        revision = declined["snapshot"]["revision"]
        retry = execute(bridge, "INVITE_PARTY_MEMBER", {"target_id": candidate["actor_id"]})
        self.assertFalse(retry["ok"])
        self.assertEqual("invitation_cooldown", retry["result"]["code"])
        self.assertEqual(revision, retry["snapshot"]["revision"])

    def test_three_person_limit_is_atomic_and_leader_can_dismiss(self):
        bridge = CampusKernelBridge(42)
        accepted_ids = []
        for _ in range(2):
            candidate = accepted_candidate(bridge.snapshot())
            accepted_ids.append(candidate["actor_id"])
            self.assertTrue(execute(bridge, "INVITE_PARTY_MEMBER", {"target_id": candidate["actor_id"]})["ok"])
        full = bridge.snapshot()
        self.assertTrue(full["party"]["is_full"])
        extra = next(item for item in full["party"]["candidates"] if item["expected_response"] != "unavailable")
        blocked = execute(bridge, "INVITE_PARTY_MEMBER", {"target_id": extra["actor_id"]})
        self.assertFalse(blocked["ok"])
        self.assertEqual("party_full", blocked["result"]["code"])
        self.assertEqual(full["revision"], blocked["snapshot"]["revision"])
        dismissed = execute(bridge, "DISMISS_PARTY_MEMBER", {"target_id": accepted_ids[0]})
        self.assertTrue(dismissed["ok"], dismissed)
        self.assertEqual(2, dismissed["snapshot"]["party"]["member_count"])
        self.assertNotIn(accepted_ids[0], [member["actor_id"] for member in dismissed["snapshot"]["party"]["members"]])

    def test_relationship_and_personality_change_invitation_score(self):
        bridge = CampusKernelBridge(42)
        state = bridge.kernel.state
        policy = party_policy_from_state(state)
        target_id = next(
            actor_id for actor_id, actor in state.population.items()
            if actor_id != "player" and actor.get("night_access") == "capable"
        )
        base = invitation_assessment(state, "player", target_id, policy)["score"]
        state.relationships[target_id]["player"] = {
            "familiarity": 80, "trust": 90, "closeness": 70, "respect": 70,
            "suspicion": 0, "fear": 0, "obligation": 30, "conflict": 0,
        }
        improved = invitation_assessment(state, "player", target_id, policy)
        self.assertGreater(improved["score"], base)
        self.assertTrue(improved["accepted"])

    def test_relationship_skill_contributes_to_party_stability_preview(self):
        bridge = CampusKernelBridge(42)
        candidate = accepted_candidate(bridge.snapshot())
        self.assertTrue(execute(bridge, "INVITE_PARTY_MEMBER", {"target_id": candidate["actor_id"]})["ok"])
        stability = bridge.snapshot()["party"]["stability"]
        self.assertGreaterEqual(stability["relationship_skill_bonus"], 3)
        self.assertTrue(stability["active_collaboration_skills"])
        skill = stability["active_collaboration_skills"][0]
        self.assertTrue(skill["active"])
        self.assertIn("effect_id", skill["battle_effect"])

    def test_expired_commitment_can_be_reconsidered_by_npc(self):
        bridge = CampusKernelBridge(42)
        candidate = accepted_candidate(bridge.snapshot())
        target_id = candidate["actor_id"]
        self.assertTrue(execute(bridge, "INVITE_PARTY_MEMBER", {"target_id": target_id})["ok"])
        state = bridge.kernel.state
        policy = party_policy_from_state(state)
        state.clock.day = 3
        state.clock.phase = "morning"
        state.relationships[target_id]["player"].update({
            "trust": 0, "suspicion": 100, "fear": 100, "conflict": 100,
        })
        command = SimulationCommand(
            command_id="review-party", actor_id="player", action_id="ADVANCE_PHASE",
            expected_world_revision=state.revision, issued_day=3, issued_phase="morning",
        )
        context = TransactionContext(state, DeterministicRngPool(42), command)
        summary = advance_party_commitments(context, policy)
        self.assertEqual(1, summary["party_withdrawals"])
        self.assertNotIn(target_id, state.parties["party:player"]["member_ids"])
        self.assertEqual("PARTY_MEMBER_WITHDREW", context.event_drafts[0].event_type)


if __name__ == "__main__":
    unittest.main()
