"""Install and resolve data-driven college abilities for every campus actor."""
from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, Sequence

from simulation.domain.abilities import CampusAbilityDefinition, CardBlueprint
from simulation.domain.world_state import WorldState
from simulation.systems.content_registry import ContentRegistry


def load_campus_ability_definitions(
    registry: ContentRegistry,
) -> Dict[str, CampusAbilityDefinition]:
    document = registry.document("actions/college_skills.json")
    profiles = document.get("ability_profiles", {})
    definitions: Dict[str, CampusAbilityDefinition] = {}
    for ability_id, payload in registry.all("campus_ability").items():
        profile_id = str(payload["profile_id"])
        profile = profiles[profile_id]
        card = CardBlueprint(
            card_id=f"college:{ability_id}",
            name=str(payload["name"]),
            source_ability_id=ability_id,
            actor_bound=True,
            card_type=str(profile["card_type"]),
            command_cost=int(profile["cost"]),
            target=str(profile["target"]),
            range_pattern=str(profile["range_pattern"]),
            base_power=int(profile["base_power"]),
            effect_ids=tuple(str(value) for value in profile["effect_ids"]),
        )
        definitions[ability_id] = CampusAbilityDefinition(
            ability_id=ability_id,
            name=str(payload["name"]),
            college_id=str(payload["college_id"]),
            source_kind=str(payload["source_kind"]),
            profile_id=profile_id,
            check_tags=tuple(str(tag) for tag in payload["check_tags"]),
            surface_modifier=int(profile["surface_modifier"]),
            card=card,
        )
    return definitions


def install_campus_abilities(
    state: WorldState,
    definitions: Mapping[str, CampusAbilityDefinition],
    colleges: Mapping[str, Mapping[str, Any]],
) -> None:
    """Attach persistent progression and actor-bound card pools to the cast."""
    if not state.population:
        raise ValueError("campus population must be installed before abilities")
    if "campus_abilities" in state.metadata:
        raise ValueError("campus abilities are already initialized")
    if not definitions:
        raise ValueError("campus ability definitions cannot be empty")

    state.metadata["campus_abilities"] = {
        "definitions": {
            ability_id: definition.to_state_dict()
            for ability_id, definition in sorted(definitions.items())
        },
        "card_blueprints": {
            definition.card.card_id: definition.card.to_state_dict()
            for definition in sorted(definitions.values(), key=lambda value: value.card.card_id)
        },
        "college_loadouts": {
            college_id: {
                "common_ability_ids": list(college["common_skills"]),
                "specialization_ability_ids": list(college["specializations"]),
            }
            for college_id, college in sorted(colleges.items())
        },
        "rank_thresholds": [0, 100, 250, 450, 700],
    }
    for actor in state.population.values():
        if not isinstance(actor, dict):
            continue
        college_id = actor.get("college_id")
        college = colleges.get(str(college_id)) if college_id else None
        ability_ids: list[str] = []
        if college is not None:
            ability_ids.extend(str(value) for value in college["common_skills"])
            specialization_id = actor.get("specialization_id")
            if specialization_id in college["specializations"]:
                ability_ids.append(str(specialization_id))
        ability_ids = sorted(set(ability_ids))
        actor["ability_progress"] = {
            ability_id: {"rank": 1, "experience": 0}
            for ability_id in ability_ids
        }
        actor["card_pool_ids"] = [definitions[ability_id].card.card_id for ability_id in ability_ids]


