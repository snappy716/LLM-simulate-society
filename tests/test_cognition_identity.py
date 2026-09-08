import unittest
from simulation.api.server import CampusKernelBridge
from tests.test_campus_cognition import LastLegalProvider, command


class EchoProvider(LastLegalProvider):
    def respond(self, request, *, max_output_tokens):
        result = super().respond(request, max_output_tokens=max_output_tokens)
        result["utterance"] = request.incoming_text
        return result


class IdentityTests(unittest.TestCase):
    def test_player_dialogue_knows_current_names_and_only_own_routine(self):
        bridge = CampusKernelBridge(42)
        command(bridge, "ADVANCE_PHASE")
        provider = LastLegalProvider()
        bridge.cognition_runtime.provider = provider
        state = bridge.kernel.state
        actor = state.cognition["focused_ids"][0]
        for channel in ("phone", "in_person"):
            if channel == "phone":
                reply = bridge.cognition_runtime.compose_phone_reply(state, actor, "player", "你好", [])
            else:
                reply = bridge.cognition_runtime.compose_player_in_person_reply(state, actor, "player", "你好", {}, [], [])
            self.assertEqual("llm", reply["source"])
            request = provider.dialogue_requests[-1]
            self.assertEqual(actor, request.identity["npc_id"])
            self.assertEqual(state.population[actor]["display_name"], request.identity["display_name"])
            self.assertEqual("player", request.state["current_partner"]["npc_id"])
            self.assertIn("own_completed_activity", request.state)
            self.assertNotIn("memory_by_actor", request.state)
            self.assertNotIn("personal_goals", request.state)

    def test_long_echo_rejected_without_retry_or_clock_change(self):
        bridge = CampusKernelBridge(42)
        provider = EchoProvider()
        bridge.cognition_runtime.provider = provider
        state = bridge.kernel.state
        actor = state.cognition["focused_ids"][0]
        self.assertIsNone(bridge.cognition_runtime.compose_player_in_person_reply(state, actor, "player",
            "你好，最近在校园里过得怎么样？", {}, [], []))
        self.assertEqual(1, len(provider.dialogue_requests))
        self.assertEqual(1, state.cognition["usage"]["rejected_responses"])
        self.assertEqual(1, state.clock.day)

    def test_secret_night_activity_is_not_exposed_as_public_routine(self):
        bridge = CampusKernelBridge(42)
        provider = LastLegalProvider()
        bridge.cognition_runtime.provider = provider
        state = bridge.kernel.state
        actor = state.cognition["focused_ids"][0]
        state.population[actor]["current_activity"] = {"status": "completed", "activity_id": "NIGHT_CONTAINMENT", "location_id": "secret-place"}
        bridge.cognition_runtime.compose_player_in_person_reply(state, actor, "player", "今天忙吗", {}, [], [])
        self.assertEqual({}, provider.dialogue_requests[-1].state["own_completed_activity"])

    def test_overnight_identity_has_authoritative_names(self):
        bridge = CampusKernelBridge(42)
        provider = LastLegalProvider()
        bridge.cognition_runtime.provider = provider
        for _ in range(4):
            self.assertTrue(command(bridge, "ADVANCE_PHASE")["ok"])
        for request in provider.requests:
            self.assertEqual(request.npc_id, request.identity["npc_id"])
            self.assertEqual(bridge.kernel._state.population[request.npc_id]["display_name"], request.identity["display_name"])
            target = request.state.get("interaction_target")
            if target:
                self.assertEqual(target["npc_id"], request.state["current_partner"]["npc_id"])


if __name__ == "__main__":
    unittest.main()
