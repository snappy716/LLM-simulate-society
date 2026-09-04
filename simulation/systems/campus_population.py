"""Deterministic creation and installation of the persistent campus cast."""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence

from simulation.domain.campus import (
    BaseAttributes,
    CampusNPCProfile,
    CampusNPCRecord,
    EmotionState,
    NeedState,
    NightAccess,
    PersonalityTraits,
    SimulationTier,
)
from simulation.domain.locations import CampusLocationGraph
from simulation.domain.world_state import WorldState
from simulation.systems.content_registry import ContentRegistry
from simulation.systems.randomness import DeterministicRngPool


class CampusPopulationError(ValueError):
    """Raised when population content cannot produce a valid persistent cast."""


class CampusPopulationGenerator:
    """Generate stable NPC identities without invoking an LLM.

    The generator consumes only the named ``npc_generation`` random stream, so
    adding randomness to trading, tasks, or combat cannot silently rewrite the
    campus cast for an existing master seed.
    """

    def __init__(
        self,
        registry: ContentRegistry,
        graph: CampusLocationGraph,
        rng_pool: DeterministicRngPool,
    ) -> None:
        self.registry = registry
        self.graph = graph
        self.rng = rng_pool.stream("npc_generation")
        self.config = registry.get("configuration", "campus_population")
        self.colleges = registry.all("college")
        self.clubs = registry.all("club")
        self._validate_content()

    def generate(self) -> List[CampusNPCRecord]:
        population = self.config["population"]
        student_count = int(population["students"])
        staff_count = int(population["staff"])
        names = self._unique_names(student_count + staff_count)
        student_colleges = self._balanced_college_ids(student_count)
        records: List[CampusNPCRecord] = []

        student_occupations: List[str] = []
        for occupation_id, count in self.config["student_occupations"].items():
            student_occupations.extend([occupation_id] * int(count))
        self.rng.shuffle(student_occupations)
        for index, (display_name, college_id, occupation_id) in enumerate(
            zip(names[:student_count], student_colleges, student_occupations), start=1
        ):
            records.append(self._make_record(
                npc_id=f"campus_student_{index:03d}",
                display_name=display_name,
                role_kind="student",
                occupation_id=occupation_id,
                college_id=college_id,
                ordinal=index,
            ))

        staff_specs: List[Dict[str, Any]] = []
        for spec in self.config["staff_occupations"]:
            staff_specs.extend([spec] * int(spec["count"]))
        self.rng.shuffle(staff_specs)
        all_college_ids = sorted(self.colleges)
        faculty_index = 0
        for index, (display_name, spec) in enumerate(
            zip(names[student_count:], staff_specs), start=1
        ):
            college_id: Optional[str] = spec.get("college_id")
            if spec.get("college_policy") == "all":
                college_id = all_college_ids[faculty_index % len(all_college_ids)]
                faculty_index += 1
            records.append(self._make_record(
                npc_id=f"campus_staff_{index:03d}",
                display_name=display_name,
                role_kind="staff",
                occupation_id=spec["id"],
                college_id=college_id,
                ordinal=index,
                primary_location_id=spec.get("primary_location_id"),
            ))

        self._assign_simulation_tiers(records)
        self._assign_night_access(records)
        self._validate_records(records)
        return records

    def _make_record(
        self,
        *,
        npc_id: str,
        display_name: str,
        role_kind: str,
        occupation_id: str,
        college_id: Optional[str],
        ordinal: int,
        primary_location_id: Optional[str] = None,
    ) -> CampusNPCRecord:
        if primary_location_id is None:
            if college_id is None:
                raise CampusPopulationError(f"{occupation_id} has no primary location")
            primary_location_id = self.config["college_primary_locations"][college_id]
        if role_kind == "student":
            east = ordinal % 2 == 1
            home_location_id = "east_dorm_room_pool" if east else "west_dorm_room_pool"
            wing = "E" if east else "W"
            room_ordinal = (ordinal + 1) // 2
            building = (room_ordinal - 1) // 24 + 1
            within = (room_ordinal - 1) % 24
            floor = within // 6 + 1
            room = within % 6 + 1
            home_room_key = f"{wing}{building:02d}-{floor}{room:02d}"
            dorm_access = "east_dorm_access" if east else "west_dorm_access"
        else:
            home_location_id = "staff_residence"
            building = (ordinal - 1) // 30 + 1
            within = (ordinal - 1) % 30
            floor = within // 6 + 1
            room = within % 6 + 1
            home_room_key = f"S{building:02d}-{floor}{room:02d}"
            dorm_access = "staff_residence_access"

        college = self.colleges.get(college_id) if college_id else None
        specialization_id = self.rng.choice(college["specializations"]) if college else None
        club_ids = self._choose_clubs(role_kind)
        personal_trait_id = self.rng.choice(self.config["personal_traits"])
        relationship_skill = self.rng.choice(self.config["relationship_skills"])
        skills: List[str] = []
        if college:
            skills.extend(college["common_skills"])
        if specialization_id:
            skills.append(specialization_id)
        skills.append(personal_trait_id)
        for club_id in club_ids:
            club = self.clubs[club_id]
            skills.extend((club["surface_skill"], club["night_skill"]))
        skills.append(relationship_skill)

        access_tags = ["campus_member", dorm_access]
        if college_id:
            access_tags.extend(self.config["college_access_tags"].get(college_id, ()))
        access_tags.extend(self.config["role_access_tags"].get(occupation_id, ()))
        if college_id == "bio_chemistry" and occupation_id in {
            "graduate_student", "student_assistant", "academic_faculty"
        }:
            access_tags.append("biosafety_access")

        identity_anchors = [f"home:{home_room_key}", f"role:{occupation_id}"]
        if college_id:
            identity_anchors.append(f"college:{college_id}")
        identity_anchors.extend(f"club:{club_id}" for club_id in club_ids)
        wealth_low, wealth_high = self.config["wealth_ranges"][role_kind]
        profile = CampusNPCProfile(
            npc_id=npc_id,
            college_id=college_id,
            occupation_id=occupation_id,
            attributes=self._attributes(college_id, occupation_id),
            personality=self._personality(),
            needs=self._needs(role_kind),
            emotions=self._emotions(),
            specialization_id=specialization_id,
            club_ids=club_ids,
            personal_trait_id=personal_trait_id,
            relationship_skill_ids=[relationship_skill],
            core_values=self._sample_unique(self.config["core_values"], 3),
            moral_boundaries=self._sample_unique(self.config["moral_boundaries"], 2),
            fear_id=self.rng.choice(self.config["fears"]),
            obsession_id=self.rng.choice(self.config["obsessions"]),
            contradiction_id=self.rng.choice(self.config["contradictions"]),
            identity_anchor_ids=identity_anchors,
        )
        return CampusNPCRecord(
            profile=profile,
            display_name=display_name,
            role_kind=role_kind,
            home_location_id=home_location_id,
            home_room_key=home_room_key,
            primary_location_id=primary_location_id,
            current_location_id=primary_location_id,
            schedule_id=self.config["schedules"][occupation_id],
            skill_ids=list(dict.fromkeys(skills)),
            access_tags=list(dict.fromkeys(access_tags)),
            appearance_seed=self.rng.randrange(0, 2**31),
            wealth=self.rng.randint(int(wealth_low), int(wealth_high)),
        )

    def _attributes(self, college_id: Optional[str], occupation_id: str) -> BaseAttributes:
        values = {
            "physique": self.rng.randint(3, 7),
            "dexterity": self.rng.randint(3, 7),
            "focus": self.rng.randint(3, 7),
            "insight": self.rng.randint(3, 7),
            "empathy": self.rng.randint(3, 7),
            "expression": self.rng.randint(3, 7),
        }
        for name, amount in self.config["college_attribute_biases"].get(college_id, {}).items():
            values[name] = min(10, values[name] + int(amount))
        role_biases = {
            "academic_faculty": {"focus": 1, "insight": 1},
            "psychology_counselor": {"empathy": 2, "expression": 1},
            "medical_staff": {"focus": 1, "empathy": 1},
            "campus_security": {"physique": 2},
            "maintenance_staff": {"dexterity": 2},
        }
        for name, amount in role_biases.get(occupation_id, {}).items():
            if name in values:
                values[name] = min(10, values[name] + amount)
        return BaseAttributes(**values)

    def _personality(self) -> PersonalityTraits:
        return PersonalityTraits(**{
            "extraversion": self.rng.randint(20, 80),
            "agreeableness": self.rng.randint(20, 80),
            "conscientiousness": self.rng.randint(25, 85),
            "openness": self.rng.randint(20, 85),
            "emotional_sensitivity": self.rng.randint(15, 85),
            "risk_tolerance": self.rng.randint(10, 80),
            "rule_alignment": self.rng.randint(20, 90),
            "altruism": self.rng.randint(15, 85),
        })

    def _needs(self, role_kind: str) -> NeedState:
        return NeedState(
            rest=self.rng.randint(10, 45),
            food=self.rng.randint(10, 45),
            safety=self.rng.randint(5, 35),
            social=self.rng.randint(5, 50),
            money=self.rng.randint(15, 60 if role_kind == "student" else 45),
            achievement=self.rng.randint(15, 60),
            curiosity=self.rng.randint(10, 65),
            commitment_pressure=self.rng.randint(10, 55),
        )

    def _emotions(self) -> EmotionState:
        return EmotionState(
            joy=self.rng.randint(5, 30),
            fear=self.rng.randint(0, 20),
            anger=self.rng.randint(0, 15),
            sadness=self.rng.randint(0, 20),
            shame=self.rng.randint(0, 15),
        )

    def _choose_clubs(self, role_kind: str) -> List[str]:
        roll = self.rng.random()
        if role_kind == "student":
            count = 2 if roll < 0.12 else 1 if roll < 0.72 else 0
        else:
            count = 1 if roll < 0.12 else 0
        return self._sample_unique(sorted(self.clubs), count)

    def _assign_simulation_tiers(self, records: Sequence[CampusNPCRecord]) -> None:
        focused_count = int(self.config["population"]["focused"])
        focused_ids = set(self.rng.sample([record.npc_id for record in records], focused_count))
        for record in records:
            record.profile.simulation_tier = (
                SimulationTier.FOCUSED if record.npc_id in focused_ids else SimulationTier.PERSISTENT
            )

    def _assign_night_access(self, records: Sequence[CampusNPCRecord]) -> None:
        shuffled = list(records)
        self.rng.shuffle(shuffled)
        cursor = 0
        for tier in (
            NightAccess.WILLING,
            NightAccess.CAPABLE,
            NightAccess.SENSITIVE,
            NightAccess.UNAWARE,
        ):
            count = int(self.config["population"]["night_access"][tier.value])
            for record in shuffled[cursor:cursor + count]:
                record.profile.night_access = tier
            cursor += count
        if cursor != len(records):
            raise CampusPopulationError("night access counts do not cover the persistent cast")

    def _unique_names(self, count: int) -> List[str]:
        names = [
            f"{surname}{given_name}"
            for surname in self.config["surnames"]
            for given_name in self.config["given_names"]
        ]
        if len(names) < count:
            raise CampusPopulationError("name pools cannot produce enough unique campus names")
        self.rng.shuffle(names)
        return names[:count]

    def _balanced_college_ids(self, count: int) -> List[str]:
        college_ids = sorted(self.colleges)
        result = [college_ids[index % len(college_ids)] for index in range(count)]
        self.rng.shuffle(result)
        return result

    def _sample_unique(self, values: Iterable[str], count: int) -> List[str]:
        choices = list(values)
        if count > len(choices):
            raise CampusPopulationError("sample count exceeds available values")
        return self.rng.sample(choices, count)

    def _validate_content(self) -> None:
        population = self.config.get("population", {})
        if int(population.get("students", -1)) + int(population.get("staff", -1)) != int(
            population.get("persistent", -2)
        ):
            raise CampusPopulationError("student and staff counts must equal persistent population")
        if sum(int(value) for value in self.config["student_occupations"].values()) != int(
            population["students"]
        ):
            raise CampusPopulationError("student occupation counts do not match student population")
        if sum(int(spec["count"]) for spec in self.config["staff_occupations"]) != int(
            population["staff"]
        ):
            raise CampusPopulationError("staff occupation counts do not match staff population")
        if sum(int(value) for value in population["night_access"].values()) != int(
            population["persistent"]
        ):
            raise CampusPopulationError("night access counts must cover persistent population")
        if set(self.config["college_primary_locations"]) != set(self.colleges):
            raise CampusPopulationError("each college requires one primary location")
        referenced_locations = set(self.config["college_primary_locations"].values())
        referenced_locations.update(
            spec["primary_location_id"]
            for spec in self.config["staff_occupations"]
            if "primary_location_id" in spec
        )
        unknown = referenced_locations - self.graph.node_ids
        if unknown:
            raise CampusPopulationError(f"population content references unknown locations: {sorted(unknown)}")

    def _validate_records(self, records: Sequence[CampusNPCRecord]) -> None:
        expected = int(self.config["population"]["persistent"])
        if len(records) != expected:
            raise CampusPopulationError(f"expected {expected} records, got {len(records)}")
        if len({record.npc_id for record in records}) != len(records):
            raise CampusPopulationError("generated NPC identifiers are not unique")
        if len({record.display_name for record in records}) != len(records):
            raise CampusPopulationError("generated NPC names are not unique")
        for record in records:
            for location_id in (
                record.home_location_id, record.primary_location_id, record.current_location_id
            ):
                if location_id not in self.graph.node_ids:
                    raise CampusPopulationError(
                        f"{record.npc_id} references unknown location: {location_id}"
                    )


