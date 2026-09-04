from __future__ import annotations

import json
import unittest
from collections import Counter
from pathlib import Path

from simulation.api import campus_world_view
from simulation.domain import CARD_RANGE_PATTERNS, CARD_TARGETS, CARD_TYPES, WorldState
from simulation.systems import (
    CampusPopulationGenerator,
    ContentRegistry,
    DeterministicRngPool,
    ability_modifier_for_check,
    available_card_blueprints,
    campus_ability_invariant,
    grant_ability_experience,
    install_campus_abilities,
    install_campus_places,
    install_campus_population,
    load_campus_ability_definitions,
    load_campus_location_graph,
)


REPOSITORY_DIR = Path(__file__).resolve().parents[1]


class CampusAbilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = ContentRegistry.load_default(REPOSITORY_DIR / "content")
        cls.graph = load_campus_location_graph(cls.registry)
        cls.definitions = load_campus_ability_definitions(cls.registry)

    def make_state(self, seed: int = 20260904) -> WorldState:
        state = WorldState(content_version=self.registry.content_version, master_seed=seed)
        install_campus_places(state, self.graph)
        records = CampusPopulationGenerator(
            self.registry, self.graph, DeterministicRngPool(seed)
        ).generate()
        install_campus_population(state, records)
        install_campus_abilities(state, self.definitions, self.registry.all("college"))
        return state

    def test_eight_colleges_define_56_valid_surface_and_card_abilities(self):
        self.assertEqual(56, len(self.definitions))
        counts = Counter(
            (definition.college_id, definition.source_kind)
            for definition in self.definitions.values()
        )
        for college_id in self.registry.ids("college"):
            self.assertEqual(4, counts[(college_id, "common")])
            self.assertEqual(3, counts[(college_id, "specialization")])
        for definition in self.definitions.values():
            self.assertTrue(definition.check_tags)
            self.assertTrue(definition.card.actor_bound)
            self.assertEqual(definition.ability_id, definition.card.source_ability_id)

    def test_every_college_actor_gets_four_common_one_specialization_and_five_cards(self):
        state = self.make_state()
        for actor_id, actor in state.population.items():
            if not actor.get("college_id"):
                continue
            ability_ids = set(actor["ability_progress"])
            college = self.registry.get("college", actor["college_id"])
            self.assertTrue(set(college["common_skills"]).issubset(ability_ids), actor_id)
            self.assertEqual(1, len(ability_ids & set(college["specializations"])), actor_id)
            self.assertEqual(5, len(actor["card_pool_ids"]), actor_id)
        self.assertEqual([], list(campus_ability_invariant(state)))

    def test_player_starts_with_psychology_specialization_and_card_pool(self):
        state = self.make_state()
        player = state.population["player"]
        self.assertEqual("cognitive_psychology", player["specialization_id"])
        self.assertEqual(5, len(player["ability_progress"]))
        cards = available_card_blueprints(state, "player")
        self.assertEqual(5, len(cards))
        self.assertTrue(all(card["actor_bound"] for card in cards))

    def test_surface_check_uses_best_plus_half_second_with_cap(self):
        state = self.make_state()
        result = ability_modifier_for_check(state, "player", ["cognition", "dialogue"])
        self.assertEqual(4, result["modifier"])
        self.assertEqual("cognitive_psychology", result["contributions"][0]["ability_id"])
        grant_ability_experience(state, "player", "cognitive_psychology", 700)
        boosted = ability_modifier_for_check(state, "player", ["cognition", "dialogue"])
        self.assertEqual(6, boosted["modifier"])

    def test_ability_installation_is_seed_stable_and_snapshot_is_public(self):
        first = self.make_state(88)
        second = self.make_state(88)
        self.assertEqual(
            first.metadata["campus_abilities"], second.metadata["campus_abilities"]
        )
        view = campus_world_view(first)
        self.assertEqual(14, view["view_version"])
        self.assertEqual(5, len(view["player"]["abilities"]))
        self.assertEqual(5, len(view["player"]["card_pool"]))
        npc = next(iter(view["population"].values()))
        self.assertIn("abilities", npc)
        self.assertIn("card_pool_ids", npc)
        self.assertNotIn("personality", npc)

    def test_combat_contracts_use_actor_bound_cards_instead_of_legacy_skill_commands(self):
        command_schema = json.loads(
            (REPOSITORY_DIR / "contracts/combat_command.schema.json").read_text(encoding="utf-8")
        )
        card_schema = json.loads(
            (REPOSITORY_DIR / "contracts/combat_card.schema.json").read_text(encoding="utf-8")
        )
        character_schema = json.loads(
            (REPOSITORY_DIR / "contracts/combat_character_card.schema.json").read_text(
                encoding="utf-8"
            )
        )
        battle_schema = json.loads(
            (REPOSITORY_DIR / "contracts/battle_state.schema.json").read_text(encoding="utf-8")
        )
        commands = set(command_schema["properties"]["command"]["enum"])
        self.assertEqual({
            "deploy_character", "reposition_character", "play_card",
            "discard_card", "end_round", "escape",
        }, commands)
        self.assertNotIn("skill_id", command_schema["properties"])
        self.assertEqual(CARD_TYPES, set(card_schema["properties"]["card_type"]["enum"]))
        self.assertEqual(CARD_TARGETS, set(card_schema["properties"]["target"]["enum"]))
        self.assertEqual(
            CARD_RANGE_PATTERNS,
            set(card_schema["properties"]["range_pattern"]["enum"]),
        )
        self.assertTrue({
            "character_cards", "formations", "shared_hand_ids", "insight_row_ids",
            "command_points", "enemy_intents",
        }.issubset(battle_schema["required"]))
        self.assertTrue({
            "actor_id", "deployment_state", "preferred_row", "base_command_id",
            "passive_ids", "command_card_ids",
        }.issubset(character_schema["required"]))


if __name__ == "__main__":
    unittest.main()
