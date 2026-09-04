from __future__ import annotations

import json
import unittest
from pathlib import Path

from simulation.api.server import CampusKernelBridge
from simulation.domain.cognition import CognitionPolicy
from simulation.persistence.kernel_checkpoint import build_kernel_checkpoint
from simulation.systems import cognition_invariant


REPOSITORY_DIR = Path(__file__).resolve().parents[1]


def command(bridge: CampusKernelBridge, action_id: str, *, target_id: str = "") -> dict:
    snapshot = bridge.snapshot()
    clock = snapshot["clock"]
    return bridge.execute({
        "command_id": f"cognition-{action_id}-{target_id}-{snapshot['revision']}",
        "actor_id": "player",
        "action_id": action_id,
        "target_ids": [target_id] if target_id else [],
        "parameters": {"target_id": target_id} if target_id else {},
        "expected_world_revision": snapshot["revision"],
        "issued_day": clock["day"],
        "issued_phase": clock["phase"],
        "issued_minute": clock["minute"],
        "source": "player",
    })


class LastLegalProvider:
    name = "fake"
    model = "fake-cheap-model"
    configured = True

    def __init__(self) -> None:
        self.requests = []
        self.dialogue_requests = []

    def decide(self, request, *, max_output_tokens):
        self.requests.append(request)
        return {
            "npc_id": request.npc_id,
            "candidate_revision": request.candidate_revision,
            "selected_action_id": request.candidates[-1]["candidate_id"],
            "reason": "角色更愿意选择这个合法方案。",
            "_usage": {"prompt_tokens": 80, "completion_tokens": 18},
        }

    def respond(self, request, *, max_output_tokens):
        self.dialogue_requests.append(request)
        fact_ids = [request.allowed_facts[0]["claim_id"]] if request.allowed_facts else []
        return {
            "npc_id": request.npc_id,
            "target_id": request.target_id,
            "candidate_revision": request.candidate_revision,
            "utterance": "这件事我们当面说清楚，也记得刚才的约定。",
            "fact_ids_used": fact_ids,
            "_usage": {"prompt_tokens": 72, "completion_tokens": 20},
        }


class InvalidProvider(LastLegalProvider):
    def decide(self, request, *, max_output_tokens):
        self.requests.append(request)
        return {
            "npc_id": request.npc_id,
            "candidate_revision": request.candidate_revision,
            "selected_action_id": "invented_illegal_action",
            "reason": "试图越过规则层。",
        }

    def respond(self, request, *, max_output_tokens):
        self.dialogue_requests.append(request)
        return {
            "npc_id": request.npc_id,
            "target_id": request.target_id,
            "candidate_revision": request.candidate_revision,
            "utterance": "我声称知道一个白名单之外的秘密。",
            "fact_ids_used": ["claim:99999999"],
        }


