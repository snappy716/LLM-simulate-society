from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from simulation.api.server import CampusKernelBridge
from simulation.actions.commands import SimulationCommand
from simulation.systems import (
    ContentRegistry,
    DeterministicRngPool,
    TransactionContext,
    advance_npc_player_proposals,
    campus_proposal_invariant,
    load_campus_interaction_policy,
    load_campus_messaging_policy,
)
from simulation.systems.campus_social import DEFAULT_RELATIONSHIP


REPOSITORY_DIR = Path(__file__).resolve().parents[1]


def propose(
    bridge: CampusKernelBridge,
    target_id: str,
    proposal_type: str,
    channel: str,
    marker: str,
) -> dict:
    snapshot = bridge.snapshot()
    clock = snapshot["clock"]
    return bridge.execute({
        "command_id": f"proposal-{marker}-{snapshot['revision']}",
        "actor_id": "player",
        "action_id": "MAKE_SOCIAL_PROPOSAL",
        "target_ids": [target_id],
        "parameters": {
            "target_id": target_id,
            "proposal_type": proposal_type,
            "channel": channel,
            "note": "",
        },
        "expected_world_revision": snapshot["revision"],
        "issued_day": clock["day"],
        "issued_phase": clock["phase"],
        "issued_minute": clock["minute"],
        "source": "player",
    })


def execute_action(bridge: CampusKernelBridge, action_id: str, parameters: dict, marker: str) -> dict:
    snapshot = bridge.snapshot()
    clock = snapshot["clock"]
    return bridge.execute({
        "command_id": f"{marker}-{snapshot['revision']}",
        "actor_id": "player",
        "action_id": action_id,
        "target_ids": [str(parameters["task_id"])] if "task_id" in parameters else [],
        "parameters": parameters,
        "expected_world_revision": snapshot["revision"],
        "issued_day": clock["day"],
        "issued_phase": clock["phase"],
        "issued_minute": clock["minute"],
        "source": "player",
    })


def advance_phase(bridge: CampusKernelBridge, marker: str) -> dict:
    return execute_action(bridge, "ADVANCE_PHASE", {}, marker)


def respond(bridge: CampusKernelBridge, proposal_id: str, accepted: bool, marker: str) -> dict:
    return execute_action(
        bridge,
        "RESPOND_SOCIAL_PROPOSAL",
        {"proposal_id": proposal_id, "accepted": accepted},
        marker,
    )


def advance_until_incoming(bridge: CampusKernelBridge, limit: int = 8) -> dict:
    for index in range(limit):
        result = advance_phase(bridge, f"incoming-{index}")
        pending = [
            item for item in result["snapshot"]["social"]["incoming_proposals"]
            if item["status"] == "pending"
        ]
        if pending:
            return pending[0]
    raise AssertionError("expected an autonomous NPC proposal")


def make_willing(bridge: CampusKernelBridge, target_id: str) -> None:
    state = bridge.kernel._state
    relation = state.relationships.setdefault(target_id, {}).setdefault(
        "player", deepcopy(DEFAULT_RELATIONSHIP)
    )
    relation.update({
        "familiarity": 100, "trust": 100, "closeness": 100,
        "respect": 100, "suspicion": 0, "conflict": 0,
    })
    state.population[target_id]["personality"].update({
        "agreeableness": 100, "risk_tolerance": 100,
    })
    state.population[target_id]["needs"]["social"] = 100


