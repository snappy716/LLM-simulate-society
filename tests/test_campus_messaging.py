from __future__ import annotations

import json
import unittest
from pathlib import Path

from simulation.api.server import CampusKernelBridge
from simulation.systems import campus_messaging_invariant, phase_index


REPOSITORY_DIR = Path(__file__).resolve().parents[1]


class DialogueProvider:
    name = "fake"
    model = "fake-dialogue-model"
    configured = True

    def __init__(self) -> None:
        self.dialogue_requests = []

    def decide(self, request, *, max_output_tokens):
        return {
            "npc_id": request.npc_id,
            "candidate_revision": request.candidate_revision,
            "selected_action_id": request.candidates[0]["candidate_id"],
            "reason": "合法候选。",
        }

    def respond(self, request, *, max_output_tokens):
        self.dialogue_requests.append(request)
        fact_ids = [request.allowed_facts[0]["claim_id"]] if request.allowed_facts else []
        return {
            "npc_id": request.npc_id,
            "target_id": request.target_id,
            "candidate_revision": request.candidate_revision,
            "utterance": "你好，我看到了。我们可以从彼此已经知道的事情聊起。",
            "fact_ids_used": fact_ids,
            "_usage": {"prompt_tokens": 72, "completion_tokens": 20},
        }


def execute(bridge: CampusKernelBridge, action_id: str, parameters=None, step=0) -> dict:
    snapshot = bridge.snapshot()
    clock = snapshot["clock"]
    return bridge.execute({
        "command_id": f"phone-{action_id}-{step}-{snapshot['revision']}",
        "actor_id": "player",
        "action_id": action_id,
        "target_ids": [parameters["target_id"]] if parameters and parameters.get("target_id") else [],
        "parameters": parameters or {},
        "expected_world_revision": snapshot["revision"],
        "issued_day": clock["day"],
        "issued_phase": clock["phase"],
        "issued_minute": clock["minute"],
        "source": "player",
    })