class CampusCognitionTests(unittest.TestCase):
    def test_initial_slots_and_public_view_are_bounded_and_sanitized(self):
        bridge = CampusKernelBridge(42)
        state = bridge.kernel.state
        self.assertEqual(20, len(state.cognition["focused_ids"]))
        self.assertEqual([], state.cognition["awakened_ids"])
        self.assertEqual([], list(cognition_invariant(state)))
        view = bridge.snapshot()["cognition"]
        self.assertEqual(20, view["focused_count"])
        self.assertEqual(6, view["awakened_slot_limit"])
        self.assertNotIn("observations", view)
        self.assertNotIn("memory_by_actor", view)
        self.assertNotIn("api_key", json.dumps(view))
        schema = json.loads(
            (REPOSITORY_DIR / "contracts/npc_cognition.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(set(schema["required"]), set(view))

    def test_player_can_awaken_six_npcs_and_seventh_is_rejected(self):
        bridge = CampusKernelBridge(3)
        actor_ids = sorted(bridge.snapshot()["population"])[:7]
        for actor_id in actor_ids[:6]:
            result = command(bridge, "AWAKEN_NPC", target_id=actor_id)
            self.assertTrue(result["ok"])
            self.assertTrue(result["snapshot"]["population"][actor_id]["awakened_by_player"])
        blocked = command(bridge, "AWAKEN_NPC", target_id=actor_ids[6])
        self.assertFalse(blocked["ok"])
        self.assertEqual("awakened_slots_full", blocked["result"]["code"])
        state = bridge.kernel.state
        self.assertEqual(6, len(state.cognition["awakened_ids"]))
        self.assertTrue(set(state.cognition["awakened_ids"]).issubset(state.cognition["focused_ids"]))

    def test_committed_event_becomes_target_subjective_memory_not_public_chronicle_dump(self):
        bridge = CampusKernelBridge(9)
        actor_id = sorted(bridge.snapshot()["population"])[0]
        result = command(bridge, "AWAKEN_NPC", target_id=actor_id)
        self.assertTrue(result["ok"])
        state = bridge.kernel.state
        memories = state.cognition["memory_by_actor"][actor_id]
        self.assertEqual(1, len(memories))
        self.assertEqual("亲历", memories[0]["interpretation"])
        self.assertGreater(memories[0]["confidence"], 0.8)
        self.assertNotIn("parameters", memories[0])
        self.assertNotIn("chronicle", json.dumps(memories, ensure_ascii=False).lower())

    def test_fake_provider_uses_only_legal_candidates_and_obeys_phase_budget(self):
        bridge = CampusKernelBridge(42)
        provider = LastLegalProvider()
        bridge.cognition_runtime.provider = provider
        result = command(bridge, "ADVANCE_PHASE")
        self.assertTrue(result["ok"])
        state = bridge.kernel.state
        usage = state.cognition["usage"]
        self.assertEqual(3, len(provider.requests))
        self.assertEqual(1, len(provider.dialogue_requests))
        self.assertEqual(4, usage["calls"])
        self.assertEqual(4, usage["phase_calls"]["afternoon"])
        self.assertEqual(2, usage["purpose_phase_calls"]["afternoon:activity"])
        self.assertEqual(1, usage["purpose_phase_calls"]["afternoon:interaction"])
        self.assertEqual(1, usage["purpose_phase_calls"]["afternoon:interaction_dialogue"])
        self.assertEqual(312, usage["prompt_tokens"])
        self.assertEqual(74, usage["completion_tokens"])
        llm_decisions = [
            actor["current_decision"] for actor in state.population.values()
            if isinstance(actor, dict) and actor.get("current_decision", {}).get("decision_source") == "llm"
        ]
        self.assertGreater(len(llm_decisions), 0)
        self.assertTrue(all(item["candidate_id"] for item in llm_decisions))
        interaction_events = [
            event for event in result["result"]["events"]
            if event["event_type"] == "NPC_INTERACTION_RESOLVED"
            and event["payload"]["decision_source"] == "llm"
        ]
        self.assertEqual(1, len(interaction_events))
        self.assertEqual("llm", interaction_events[0]["payload"]["wording_source"])
        self.assertIn("当面说清楚", interaction_events[0]["public_summary"])
        dialogue_request = provider.dialogue_requests[0].to_dict()
        self.assertEqual("in_person", dialogue_request["dialogue_kind"])
        self.assertEqual(
            interaction_events[0]["payload"]["intent_id"],
            dialogue_request["interaction_context"]["intent_id"],
        )
        self.assertNotIn("chronicles", dialogue_request)
        first_request = provider.requests[0].to_dict()
        self.assertNotIn("chronicles", first_request)
        self.assertNotIn("authoritative", first_request)

    def test_invalid_or_unavailable_provider_falls_back_without_blocking_world(self):
        bridge = CampusKernelBridge(8)
        provider = InvalidProvider()
        bridge.cognition_runtime.provider = provider
        result = command(bridge, "ADVANCE_PHASE")
        self.assertTrue(result["ok"])
        state = bridge.kernel.state
        self.assertGreater(state.cognition["usage"]["rejected_responses"], 0)
        self.assertTrue(all(
            actor.get("current_decision", {}).get("decision_source") != "llm"
            for actor_id, actor in state.population.items()
            if actor_id != "player" and isinstance(actor, dict)
        ))
        self.assertTrue(all(
            record.get("wording_source") == "rule"
            for record in state.cognition["interactions"]["recent"]
        ))
        self.assertEqual(0, result["result"]["payload"]["phase_execution"]["blocked_actor_count"])

    def test_provider_secret_is_not_serialized_into_checkpoint(self):
        bridge = CampusKernelBridge(5)
        bridge.cognition_runtime.configure_openai_compatible(
            "https://provider.invalid/v1", "configured-model", "test-secret-never-save"
        )
        checkpoint = build_kernel_checkpoint(bridge.kernel.state, bridge.kernel._rng)
        serialized = json.dumps(checkpoint)
        self.assertNotIn("test-secret-never-save", serialized)
        self.assertNotIn("provider.invalid", serialized)

    def test_generic_openai_compatible_provider_and_legacy_aliases_are_supported(self):
        for provider_id in ("openai_compatible", "deepseek", "deepseek_compatible"):
            bridge = CampusKernelBridge(5)
            bridge.configure_cognition_interface({
                "provider": provider_id,
                "base_url": "https://provider.invalid/v1",
                "model": "configured-model",
                "api_key": "test-secret-never-send",
            })
            status = bridge.cognition_runtime.public_status()
            self.assertEqual("openai_compatible", status["mode"])
            self.assertTrue(status["configured"])

    def test_versioned_policy_does_not_contain_personal_provider_presets(self):
        payload = json.loads(
            (REPOSITORY_DIR / "content/npcs/cognition_policy.json").read_text(encoding="utf-8")
        )
        self.assertNotIn("model_presets", payload)


if __name__ == "__main__":
    unittest.main()
