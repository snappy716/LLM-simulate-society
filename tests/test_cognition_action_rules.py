from dataclasses import replace
import unittest
from unittest.mock import patch

from simulation.api.server import CampusKernelBridge
from simulation.cognition.action_rules import action_rule_context, candidate_cost, COMMON_RULES, TRAIT_MEANINGS
from simulation.cognition.provider import OpenAICompatibleCognitionProvider, OllamaCognitionProvider, SHARED_RULE_GUIDANCE
from simulation.domain.campus import PERSONALITY_NAMES
from simulation.domain.cognition import BoundedDialogueRequest
from simulation.systems.campus_cognition import bind_cognition_identity
from tests.test_campus_cognition import LastLegalProvider


class ActionRulesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = CampusKernelBridge(42)

    def setUp(self):
        self.state = self.bridge.kernel.state
        self.actor = self.state.cognition["focused_ids"][0]

    def test_shared_rules_for_every_actor_are_detached_and_read_only(self):
        before = self.state.to_dict()
        for actor in self.state.population:
            rules = action_rule_context(self.state, actor)
            self.assertEqual(COMMON_RULES, rules["common"])
            self.assertEqual(self.state.clock.day, rules["clock"]["day"])
            rules["common"].clear()
            rules["phase_policy"]["morning"]["major_actions"] = 999
        self.assertEqual(before, self.state.to_dict())

    def test_budget_values_follow_runtime_policy_and_stale_is_unknown_not_free(self):
        economy = self.state.action_economy
        economy["policy"]["phases"]["morning"]["major_actions"] = 2
        economy["actors"][self.actor]["major_remaining"] = 0
        rules = action_rule_context(self.state, self.actor)
        self.assertEqual(2, rules["phase_policy"]["morning"]["major_actions"])
        self.assertEqual(0, rules["own_current_budget"]["major_remaining"])
        economy["actors"][self.actor]["day"] -= 1
        rules = action_rule_context(self.state, self.actor)
        self.assertFalse(rules["own_current_budget"]["known"])
        self.assertIsNone(rules["own_current_budget"]["major_remaining"])

    def test_reservation_exposes_only_own_current_boolean_not_private_details(self):
        self.state.parties["fixture-secret-party"] = {"members": {self.actor: {"departure": {
            "day": self.state.clock.day, "phase": self.state.clock.phase, "secret": "fixture-private-goal"}}}}
        rules = action_rule_context(self.state, self.actor)
        self.assertTrue(rules["own_current_budget"]["reserved_for_existing_commitment"])
        self.assertNotIn("fixture-private", str(rules))
        other = next(n for n in self.state.population if n != self.actor)
        self.assertFalse(action_rule_context(self.state, other)["own_current_budget"]["reserved_for_existing_commitment"])
        self.state.parties["fixture-secret-party"]["members"][self.actor]["departure"]["day"] += 1
        self.assertFalse(action_rule_context(self.state, self.actor)["own_current_budget"]["reserved_for_existing_commitment"])

    def test_binding_replaces_forged_rules_and_keeps_personal_differences(self):
        runtime = self.bridge.cognition_runtime
        a, b = self.state.cognition["focused_ids"][:2]
        self.state.population[a]["personality"]["extraversion"] = 1
        self.state.population[b]["personality"]["extraversion"] = 99
        requests = []
        for actor in (a, b):
            request = runtime._request(self.state, actor, [])
            request = replace(request, state={**request.state, "action_rules": {"unlimited_major": True}})
            requests.append(bind_cognition_identity(self.state, request))
        self.assertEqual([1, 99], [r.identity["personality"]["extraversion"] for r in requests])
        self.assertEqual(set(PERSONALITY_NAMES), set(TRAIT_MEANINGS))
        for r in requests:
            self.assertNotIn("unlimited_major", r.state["action_rules"])
            self.assertEqual(COMMON_RULES, r.state["action_rules"]["common"])

    def test_phone_player_and_npc_speech_all_receive_same_rules(self):
        runtime = self.bridge.cognition_runtime
        provider = LastLegalProvider()
        runtime.provider = provider
        ordinary = next(n for n in self.state.population if n != "player" and n not in self.state.cognition["focused_ids"])
        for actor in (self.actor, ordinary):
            self.assertIsNotNone(runtime.compose_phone_reply(self.state, actor, "player", "今天想做什么？", []))
            self.assertIsNotNone(runtime.compose_player_in_person_reply(self.state, actor, "player", "你愿意怎么安排？", {}, [], []))
        self.assertIsNotNone(runtime.compose_interaction_dialogue(self.state, self.actor, ordinary,
            {"intent_id": "exchange_ideas", "outcome": "accepted", "verified_summary": "已交换想法"}, [], []))
        self.assertEqual(5, len(provider.dialogue_requests))
        for request in provider.dialogue_requests:
            self.assertEqual(COMMON_RULES, request.state["action_rules"]["common"])
            self.assertNotIn("personal_goals", request.state)
            self.assertNotIn("anomaly_meetings", str(request.state["action_rules"]))
        self.assertEqual(0, self.state.cognition["usage"]["budget_blocks"])

    def test_costs_do_not_claim_healing_rest_or_unknown_actions_are_free(self):
        self.assertEqual(1, candidate_cost({"activity_id": "ATTEND_CLASS", "action_class": "major"})["major_action_cost"])
        self.assertEqual(0, candidate_cost({"activity_id": "BUY_ITEM", "action_class": "free"})["major_action_cost"])
        rest = candidate_cost({"activity_id": "REST", "action_class": "free"})
        self.assertIsNone(rest["major_action_cost"])
        self.assertIn("恢复", rest["cost_condition"])
        self.assertIsNone(candidate_cost({})["major_action_cost"])

    def test_both_provider_types_pass_shared_guidance_and_actor_rules(self):
        runtime = self.bridge.cognition_runtime
        request = bind_cognition_identity(self.state, runtime._request(self.state, self.actor, []))
        dialogue = BoundedDialogueRequest(npc_id=self.actor, target_id="player",
            candidate_revision=self.state.revision, day=self.state.clock.day, phase=self.state.clock.phase,
            identity=request.identity, state=request.state, relationship={}, recent_messages=(),
            incoming_text="今天有什么安排？", allowed_facts=(), dialogue_kind="phone", interaction_context={})
        providers = (OpenAICompatibleCognitionProvider("https://example.invalid", "fixture", "fixture-not-a-key"),
                     OllamaCognitionProvider("http://127.0.0.1:11434", "fixture"))
        for provider in providers:
            with patch.object(provider, "_complete_json", return_value={}) as transport:
                provider.decide(request, max_output_tokens=160)
                provider.decide(replace(request, daily_options={}), max_output_tokens=160)
                provider.respond(dialogue, max_output_tokens=160)
                self.assertEqual(3, transport.call_count)
                for call in transport.call_args_list:
                    self.assertIn(SHARED_RULE_GUIDANCE, call.args[0])
                    self.assertEqual(COMMON_RULES, call.args[1]["state"]["action_rules"]["common"])
                self.assertNotIn("只规划明天", transport.call_args_list[1].args[0])


if __name__ == "__main__":
    unittest.main()