class CampusMessagingIntegrationTests(unittest.TestCase):
    def test_focused_contact_uses_bounded_llm_wording_and_discloses_only_allowed_fact(self):
        bridge = CampusKernelBridge(42)
        target_id = str(bridge.snapshot()["messaging"]["contacts"][0]["actor_id"])
        self.assertTrue(execute(bridge, "AWAKEN_NPC", {"target_id": target_id})["ok"])
        provider = DialogueProvider()
        bridge.cognition_runtime.provider = provider
        result = execute(bridge, "SEND_PHONE_MESSAGE", {
            "target_id": target_id,
            "text": "你好，最近有什么想和我说的吗？",
        })
        self.assertTrue(result["ok"])
        reply = result["result"]["payload"]["reply_messages"][0]
        self.assertEqual("llm", reply["source"])
        self.assertIn("彼此已经知道", reply["text"])
        self.assertEqual(1, len(provider.dialogue_requests))
        request = provider.dialogue_requests[0]
        request_json = json.dumps(request.to_dict(), ensure_ascii=False)
        self.assertNotIn("chronicles", request_json)
        self.assertNotIn("tasks", request_json)
        used_claim = reply["shared_claim_id"]
        self.assertIn(used_claim, bridge.kernel.state.knowledge["beliefs_by_actor"]["player"])
        share = result["result"]["payload"]["information_shares"][0]
        self.assertEqual("phone_statement", share["acquisition_method"])
        usage = bridge.kernel._state.cognition["usage"]
        self.assertEqual(1, usage["purpose_phase_calls"]["morning:player_dialogue"])
        self.assertEqual(72, usage["prompt_tokens"])
        self.assertEqual(20, usage["completion_tokens"])

    def test_player_dialogue_is_not_limited_by_autonomous_budget(self):
        bridge = CampusKernelBridge(9)
        target_id = str(bridge.snapshot()["messaging"]["contacts"][0]["actor_id"])
        self.assertTrue(execute(bridge, "AWAKEN_NPC", {"target_id": target_id})["ok"])
        provider = DialogueProvider()
        bridge.cognition_runtime.provider = provider
        usage = bridge.kernel.state.cognition["usage"]
        usage["automated_calls"] = bridge.cognition_runtime.policy.daily_call_limit
        usage["automated_estimated_tokens"] = bridge.cognition_runtime.policy.daily_estimated_token_limit
        sources = []
        for index in range(5):
            result = execute(bridge, "SEND_PHONE_MESSAGE", {
                "target_id": target_id, "text": f"第{index + 1}条消息。",
            }, step=index)
            self.assertTrue(result["ok"])
            sources.append(result["result"]["payload"]["reply_messages"][0]["source"])
        self.assertEqual(["llm"] * 5, sources)
        self.assertEqual(5, len(provider.dialogue_requests))
        final_usage = bridge.kernel.state.cognition["usage"]
        self.assertEqual(5, final_usage["player_dialogue_calls"])
        self.assertEqual(0, final_usage["budget_blocks"])

    def test_player_can_message_remote_npc_for_free_and_records_reply(self):
        bridge = CampusKernelBridge(42)
        before = bridge.snapshot()
        target_id = str(before["messaging"]["contacts"][0]["actor_id"])
        target_location = before["population"][target_id]["current_location_id"]
        self.assertNotEqual(before["player"]["current_location_id"], target_location)
        major_before = before["player"]["action_budget"]["major_remaining"]

        result = execute(bridge, "SEND_PHONE_MESSAGE", {
            "target_id": target_id,
            "text": "你好，今晚有空聊聊校园里的事吗？",
        })
        self.assertTrue(result["ok"])
        payload = result["result"]["payload"]
        self.assertEqual("free", payload["action_class"])
        self.assertEqual(1, len(payload["reply_messages"]))
        after = result["snapshot"]
        self.assertEqual(major_before, after["player"]["action_budget"]["major_remaining"])
        thread = after["messaging"]["threads"][target_id]
        self.assertEqual(2, len(thread["messages"]))
        self.assertEqual("player", thread["messages"][0]["sender_id"])
        self.assertEqual(target_id, thread["messages"][1]["sender_id"])
        self.assertEqual(1, thread["unread_count"])
        schema = json.loads(
            (REPOSITORY_DIR / "contracts/phone_message.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(set(schema["required"]), set(thread["messages"][0]))
        self.assertEqual([], list(campus_messaging_invariant(bridge.kernel.state)))

    def test_thread_read_state_and_validation_are_atomic(self):
        bridge = CampusKernelBridge(4)
        target_id = str(bridge.snapshot()["messaging"]["contacts"][0]["actor_id"])
        self.assertTrue(execute(bridge, "SEND_PHONE_MESSAGE", {
            "target_id": target_id, "text": "收到请回复。",
        })["ok"])
        read = execute(bridge, "MARK_PHONE_THREAD_READ", {"target_id": target_id})
        self.assertTrue(read["ok"])
        self.assertEqual(0, read["snapshot"]["messaging"]["threads"][target_id]["unread_count"])
        revision = read["snapshot"]["revision"]
        too_long = execute(bridge, "SEND_PHONE_MESSAGE", {
            "target_id": target_id, "text": "长" * 241,
        })
        self.assertFalse(too_long["ok"])
        self.assertEqual(revision, too_long["snapshot"]["revision"])

    def test_player_discovers_contacts_in_person_without_a_limit(self):
        bridge = CampusKernelBridge(12)
        before = bridge.snapshot()
        initial_ids = {
            contact["actor_id"] for contact in before["messaging"]["contacts"]
        }
        self.assertEqual(3, len(initial_ids))
        target_id = next(
            actor_id for actor_id, actor in before["population"].items()
            if actor_id not in initial_ids
            and actor.get("college_id") == "psychology"
        )
        rejected = execute(bridge, "ADD_PHONE_CONTACT", {"target_id": target_id})
        self.assertFalse(rejected["ok"])
        target_location = before["population"][target_id]["current_location_id"]
        destination_id = before["places"][target_location]["region_id"]
        traveled = execute(bridge, "FAST_TRAVEL_CAMPUS", {"destination_id": destination_id})
        self.assertTrue(traveled["ok"])
        budget_before = traveled["snapshot"]["player"]["action_budget"]["major_remaining"]
        added = execute(bridge, "ADD_PHONE_CONTACT", {"target_id": target_id})
        self.assertTrue(added["ok"])
        self.assertEqual(4, len(added["snapshot"]["messaging"]["contacts"]))
        self.assertTrue(added["snapshot"]["population"][target_id]["is_phone_contact"])
        self.assertEqual(
            budget_before,
            added["snapshot"]["player"]["action_budget"]["major_remaining"],
        )

    def test_npcs_exchange_remote_messages_with_pair_cooldown(self):
        bridge = CampusKernelBridge(17)
        seen: dict[tuple[str, str], int] = {}
        autonomous_messages = 0
        for step in range(8):
            result = execute(bridge, "ADVANCE_PHASE", step=step)
            self.assertTrue(result["ok"])
            execution = result["result"]["payload"]["phase_execution"]
            self.assertLessEqual(execution["phone_conversation_count"], 3)
            autonomous_messages += execution["phone_message_count"]
            state = bridge.kernel.state
            now = phase_index(state.clock.day, state.clock.phase)
            for pair_key, last in state.cognition["messaging"]["pair_last_autonomous_phase"].items():
                pair = tuple(pair_key.split("|"))
                changed_this_phase = pair not in seen or last != seen[pair]
                if pair in seen and changed_this_phase:
                    self.assertGreaterEqual(last - seen[pair], 2)
                seen[pair] = last
                if changed_this_phase:
                    left, right = pair
                    self.assertNotEqual(
                        state.population[left]["current_location_id"],
                        state.population[right]["current_location_id"],
                    )
                self.assertLessEqual(last, now)
        self.assertGreater(autonomous_messages, 0)
        self.assertEqual([], list(campus_messaging_invariant(bridge.kernel.state)))


if __name__ == "__main__":
    unittest.main()