def ability_modifier_for_check(
    state: WorldState,
    actor_id: str,
    check_tags: Sequence[str],
) -> Dict[str, Any]:
    """Return the best matching ability plus half of the second best, capped at six."""
    actor = state.population.get(actor_id)
    if not isinstance(actor, dict):
        raise KeyError(f"unknown campus actor: {actor_id}")
    requested_tags = {str(tag) for tag in check_tags if str(tag)}
    definitions = state.metadata.get("campus_abilities", {}).get("definitions", {})
    matches: list[Dict[str, Any]] = []
    for ability_id, progress in actor.get("ability_progress", {}).items():
        definition = definitions.get(ability_id)
        if not isinstance(definition, dict):
            continue
        overlap = requested_tags & set(definition.get("check_tags", ()))
        if not overlap:
            continue
        rank = int(progress.get("rank", 1))
        value = int(definition.get("surface_modifier", 0)) + max(0, (rank - 1) // 2)
        matches.append({
            "ability_id": ability_id,
            "name": definition.get("name", ability_id),
            "matched_tags": sorted(overlap),
            "rank": rank,
            "raw_modifier": value,
        })
    matches.sort(key=lambda entry: (-entry["raw_modifier"], entry["ability_id"]))
    contributions: list[Dict[str, Any]] = []
    if matches:
        first = dict(matches[0])
        first["applied_modifier"] = first["raw_modifier"]
        contributions.append(first)
    if len(matches) > 1:
        second = dict(matches[1])
        second["applied_modifier"] = second["raw_modifier"] // 2
        contributions.append(second)
    return {
        "actor_id": actor_id,
        "check_tags": sorted(requested_tags),
        "modifier": min(6, sum(entry["applied_modifier"] for entry in contributions)),
        "contributions": contributions,
    }


def available_card_blueprints(state: WorldState, actor_id: str) -> list[Dict[str, Any]]:
    actor = state.population.get(actor_id)
    if not isinstance(actor, dict):
        raise KeyError(f"unknown campus actor: {actor_id}")
    blueprints = state.metadata.get("campus_abilities", {}).get("card_blueprints", {})
    return [
        dict(blueprints[card_id])
        for card_id in actor.get("card_pool_ids", ())
        if card_id in blueprints
    ]


def grant_ability_experience(
    state: WorldState,
    actor_id: str,
    ability_id: str,
    amount: int,
) -> Dict[str, int]:
    if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
        raise ValueError("ability experience amount must be a non-negative integer")
    actor = state.population.get(actor_id)
    if not isinstance(actor, dict):
        raise KeyError(f"unknown campus actor: {actor_id}")
    progress = actor.get("ability_progress", {}).get(ability_id)
    if not isinstance(progress, dict):
        raise KeyError(f"actor does not know campus ability: {ability_id}")
    thresholds = state.metadata["campus_abilities"]["rank_thresholds"]
    experience = int(progress.get("experience", 0)) + amount
    rank = max(index + 1 for index, threshold in enumerate(thresholds) if experience >= threshold)
    progress.update({"rank": rank, "experience": experience})
    return {"rank": rank, "experience": experience}


def campus_ability_invariant(state: WorldState) -> Iterable[str]:
    errors: list[str] = []
    system = state.metadata.get("campus_abilities")
    if not isinstance(system, dict):
        return ["campus ability metadata is missing"]
    definitions = system.get("definitions", {})
    blueprints = system.get("card_blueprints", {})
    loadouts = system.get("college_loadouts", {})
    for actor_id, actor in state.population.items():
        if not isinstance(actor, dict):
            errors.append(f"campus actor {actor_id} must be a mapping")
            continue
        college_id = actor.get("college_id")
        progress = actor.get("ability_progress", {})
        cards = actor.get("card_pool_ids", [])
        expected_abilities: list[str] = []
        if college_id in loadouts:
            expected_abilities.extend(loadouts[college_id]["common_ability_ids"])
            specialization_id = actor.get("specialization_id")
            if specialization_id in loadouts[college_id]["specialization_ability_ids"]:
                expected_abilities.append(specialization_id)
        expected_abilities = sorted(set(expected_abilities))
        expected_cards = [definitions[ability_id]["card_id"] for ability_id in expected_abilities]
        if sorted(progress) != expected_abilities:
            errors.append(f"campus actor {actor_id} ability progress differs from known skills")
        if cards != expected_cards:
            errors.append(f"campus actor {actor_id} card pool differs from known abilities")
        for ability_id, values in progress.items():
            rank = values.get("rank") if isinstance(values, dict) else None
            experience = values.get("experience") if isinstance(values, dict) else None
            if isinstance(rank, bool) or not isinstance(rank, int) or not 1 <= rank <= 5:
                errors.append(f"campus actor {actor_id} ability {ability_id} has invalid rank")
            if isinstance(experience, bool) or not isinstance(experience, int) or experience < 0:
                errors.append(f"campus actor {actor_id} ability {ability_id} has invalid experience")
        if college_id in loadouts:
            common = set(loadouts[college_id]["common_ability_ids"])
            specializations = set(loadouts[college_id]["specialization_ability_ids"])
            if not common.issubset(progress):
                errors.append(f"campus actor {actor_id} lacks college common abilities")
            selected = set(progress) & specializations
            if len(selected) != 1 or actor.get("specialization_id") not in selected:
                errors.append(f"campus actor {actor_id} must have one college specialization")
        for card_id in cards:
            if card_id not in blueprints:
                errors.append(f"campus actor {actor_id} references unknown card {card_id}")
    return errors


__all__ = [
    "ability_modifier_for_check",
    "available_card_blueprints",
    "campus_ability_invariant",
    "grant_ability_experience",
    "install_campus_abilities",
    "load_campus_ability_definitions",
]
