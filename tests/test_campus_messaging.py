from __future__ import annotations

import json
import unittest
from pathlib import Path

from simulation.api.server import CampusKernelBridge
from simulation.systems import campus_messaging_invariant, phase_index


REPOSITORY_DIR = Path(__file__).resolve().parents[1]


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
