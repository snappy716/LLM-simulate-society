from __future__ import annotations

import json
import unittest
from pathlib import Path

from simulation.api.server import CampusKernelBridge
from simulation.systems import campus_interaction_invariant


REPOSITORY_DIR = Path(__file__).resolve().parents[1]


class DialogueProvider:
    name = "fake"
    model = "fake-player-dialogue"
    configured = True

    def __init__(self) -> None:
        self.requests = []

    def respond(self, request, *, max_output_tokens):
        self.requests.append(request)
        return {
            "npc_id": request.npc_id,
            "target_id": request.target_id,
            "candidate_revision": request.candidate_revision,
            "utterance": "我听见了。我们可以当面继续聊。",
            "fact_ids_used": [],
            "_usage": {"prompt_tokens": 40, "completion_tokens": 12},
        }


def talk(bridge: CampusKernelBridge, target_id: str, text: str, step: int = 0) -> dict:
    snapshot = bridge.snapshot()
    clock = snapshot["clock"]
    return bridge.execute({
        "command_id": f"talk-{step}-{snapshot['revision']}",
        "actor_id": "player",
        "action_id": "TALK_TO_NPC",
        "target_ids": [target_id],
        "parameters": {"target_id": target_id, "intent_id": "small_talk", "text": text},
        "expected_world_revision": snapshot["revision"],
        "issued_day": clock["day"],
        "issued_phase": clock["phase"],
        "issued_minute": clock["minute"],
        "source": "player",
    })


class PlayerNpcDialogueTests(unittest.TestCase):
    def _place_with_target(self, bridge: CampusKernelBridge) -> str:
        state = bridge.kernel._state
        target_id = sorted(actor_id for actor_id in state.population if actor_id != "player")[0]
        state.population["player"]["current_location_id"] = state.population[target_id]["current_location_id"]
        return target_id

    def test_face_to_face_dialogue_is_free_and_only_first_chat_applies_consequences(self):
        bridge = CampusKernelBridge(31)
        target_id = self._place_with_target(bridge)
        budget_before = bridge.snapshot()["player"]["action_budget"]["major_remaining"]
        first = talk(bridge, target_id, "你好，我想认识一下你。")
        second = talk(bridge, target_id, "我们再多聊几句吧。", 1)
        self.assertTrue(first["ok"])
        self.assertTrue(second["ok"])
        first_payload = first["result"]["payload"]
        second_payload = second["result"]["payload"]
        self.assertTrue(first_payload["consequence_applied"])
        self.assertFalse(second_payload["consequence_applied"])
        self.assertEqual("free", first_payload["action_class"])
        self.assertEqual(budget_before, second["snapshot"]["player"]["action_budget"]["major_remaining"])
        final_state = bridge.kernel.state
        self.assertEqual(2, len(final_state.cognition["interactions"]["player_dialogues"]))
        self.assertTrue(any(
            final_state.chronicles["entries"][entry_id]["event_type"] == "PLAYER_NPC_DIALOGUE_RESOLVED"
            for entry_id in final_state.chronicles["by_actor"][target_id]
        ))
        schema = json.loads((REPOSITORY_DIR / "contracts/player_npc_dialogue.schema.json").read_text())
        self.assertEqual(set(schema["required"]), set(second_payload))
        self.assertEqual([], list(campus_interaction_invariant(final_state)))

    def test_remote_dialogue_is_rejected_without_commit(self):
        bridge = CampusKernelBridge(33)
        state = bridge.kernel._state
        player_region = state.places[state.population["player"]["current_location_id"]]["region_id"]
        excluded_regions = {player_region, "central_region"}
        target_id = next(
            actor_id for actor_id, actor in sorted(state.population.items())
            if actor_id != "player"
            and state.places[actor["current_location_id"]]["region_id"] not in excluded_regions
        )
        revision_before = bridge.snapshot()["revision"]
        result = talk(bridge, target_id, "你听得到吗？")
        self.assertFalse(result["ok"])
        self.assertEqual("target_not_present", result["result"]["code"])
        self.assertEqual(revision_before, result["snapshot"]["revision"])

    def test_focused_npc_chat_has_no_llm_count_limit_even_when_automation_is_exhausted(self):
        bridge = CampusKernelBridge(35)
        target_id = self._place_with_target(bridge)
        state = bridge.kernel._state
        if target_id not in state.cognition["focused_ids"]:
            state.cognition["focused_ids"][-1] = target_id
        provider = DialogueProvider()
        bridge.cognition_runtime.provider = provider
        usage = state.cognition["usage"]
        usage["automated_calls"] = bridge.cognition_runtime.policy.daily_call_limit
        usage["automated_estimated_tokens"] = bridge.cognition_runtime.policy.daily_estimated_token_limit
        for index in range(6):
            result = talk(bridge, target_id, f"这是第 {index + 1} 次交谈。", index)
            self.assertTrue(result["ok"])
            self.assertEqual("llm", result["result"]["payload"]["wording_source"])
        self.assertEqual(6, len(provider.requests))
        final_usage = bridge.kernel.state.cognition["usage"]
        self.assertEqual(6, final_usage["player_dialogue_calls"])
        self.assertEqual(0, final_usage["budget_blocks"])


if __name__ == "__main__":
    unittest.main()
