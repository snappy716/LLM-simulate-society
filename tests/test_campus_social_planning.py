from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from simulation.api.server import CampusKernelBridge
from simulation.systems.campus_daily_plans import daily_plans_invariant
from simulation.persistence.kernel_checkpoint import save_kernel_checkpoint, load_kernel_checkpoint
from tests.test_campus_cognition import LastLegalProvider, command


class SocialProvider(LastLegalProvider):
    def decide(self, request, *, max_output_tokens):
        result = super().decide(request, max_output_tokens=max_output_tokens)
        if request.daily_options is not None and request.social_options:
            social = request.social_options[0]
            result["social_choice"] = social["candidate_id"]
            result["daily_choices"][social["phase"]] = next(o["candidate_id"] for o in request.daily_options[social["phase"]]
                                                               if o["location_id"] == social["location_id"])
        return result


class SocialPlanningTests(unittest.TestCase):
    def setup_world(self):
        bridge = CampusKernelBridge(42)
        provider = SocialProvider()
        bridge.cognition_runtime.provider = provider
        for _ in range(4):
            self.assertTrue(command(bridge, "ADVANCE_PHASE")["ok"])
        return bridge, provider

    def test_plans_execute_with_receipts_no_daytime_model_calls_and_roundtrip(self):
        bridge, provider = self.setup_world()
        state = bridge.kernel.state
        planned = deepcopy(state.cognition["daily_plans"])
        social = [(n, phase, slot["social_intent"]) for n, slots in planned["actors"].items()
                  for phase, slot in slots.items() if slot.get("social_intent")]
        self.assertGreater(len(social), 0)
        self.assertEqual(20, sum(r.daily_options is not None for r in provider.requests))
        self.assertTrue(all(n != s["target_id"] and s["target_id"] != "player" for n, _, s in social))
        count = len(provider.requests), len(provider.dialogue_requests)
        events = []
        for _ in range(3):
            result = command(bridge, "ADVANCE_PHASE")
            self.assertTrue(result["ok"])
            events.extend(result["result"]["events"])
        self.assertEqual(count, (len(provider.requests), len(provider.dialogue_requests)))
        self.assertEqual(planned, bridge.kernel.state.cognition["daily_plans"])
        receipts = bridge.kernel.state.cognition["social_agenda_receipts"]["actors"]
        self.assertEqual({n for n, _, _ in social}, set(receipts))
        self.assertEqual([], list(daily_plans_invariant(bridge.kernel.state)))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "social.json"
            saved, rng = bridge.kernel.capture_checkpoint()
            save_kernel_checkpoint(path, saved, rng)
            loaded = load_kernel_checkpoint(path)
            self.assertEqual(receipts, loaded.state.cognition["social_agenda_receipts"]["actors"])

    def test_bad_social_ids_and_target_tampering_are_rejected(self):
        class BadProvider(SocialProvider):
            def decide(self, request, *, max_output_tokens):
                value = super().decide(request, max_output_tokens=max_output_tokens)
                if request.daily_options is not None:
                    value["social_choice"] = "invented-person-and-intention"
                return value
        bridge = CampusKernelBridge(42)
        bridge.cognition_runtime.provider = BadProvider()
        for _ in range(4):
            self.assertTrue(command(bridge, "ADVANCE_PHASE")["ok"])
        self.assertEqual(20, bridge.kernel.state.cognition["usage"]["rejected_responses"])
        valid, _ = self.setup_world()
        state = valid.kernel.state
        slot = next(s for slots in state.cognition["daily_plans"]["actors"].values() for s in slots.values() if s.get("social_intent"))
        slot["social_intent"]["target_id"] = "player"
        self.assertIn("invalid daily social intention", list(daily_plans_invariant(state)))

    def test_known_people_only_and_coherent_locations(self):
        bridge, provider = self.setup_world()
        for request in provider.requests:
            for option in request.social_options:
                self.assertNotEqual(request.npc_id, option["target_id"])
                self.assertEqual(bridge.kernel._state.population[option["target_id"]]["display_name"], option["target_name"])
                self.assertIn(option["location_id"], [s["location_id"] for s in request.daily_options[option["phase"]]])
                self.assertEqual(option["compatible_daily_choices"], [s["candidate_id"] for s in request.daily_options[option["phase"]]
                                                                      if s["location_id"] == option["location_id"]])

    def test_unmet_intention_never_teleports_and_has_one_receipt(self):
        from simulation.systems.campus_interactions import advance_campus_interactions, load_campus_interaction_policy
        from simulation.systems.campus_intelligence import load_campus_intelligence_policy
        from simulation.systems import ContentRegistry, DeterministicRngPool
        from simulation.systems.transactions import TransactionContext
        from simulation.actions.commands import SimulationCommand
        bridge, _ = self.setup_world()
        state = bridge.kernel.state
        plan = next((n, phase, slot["social_intent"]) for n, slots in state.cognition["daily_plans"]["actors"].items()
                    for phase, slot in slots.items() if slot.get("social_intent"))
        actor, phase, social = plan
        state.clock.phase = phase
        state.cognition.pop("social_agenda_receipts", None)
        # Explicit unit fixture: isolate exactly one social intent and make all
        # other NPCs unavailable; no production movement is replaced in-game.
        for n, slots in state.cognition["daily_plans"]["actors"].items():
            for slot in slots.values():
                if n != actor:
                    slot.pop("social_intent", None)
        for n in state.population:
            state.population[n]["current_activity"] = {"status": "blocked"}
        location = next(location for location in state.places if location != social["location_id"])
        state.population[social["target_id"]]["current_location_id"] = location
        registry = ContentRegistry.load_default(Path(__file__).resolve().parents[1] / "content")
        context = TransactionContext(state, DeterministicRngPool(42), SimulationCommand("fixture", "player", "ADVANCE_PHASE", state.revision))
        policy = load_campus_interaction_policy(registry)
        intelligence = load_campus_intelligence_policy(registry)
        for _ in range(2):
            advance_campus_interactions(context, policy, intelligence)
        self.assertEqual(location, state.population[social["target_id"]]["current_location_id"])
        self.assertEqual("not_met", state.cognition["social_agenda_receipts"]["actors"][actor]["status"])
        self.assertEqual(1, len([e for e in context.event_drafts if e.event_type == "NPC_SOCIAL_PLAN_RESOLVED"]))


if __name__ == "__main__":
    unittest.main()