def install_campus_population(
    state: WorldState,
    records: Iterable[CampusNPCRecord],
) -> None:
    """Install the player and persistent cast into an initialized campus state."""
    if state.population:
        raise ValueError("world population aggregate is already initialized")
    if not state.places:
        raise ValueError("campus places must be installed before population")
    cast = list(records)
    state.population["player"] = {
        "npc_id": "player",
        "display_name": "玩家",
        "role_kind": "student",
        "college_id": "psychology",
        "occupation_id": "new_psychology_student",
        "primary_location_id": "humanities_psychology_building",
        "current_location_id": "south_gate_region",
        "home_location_id": "east_dorm_room_pool",
        "home_room_key": "E01-101",
        "access_tags": ["campus_member", "east_dorm_access"],
        "simulation_tier": SimulationTier.FOCUSED.value,
        "night_access": NightAccess.SENSITIVE.value,
        "attributes": {
            "physique": 4,
            "dexterity": 5,
            "focus": 6,
            "insight": 6,
            "empathy": 6,
            "expression": 5,
        },
        "personality": {
            "extraversion": 50,
            "agreeableness": 55,
            "conscientiousness": 55,
            "openness": 65,
            "emotional_sensitivity": 50,
            "risk_tolerance": 45,
            "rule_alignment": 55,
            "altruism": 55,
        },
        "needs": {
            "rest": 20,
            "food": 20,
            "safety": 10,
            "social": 25,
            "money": 30,
            "achievement": 35,
            "curiosity": 45,
            "commitment_pressure": 25,
        },
        "emotions": {"joy": 15, "fear": 5, "anger": 0, "sadness": 5, "shame": 0},
        "specialization_id": "cognitive_psychology",
        "club_ids": [],
        "skill_ids": [
            "emotion_observation",
            "focus_stabilization",
            "cognitive_analysis",
            "supportive_communication",
            "cognitive_psychology",
        ],
        "wealth": 500,
        "is_player": True,
    }
    for record in cast:
        if record.npc_id in state.population:
            raise CampusPopulationError(f"duplicate installed NPC id: {record.npc_id}")
        state.population[record.npc_id] = record.to_state_dict()
    students = sum(record.role_kind == "student" for record in cast)
    staff = sum(record.role_kind == "staff" for record in cast)
    state.metadata["campus_population"] = {
        "represented_total": len(cast),
        "represented_students": students,
        "represented_staff": staff,
        "background_total": 5800,
        "campus_total": 6000,
        "campus_students": 4000,
        "campus_staff": 2000,
        "player_is_additional": True,
    }


__all__ = [
    "CampusPopulationError",
    "CampusPopulationGenerator",
    "install_campus_population",
]