class CampusProposalTests(unittest.TestCase):
    class ProposalProvider:
        name = "fake"
        model = "fake-proposal"
        configured = True

        def __init__(self) -> None:
            self.requests = []

        def respond(self, request, *, max_output_tokens):
            self.requests.append(request)
            return {
                "npc_id": request.npc_id,
                "target_id": request.target_id,
                "candidate_revision": request.candidate_revision,
                "utterance": "可以，我接受这个明确的安排。",
                "fact_ids_used": [],
                "_usage": {"prompt_tokens": 24, "completion_tokens": 10},
            }

    def test_phone_meet_up_is_explicit_free_and_persisted_in_thread(self):
        bridge = CampusKernelBridge(51)
        target_id = bridge.snapshot()["messaging"]["contacts"][0]["actor_id"]
        make_willing(bridge, target_id)
        budget_before = bridge.snapshot()["player"]["action_budget"]["major_remaining"]
        result = propose(bridge, target_id, "meet_up", "phone", "meet")
        self.assertTrue(result["ok"])
        payload = result["result"]["payload"]
        self.assertEqual("accepted", payload["status"])
        self.assertEqual("free", payload["action_class"])
        self.assertEqual("created", payload["hook_transition"])
        self.assertEqual(2, len(result["snapshot"]["messaging"]["threads"][target_id]["messages"]))
        self.assertEqual(budget_before, result["snapshot"]["player"]["action_budget"]["major_remaining"])
        schema = json.loads(
            (REPOSITORY_DIR / "contracts/social_proposal.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(set(schema["required"]), set(payload))
        self.assertEqual([], list(campus_proposal_invariant(bridge.kernel.state)))

    def test_in_person_party_proposal_uses_real_party_commitment(self):
        bridge = CampusKernelBridge(53)
        candidate = next(
            item for item in bridge.snapshot()["party"]["candidates"]
            if item["can_invite"]
        )
        target_id = candidate["actor_id"]
        state = bridge.kernel._state
        state.population["player"]["current_location_id"] = state.population[target_id]["current_location_id"]
        make_willing(bridge, target_id)
        result = propose(bridge, target_id, "party_invite", "in_person", "party")
        self.assertTrue(result["ok"])
        self.assertEqual("accepted", result["result"]["payload"]["status"])
        self.assertEqual(target_id, result["snapshot"]["party"]["members"][1]["actor_id"])
        self.assertEqual(2, result["snapshot"]["party"]["member_count"])

    def test_task_help_requires_a_player_owned_task(self):
        bridge = CampusKernelBridge(55)
        target_id = bridge.snapshot()["messaging"]["contacts"][0]["actor_id"]
        result = propose(bridge, target_id, "task_help", "phone", "no-task")
        self.assertFalse(result["ok"])
        self.assertEqual("proposal_precondition_failed", result["result"]["code"])
        self.assertEqual(1, result["snapshot"]["revision"])

    def test_task_help_acceptance_links_the_owned_task_to_a_real_commitment(self):
        bridge = CampusKernelBridge(56)
        task_id = next(
            task_id for task_id, task in bridge.snapshot()["tasks"].items()
            if task["state"] in {"open", "viewed", "considering"}
        )
        self.assertTrue(execute_action(bridge, "VIEW_FORUM_TASK", {"task_id": task_id}, "view")["ok"])
        task_revision = int(bridge.snapshot()["tasks"][task_id]["lock_revision"])
        self.assertTrue(execute_action(
            bridge, "CLAIM_FORUM_TASK",
            {"task_id": task_id, "expected_task_revision": task_revision}, "claim",
        )["ok"])
        target_id = bridge.snapshot()["messaging"]["contacts"][0]["actor_id"]
        make_willing(bridge, target_id)
        result = propose(bridge, target_id, "task_help", "phone", "help")
        self.assertTrue(result["ok"])
        payload = result["result"]["payload"]
        self.assertEqual(task_id, payload["subject_id"])
        final_state = bridge.kernel.state
        self.assertIn(target_id, final_state.tasks[task_id]["helper_ids"])
        self.assertEqual("task_support_commitment", final_state.cognition["interactions"]["hooks"][-1]["hook_type"])
        self.assertEqual("created", payload["hook_transition"])
        self.assertTrue(execute_action(
            bridge, "ABANDON_FORUM_TASK", {"task_id": task_id}, "abandon"
        )["ok"])
        self.assertEqual(
            "broken", bridge.kernel.state.cognition["interactions"]["hooks"][-1]["state"]
        )

    def test_phone_requires_contact_and_face_to_face_requires_shared_scene(self):
        bridge = CampusKernelBridge(57)
        contacts = {item["actor_id"] for item in bridge.snapshot()["messaging"]["contacts"]}
        target_id = next(actor_id for actor_id in bridge.snapshot()["population"] if actor_id not in contacts)
        phone = propose(bridge, target_id, "meet_up", "phone", "remote-phone")
        self.assertFalse(phone["ok"])
        self.assertEqual("not_a_contact", phone["result"]["code"])

        state = bridge.kernel._state
        player_region = state.places[state.population["player"]["current_location_id"]]["region_id"]
        excluded = {player_region, "central_region"}
        remote_id = next(
            actor_id for actor_id, actor in sorted(state.population.items())
            if actor_id != "player"
            and state.places[actor["current_location_id"]]["region_id"] not in excluded
        )
        face = propose(bridge, remote_id, "meet_up", "in_person", "remote-face")
        self.assertFalse(face["ok"])
        self.assertEqual("target_not_present", face["result"]["code"])

    def test_same_proposal_type_has_one_phase_cooldown(self):
        bridge = CampusKernelBridge(59)
        target_id = bridge.snapshot()["messaging"]["contacts"][0]["actor_id"]
        make_willing(bridge, target_id)
        first = propose(bridge, target_id, "meet_up", "phone", "first")
        self.assertTrue(first["ok"])
        second = propose(bridge, target_id, "meet_up", "phone", "second")
        self.assertFalse(second["ok"])
        self.assertEqual("proposal_cooldown", second["result"]["code"])
        self.assertEqual(first["snapshot"]["revision"], second["snapshot"]["revision"])

    def test_player_proposal_llm_only_words_the_verified_outcome_without_background_budget(self):
        bridge = CampusKernelBridge(61)
        target_id = bridge.snapshot()["messaging"]["contacts"][0]["actor_id"]
        make_willing(bridge, target_id)
        state = bridge.kernel._state
        if target_id not in state.cognition["focused_ids"]:
            state.cognition["focused_ids"][-1] = target_id
        provider = self.ProposalProvider()
        bridge.cognition_runtime.provider = provider
        state.cognition["usage"]["automated_calls"] = bridge.cognition_runtime.policy.daily_call_limit
        state.cognition["usage"]["automated_estimated_tokens"] = bridge.cognition_runtime.policy.daily_estimated_token_limit
        result = propose(bridge, target_id, "meet_up", "phone", "llm")
        self.assertTrue(result["ok"])
        self.assertEqual("llm", result["result"]["payload"]["wording_source"])
        self.assertEqual("accepted", provider.requests[0].interaction_context["outcome"])
        usage = bridge.kernel.state.cognition["usage"]
        self.assertEqual(1, usage["player_dialogue_calls"])
        self.assertEqual(0, usage["budget_blocks"])

    def test_npc_task_request_waits_for_player_then_commits_atomically(self):
        bridge = CampusKernelBridge(91)
        proposal = advance_until_incoming(bridge)
        self.assertEqual("task_help", proposal["proposal_type"])
        task_id = proposal["subject_id"]
        self.assertNotIn("player", bridge.kernel._state.tasks[task_id]["helper_ids"])
        self.assertFalse(any(
            hook.get("linked_task_id") == task_id and hook.get("target_id") == "player"
            for hook in bridge.kernel._state.cognition["interactions"]["hooks"]
        ))
        result = respond(bridge, proposal["proposal_id"], True, "accept-incoming")
        self.assertTrue(result["ok"])
        payload = result["result"]["payload"]
        self.assertEqual("accepted", payload["status"])
        self.assertEqual("created", payload["hook_transition"])
        self.assertIn("player", bridge.kernel._state.tasks[task_id]["helper_ids"])
        self.assertTrue(any(
            hook.get("hook_id") == payload["hook_id"]
            and hook.get("hook_type") == "task_support_commitment"
            and hook.get("linked_task_id") == task_id
            for hook in bridge.kernel._state.cognition["interactions"]["hooks"]
        ))
        self.assertEqual([], list(campus_proposal_invariant(bridge.kernel.state)))

    def test_player_can_decline_without_applying_requested_task_or_hook(self):
        bridge = CampusKernelBridge(91)
        proposal = advance_until_incoming(bridge)
        task_id = proposal["subject_id"]
        result = respond(bridge, proposal["proposal_id"], False, "decline-incoming")
        self.assertTrue(result["ok"])
        self.assertEqual("declined", result["result"]["payload"]["status"])
        self.assertNotIn("player", bridge.kernel._state.tasks[task_id]["helper_ids"])
        self.assertFalse(any(
            hook.get("linked_task_id") == task_id and hook.get("target_id") == "player"
            for hook in bridge.kernel._state.cognition["interactions"]["hooks"]
        ))

    def test_pending_request_expires_and_cannot_be_answered_late(self):
        bridge = CampusKernelBridge(91)
        proposal = advance_until_incoming(bridge)
        for index in range(5):
            advance_phase(bridge, f"expire-{index}")
        final = next(
            item for item in bridge.snapshot()["social"]["incoming_proposals"]
            if item["proposal_id"] == proposal["proposal_id"]
        )
        self.assertEqual("expired", final["status"])
        result = respond(bridge, proposal["proposal_id"], True, "late-response")
        self.assertFalse(result["ok"])
        self.assertEqual("proposal_already_resolved", result["result"]["code"])

    def test_incoming_proposal_schema_and_snapshot_are_explicit(self):
        bridge = CampusKernelBridge(91)
        proposal = advance_until_incoming(bridge)
        schema = json.loads(
            (REPOSITORY_DIR / "contracts/npc_player_proposal.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(set(schema["required"]), set(proposal) - {"initiator_name"})
        self.assertEqual("player", proposal["player_id"])
        self.assertEqual("free", proposal["action_class"])
        self.assertEqual("pending", proposal["status"])

    def test_remote_contact_request_and_player_reply_share_the_phone_thread(self):
        bridge = CampusKernelBridge(93)
        state = bridge.kernel._state
        contact_id = bridge.snapshot()["messaging"]["contacts"][0]["actor_id"]
        for actor_id, actor in state.population.items():
            if actor_id != "player":
                actor["needs"]["social"] = 0
                actor.pop("active_forum_task_id", None)
        contact = state.population[contact_id]
        contact["needs"]["social"] = 100
        relation = state.relationships.setdefault(contact_id, {}).setdefault(
            "player", deepcopy(DEFAULT_RELATIONSHIP)
        )
        relation.update({"trust": 100, "closeness": 100, "suspicion": 0, "conflict": 0})
        state.population["player"]["current_location_id"] = next(
            place_id for place_id, place in state.places.items()
            if place.get("region_id") == "central_region" and place.get("node_type") != "region"
        )
        contact["current_location_id"] = next(
            place_id for place_id, place in state.places.items()
            if place.get("region_id") == "west_dorm_region" and place.get("node_type") != "region"
        )
        registry = ContentRegistry.load_default(REPOSITORY_DIR / "content")
        clock = state.clock
        command = SimulationCommand(
            command_id="system-proposal-test", actor_id="player",
            action_id="ADVANCE_PHASE", target_ids=(), parameters={},
            expected_world_revision=state.revision, issued_day=clock.day,
            issued_phase=clock.phase, issued_minute=clock.minute, source="rule",
        )
        context = TransactionContext(state, DeterministicRngPool(state.master_seed), command)
        summary = advance_npc_player_proposals(
            context,
            load_campus_interaction_policy(registry),
            load_campus_messaging_policy(registry),
        )
        self.assertEqual(1, summary["incoming_proposal_created_count"])
        proposal = state.cognition["interactions"]["incoming_proposals"][-1]
        self.assertEqual(contact_id, proposal["initiator_id"])
        self.assertEqual("phone", proposal["channel"])
        self.assertIsNotNone(proposal["request_message_id"])
        result = respond(bridge, proposal["proposal_id"], False, "phone-decline")
        self.assertTrue(result["ok"])
        payload = result["result"]["payload"]
        self.assertIsNotNone(payload["response_message_id"])
        messages = result["snapshot"]["messaging"]["threads"][contact_id]["messages"]
        self.assertEqual(
            [proposal["request_message_id"], payload["response_message_id"]],
            [messages[-2]["message_id"], messages[-1]["message_id"]],
        )


if __name__ == "__main__":
    unittest.main()
