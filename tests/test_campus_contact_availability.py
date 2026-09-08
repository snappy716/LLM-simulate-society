"""Real stranded site plus explicitly labelled incapacity/retention boundaries."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from simulation.api.server import CampusKernelBridge
from simulation.actions.commands import SimulationCommand
from simulation.persistence.kernel_checkpoint import save_kernel_checkpoint, load_kernel_checkpoint
from simulation.systems import ContentRegistry, DeterministicRngPool
from simulation.systems.transactions import TransactionContext
from simulation.systems.campus_intelligence import load_campus_intelligence_policy
from simulation.systems.campus_messaging import (
    _append_message, _add_contact, advance_campus_phone_messages,
    advance_pending_phone_replies, campus_messaging_invariant,
    make_campus_messaging_handler, phone_available,
)
from tests.test_campus_disputes import command
from tests.test_campus_messaging import DialogueProvider
from tests.test_campus_welfare import prepare_welfare_fixture


class ContactAvailabilityTests(unittest.TestCase):
    def setUp(self):
        self.bridge = CampusKernelBridge(42)
        self.state, self.victim, self.helper, self.context, self.policy = prepare_welfare_fixture(self.bridge)
        self.provider = DialogueProvider()
        self.bridge.cognition_runtime.provider = self.provider

    def send(self, text="你好，还方便联系吗？"):
        result = command(self.bridge, "SEND_PHONE_MESSAGE", {"target_id": self.victim, "text": text})
        self.state = self.bridge.kernel._state
        return result

    def context_now(self):
        return TransactionContext(self.state, DeterministicRngPool(42),
            SimulationCommand("contact-test", "player", "ADVANCE_SOCIAL_PULSE", self.state.revision))

    def test_captive_send_succeeds_without_fabricated_reply_or_effects(self):
        before = deepcopy((self.state.population, self.state.relationships, self.state.knowledge,
                           self.state.clock, self.state.action_economy, self.state.inventories))
        result = self.send()
        self.assertTrue(result["ok"], result["result"]["code"])
        self.assertEqual("reply_pending", result["result"]["code"])
        self.assertEqual([], result["result"]["payload"]["reply_messages"])
        self.assertEqual([], result["result"]["payload"]["information_shares"])
        self.assertEqual([], self.provider.dialogue_requests)
        self.assertEqual(before, (self.state.population, self.state.relationships, self.state.knowledge,
                                  self.state.clock, self.state.action_economy, self.state.inventories))
        thread = result["snapshot"]["messaging"]["threads"][self.victim]
        self.assertEqual(1, len(thread["messages"]))
        self.assertEqual({"status", "first_tick", "last_tick", "distinct_phases"}, set(thread["contact_status"]))
        self.assertEqual([], list(campus_messaging_invariant(self.state)))

    def test_repeated_messages_no_quota_count_distinct_attempted_phases_only(self):
        for _ in range(4):
            self.assertTrue(self.send()["ok"])
        key = "player>" + self.victim
        self.assertEqual(1, self.state.cognition["messaging"]["contact_gaps"][key]["distinct_phases"])
        self.assertTrue(command(self.bridge, "ADVANCE_PHASE", {})["ok"])
        self.send()
        self.assertEqual(2, self.state.cognition["messaging"]["contact_gaps"][key]["distinct_phases"])
        self.assertEqual(1, len(self.state.cognition["messaging"]["pending_replies"]))
        self.assertEqual([], self.provider.dialogue_requests)

    def test_actual_dawn_release_resumes_once_not_healing_or_fake_llm_answer(self):
        self.send("第一条问题")
        self.send("第二条问题")
        for _ in range(2):
            result = command(self.bridge, "ADVANCE_PHASE", {})
            self.assertTrue(result["ok"], result["result"]["code"])
        self.state = self.bridge.kernel._state
        messages = self.state.cognition["messaging"]["messages"]
        replies = [m for m in messages.values() if m["source"] == "deferred_acknowledgment"
                   and m["sender_id"] == self.victim and m["receiver_id"] == "player"]
        self.assertEqual(1, len(replies))
        self.assertIn("第二条", messages[replies[0]["reply_to_message_id"]]["text"])
        before = deepcopy((self.state.population, self.state.relationships, self.state.action_economy))
        self.assertEqual(0, advance_pending_phone_replies(self.context_now(), self.policy)["phone_deferred_reply_count"])
        self.assertEqual(before, (self.state.population, self.state.relationships, self.state.action_economy))
        self.assertEqual("contact_resumed", self.bridge.snapshot()["messaging"]["threads"][self.victim]["contact_status"]["status"])
        count = len(self.provider.dialogue_requests)
        result = self.send("我们继续刚才的问题吧")
        self.assertEqual("llm", result["result"]["payload"]["reply_messages"][0]["source"])
        self.assertEqual(count + 1, len(self.provider.dialogue_requests))

    def test_normal_night_layer_phone_not_forbidden(self):
        # Explicit normal night-layer boundary, not a captive or a battle.
        state = self.state
        target = self.helper
        _add_contact(state, "player", target)
        state.situations["night_world"]["actor_states"].setdefault(target, {})["layer"] = "night"
        self.assertTrue(phone_available(state, target))
        handler = make_campus_messaging_handler(self.policy, None)
        # This direct no-runtime path is the same rule fallback used offline.
        outcome = handler(self.context, SimulationCommand("night-phone", "player", "SEND_PHONE_MESSAGE", state.revision,
            parameters={"target_id": target, "text": "夜里也可以保持联系"},
            issued_day=state.clock.day, issued_phase=state.clock.phase, source="player"))
        self.assertTrue(outcome.success)
        self.assertEqual(1, len(outcome.payload["reply_messages"]))

    def test_sender_unavailable_and_impersonation_rejected_atomically(self):
        handler = make_campus_messaging_handler(self.policy, None)
        before = deepcopy(self.state.cognition["messaging"])
        for source, expected in (("rule", "sender_unavailable"), ("player", "actor_not_authorized")):
            outcome = handler(self.context, SimulationCommand("invalid-sender", self.victim, "SEND_PHONE_MESSAGE", self.state.revision,
                parameters={"target_id": "player", "text": "不能假装可以主动联系"},
                issued_day=self.state.clock.day, issued_phase=self.state.clock.phase, source=source))
            self.assertFalse(outcome.success)
            self.assertEqual(expected, outcome.code)
        self.assertEqual(before, self.state.cognition["messaging"])

    def test_battle_and_zero_health_boundaries_do_not_leak_reasons(self):
        # Unit guards only; actual battle state transitions are covered globally.
        target = self.helper
        self.state.metadata.setdefault("campus_combat", {}).setdefault("active_battle_by_actor", {})[target] = "explicit-test-boundary"
        self.assertFalse(phone_available(self.state, target))
        self.state.metadata["campus_combat"]["active_battle_by_actor"].pop(target)
        self.state.population[target]["vitals"]["health"] = 0
        self.assertFalse(phone_available(self.state, target))

    def test_pending_checkpoint_and_old_save_optional_fields(self):
        self.assertEqual([], list(campus_messaging_invariant(self.state)))
        self.send()
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "pending.json"
            save_kernel_checkpoint(checkpoint, self.state, DeterministicRngPool(42))
            restored = load_kernel_checkpoint(checkpoint).state
            self.assertEqual(self.state.cognition["messaging"], restored.cognition["messaging"])
            self.assertEqual([], list(campus_messaging_invariant(restored)))
        key = "player>" + self.victim
        self.state.cognition["messaging"]["pending_replies"][key] = "nonexistent"
        self.assertTrue(list(campus_messaging_invariant(self.state)))

    def test_retention_does_not_invent_response_or_leave_orphan_pending(self):
        self.send()
        policy = replace(self.policy, max_messages_per_thread=2)
        self.state.cognition["messaging"]["policy"]["max_messages_per_thread"] = 2
        for _ in range(3):
            _append_message(self.state, "player", self.victim, "显式系统记录保留边界", policy, source="rule")
        aggregate = self.state.cognition["messaging"]
        self.assertEqual({}, aggregate["pending_replies"])
        self.assertEqual("record_expired", aggregate["contact_gaps"]["player>" + self.victim]["status"])
        self.assertEqual([], list(campus_messaging_invariant(self.state)))

    def test_real_structured_reply_closes_pending_without_extra_ack(self):
        from simulation.systems.campus_messaging import append_structured_phone_message
        from simulation.systems.campus_night_sites import upkeep_night_sites
        self.send()
        # Actual dawn site release, before ordinary pending-message processing.
        self.state.clock.day = 2
        self.state.clock.phase = "morning"
        context = self.context_now()
        upkeep_night_sites(context)
        reply = append_structured_phone_message(context, self.victim, "player", "现在可以联系了，谢谢关心。",
            self.policy, source="rule")
        gap = self.state.cognition["messaging"]["contact_gaps"]["player>" + self.victim]
        self.assertEqual("contact_resumed", gap["status"])
        self.assertEqual(reply["message_id"], gap["reply_id"])
        self.assertEqual(0, advance_pending_phone_replies(context, self.policy)["phone_deferred_reply_count"])
        self.assertEqual([], list(campus_messaging_invariant(self.state)))

    def test_npc_actual_attempt_no_response_no_relationship_or_intelligence_gain(self):
        # Explicit single contact pair and strong social need, not a natural-frequency claim.
        messaging = self.state.cognition["messaging"]
        messaging["contacts_by_actor"] = {n: [] for n in self.state.population}
        messaging["threads"], messaging["messages"] = {}, {}
        _add_contact(self.state, self.helper, self.victim)
        for actor in self.state.population.values():
            actor["needs"]["social"] = 0
        self.state.population[self.helper]["needs"]["social"] = 100
        self.state.population[self.victim]["needs"]["social"] = 90
        self.state.population[self.helper]["current_location_id"] = "hospital_clinic"
        messaging["pair_last_autonomous_phase"] = {}
        registry = ContentRegistry.load_default(Path(__file__).resolve().parents[1] / "content")
        before = deepcopy((self.state.relationships, self.state.knowledge, self.state.population))
        result = advance_campus_phone_messages(self.context, self.policy, load_campus_intelligence_policy(registry))
        self.assertEqual(1, result["phone_pending_count"])
        self.assertEqual(0, result["phone_conversation_count"])
        self.assertEqual(1, result["phone_message_count"])
        self.assertEqual(before, (self.state.relationships, self.state.knowledge, self.state.population))
        self.assertNotIn("contact_status", self.bridge.snapshot()["messaging"].get("threads", {}).get(self.victim, {}))
        self.assertEqual([], list(campus_messaging_invariant(self.state)))
