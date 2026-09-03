from __future__ import annotations

import json
import unittest
from collections import Counter
from pathlib import Path

from simulation.domain import NightAccess, SimulationTier, WorldState
from simulation.systems import (
    CampusPopulationGenerator,
    ContentRegistry,
    DeterministicRngPool,
    install_campus_places,
    install_campus_population,
    load_campus_location_graph,
)


REPOSITORY_DIR = Path(__file__).resolve().parents[1]


class CampusPopulationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = ContentRegistry.load_default(REPOSITORY_DIR / "content")
        cls.graph = load_campus_location_graph(cls.registry)

    def generate(self, seed: int = 20260903):
        return CampusPopulationGenerator(
            self.registry,
            self.graph,
            DeterministicRngPool(seed),
        ).generate()

    def test_generates_exact_persistent_composition(self):
        records = self.generate()
        self.assertEqual(200, len(records))
        self.assertEqual(Counter({"student": 134, "staff": 66}), Counter(
            record.role_kind for record in records
        ))
        self.assertEqual(200, len({record.npc_id for record in records}))
        self.assertEqual(200, len({record.display_name for record in records}))

    def test_generation_is_seeded_and_reproducible(self):
        first = [record.to_state_dict() for record in self.generate(101)]
        second = [record.to_state_dict() for record in self.generate(101)]
        different = [record.to_state_dict() for record in self.generate(102)]
        self.assertEqual(first, second)
        self.assertNotEqual(first, different)

    def test_focused_and_night_tier_budgets_are_exact(self):
        records = self.generate()
        self.assertEqual(20, sum(
            record.profile.simulation_tier == SimulationTier.FOCUSED for record in records
        ))
        self.assertEqual(
            Counter({
                NightAccess.UNAWARE: 78,
                NightAccess.SENSITIVE: 60,
                NightAccess.CAPABLE: 40,
                NightAccess.WILLING: 22,
            }),
            Counter(record.profile.night_access for record in records),
        )

    def test_all_colleges_have_people_and_complete_skill_modules(self):
        records = self.generate()
        college_ids = set(self.registry.ids("college"))
        represented = {record.profile.college_id for record in records if record.profile.college_id}
        self.assertEqual(college_ids, represented)
        for record in records:
            if record.profile.college_id:
                college = self.registry.get("college", record.profile.college_id)
                self.assertTrue(set(college["common_skills"]).issubset(record.skill_ids))
                self.assertIn(record.profile.specialization_id, record.skill_ids)
                self.assertIn(record.profile.personal_trait_id, record.skill_ids)
                self.assertTrue(set(record.profile.relationship_skill_ids).issubset(record.skill_ids))
                self.assertGreaterEqual(len(record.skill_ids), 7)

    def test_homes_rooms_locations_and_permissions_are_semantically_stable(self):
        records = self.generate()
        for record in records:
            self.assertIn(record.home_location_id, self.graph.node_ids)
            self.assertIn(record.primary_location_id, self.graph.node_ids)
            self.assertIn(record.current_location_id, self.graph.node_ids)
            self.assertIn("campus_member", record.access_tags)
            self.assertTrue(record.home_room_key)
            if record.role_kind == "student":
                self.assertIn(record.home_location_id, {
                    "east_dorm_room_pool", "west_dorm_room_pool"
                })
                required = (
                    "east_dorm_access"
                    if record.home_location_id == "east_dorm_room_pool"
                    else "west_dorm_access"
                )
                self.assertIn(required, record.access_tags)
                self.assertRegex(record.home_room_key, r"^[EW][0-9]{2}-[1-4][0-9]{2}$")
            else:
                self.assertEqual("staff_residence", record.home_location_id)
                self.assertRegex(record.home_room_key, r"^S[0-9]{2}-[1-5][0-9]{2}$")

    def test_records_include_decision_driving_character_fields(self):
        for record in self.generate():
            profile = record.profile
            self.assertEqual(3, len(profile.core_values))
            self.assertEqual(2, len(profile.moral_boundaries))
            self.assertIsNotNone(profile.fear_id)
            self.assertIsNotNone(profile.obsession_id)
            self.assertIsNotNone(profile.contradiction_id)
            self.assertGreaterEqual(len(profile.identity_anchor_ids), 2)

    def test_population_installs_after_places_with_real_world_scale_metadata(self):
        state = WorldState(content_version=self.registry.content_version, master_seed=91)
        install_campus_places(state, self.graph)
        records = self.generate(91)
        install_campus_population(state, records)
        state.require_valid()
        self.assertEqual(201, len(state.population))
        self.assertEqual("south_gate_region", state.population["player"]["current_location_id"])
        metadata = state.metadata["campus_population"]
        self.assertEqual(200, metadata["represented_total"])
        self.assertEqual(5800, metadata["background_total"])
        self.assertEqual(6000, metadata["campus_total"])

    def test_generated_record_contract_is_valid_json_schema_shape(self):
        schema = json.loads(
            (REPOSITORY_DIR / "contracts" / "campus_population_record.schema.json").read_text(
                encoding="utf-8"
            )
        )
        record = self.generate()[0].to_state_dict()
        self.assertTrue(set(schema["required"]).issubset(record))
        self.assertEqual(set(schema["properties"]), set(record))


if __name__ == "__main__":
    unittest.main()
