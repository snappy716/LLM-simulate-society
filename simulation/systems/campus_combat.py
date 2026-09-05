"""Authoritative character-card selection and three-row deployment runtime."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from typing import Any, Dict, Iterable, Mapping

from simulation.domain.campus import BaseAttributes, derive_stats
from simulation.domain.combat import (
    COMBAT_ROWS,
    CombatDeploymentPolicy,
    CombatRoundPolicy,
    parse_combat_deployment_policy,
    parse_combat_round_policy,
)
from simulation.domain.locations import CampusLocationGraph
from simulation.domain.world_state import WorldState
from simulation.systems.campus_night_world import moon_phase_for_day, night_world_policy_from_state
from simulation.systems.campus_parties import invitation_assessment, party_for_actor, party_policy_from_state
from simulation.systems.campus_tasks import complete_assigned_task
from simulation.systems.content_registry import ContentRegistry
from simulation.systems.transactions import TransactionOutcome
from simulation.systems.campus_vitals import change_vital


CAMPUS_COMBAT_SCHEMA_VERSION = 3
COMBAT_ACTION_IDS = {
    "START_BATTLE_PREPARATION",
    "DEPLOY_COMBAT_CHARACTER",
    "WITHDRAW_COMBAT_CHARACTER",
    "REPOSITION_COMBAT_CHARACTER",
    "CONFIRM_BATTLE_DEPLOYMENT",
    "CANCEL_BATTLE_PREPARATION",
    "START_CARD_COMBAT",
    "PLAY_COMBAT_CARD",
    "USE_COMBAT_BASE_COMMAND",
    "END_COMBAT_ROUND",
}


def load_combat_deployment_policy(registry: ContentRegistry) -> CombatDeploymentPolicy:
    return parse_combat_deployment_policy(registry.get("configuration", "combat_deployment"))


def load_combat_round_policy(registry: ContentRegistry) -> CombatRoundPolicy:
    return parse_combat_round_policy(registry.get("configuration", "combat_rounds"))


def combat_policy_from_state(state: WorldState) -> CombatDeploymentPolicy:
    payload = state.metadata.get("campus_combat", {}).get("policy")
    if not isinstance(payload, dict):
        raise ValueError("campus combat policy is not installed")
    return parse_combat_deployment_policy(payload)


def combat_round_policy_from_state(state: WorldState) -> CombatRoundPolicy:
    payload = state.metadata.get("campus_combat", {}).get("round_policy")
    if not isinstance(payload, dict):
        raise ValueError("campus combat round policy is not installed")
    return parse_combat_round_policy(payload)


def install_campus_combat(
    state: WorldState,
    policy: CombatDeploymentPolicy,
    round_policy: CombatRoundPolicy,
    enemy_archetypes: Mapping[str, Mapping[str, Any]],
) -> None:
    if state.battles:
        raise ValueError("campus battles are already initialized")
    if "campus_combat" in state.metadata:
        raise ValueError("campus combat runtime is already initialized")
    if not state.parties or "night_world" not in state.situations:
        raise ValueError("party and night-world runtimes must exist before combat")
    if not enemy_archetypes:
        raise ValueError("at least one combat enemy archetype is required")
    required_enemy_fields = {
        "id", "name", "max_health", "defense", "resistance", "speed",
        "preferred_row", "weaknesses", "knowledge_tags",
    }
    for archetype_id, archetype in enemy_archetypes.items():
        if str(archetype.get("id", "")) != archetype_id:
            raise ValueError(f"combat enemy archetype id mismatch: {archetype_id}")
        if required_enemy_fields - set(archetype):
            raise ValueError(f"combat enemy archetype {archetype_id} is incomplete")
        if archetype.get("preferred_row") not in COMBAT_ROWS:
            raise ValueError(f"combat enemy archetype {archetype_id} has an invalid row")
    state.metadata["campus_combat"] = {
        "schema_version": CAMPUS_COMBAT_SCHEMA_VERSION,
        "policy": policy.to_dict(),
        "round_policy": round_policy.to_dict(),
        "enemy_archetypes": deepcopy(dict(enemy_archetypes)),
        "battle_sequence": 0,
        "active_battle_by_actor": {},
    }


def _actor_region_id(state: WorldState, actor_id: str) -> str:
    actor = state.population.get(actor_id, {})
    location_id = str(actor.get("current_location_id", "")) if isinstance(actor, dict) else ""
    place = state.places.get(location_id, {})
    if not isinstance(place, dict):
        return ""
    return location_id if place.get("node_type") == "region" else str(place.get("region_id", ""))


def _owned_night_tasks(state: WorldState, actor_id: str) -> list[Dict[str, Any]]:
    return sorted(
        (
            task for task in state.tasks.values()
            if isinstance(task, dict)
            and task.get("forum") == "night"
            and task.get("assignee_id") == actor_id
            and task.get("state") in {"locked", "in_progress"}
        ),
        key=lambda task: (int(task.get("created_day", 0)), str(task.get("task_id", ""))),
    )


def active_battle_for_actor(state: WorldState, actor_id: str) -> Dict[str, Any] | None:
    battle_id = state.metadata.get("campus_combat", {}).get(
        "active_battle_by_actor", {}
    ).get(actor_id)
    battle = state.battles.get(str(battle_id or ""))
    return battle if isinstance(battle, dict) else None


def _task_for_preparation(
    state: WorldState,
    actor_id: str,
    task_id: str,
) -> Dict[str, Any] | None:
    tasks = _owned_night_tasks(state, actor_id)
    if task_id:
        return next((task for task in tasks if task.get("task_id") == task_id), None)
    actor_region = _actor_region_id(state, actor_id)
    return next(
        (task for task in tasks if task.get("execution_region_id") == actor_region),
        None,
    )


def _engaged_task_id(state: WorldState, actor_id: str) -> str:
    for task in state.tasks.values():
        if (
            isinstance(task, dict)
            and task.get("assignee_id") == actor_id
            and task.get("state") in {"locked", "in_progress"}
        ):
            return str(task.get("task_id", ""))
    return ""


def combat_readiness_assessment(
    state: WorldState,
    leader_id: str,
    actor_id: str,
    policy: CombatDeploymentPolicy,
    *,
    situation_id: str = "",
    graph: CampusLocationGraph | None = None,
) -> Dict[str, Any]:
    actor = state.population.get(actor_id)
    party = party_for_actor(state, leader_id)
    if not isinstance(actor, dict) or not isinstance(party, dict):
        return {"eligible": False, "reason": "unknown_actor_or_party"}
    if actor_id not in party.get("member_ids", ()):
        return {"eligible": False, "reason": "not_party_member"}
    if actor.get("vitals", {}).get("health", 1) <= 0:
        return {"eligible": False, "reason": "incapacitated"}
    if actor_id != leader_id:
        party_policy = party_policy_from_state(state)
        willingness = invitation_assessment(state, leader_id, actor_id, party_policy)
        if (
            not willingness.get("eligible")
            or int(willingness.get("score", -1000)) < party_policy.withdrawal_score_threshold
        ):
            return {"eligible": False, "reason": "commitment_withdrawn"}
        if actor.get("night_access") not in {"capable", "willing"}:
            return {"eligible": False, "reason": "night_access_unavailable"}
    fear = int(actor.get("emotions", {}).get("fear", 0))
    injury = int(actor.get("injury_severity", actor.get("conditions", {}).get("injury", 0)))
    night_state = state.situations.get("night_world", {}).get("actor_states", {}).get(actor_id, {})
    pollution = int(night_state.get("pollution", 0))
    if fear >= policy.fear_limit:
        return {"eligible": False, "reason": "fear_limit", "value": fear}
    if injury >= policy.injury_limit:
        return {"eligible": False, "reason": "injury_limit", "value": injury}
    if pollution >= policy.pollution_limit:
        return {"eligible": False, "reason": "pollution_limit", "value": pollution}
    task = state.tasks.get(situation_id, {})
    forbidden = set(task.get("forbidden_boundary_ids", ())) if isinstance(task, dict) else set()
    crossed = forbidden.intersection(actor.get("moral_boundaries", ()))
    if crossed:
        return {
            "eligible": False,
            "reason": "moral_boundary",
            "boundary_ids": sorted(crossed),
        }
    engaged_task_id = _engaged_task_id(state, actor_id)
    if engaged_task_id and engaged_task_id != situation_id:
        return {
            "eligible": False,
            "reason": "other_task_commitment",
            "task_id": engaged_task_id,
        }
    if graph is not None and actor_id != leader_id:
        destination_id = str(state.population[leader_id].get("current_location_id", ""))
        route = graph.shortest_route(
            str(actor.get("current_location_id", "")),
            destination_id,
            phase=state.clock.phase,
            access_tags=actor.get("access_tags", ()),
        )
        if route is None:
            return {"eligible": False, "reason": "route_unavailable"}
    return {
        "eligible": True,
        "reason": "ready",
        "fear": fear,
        "injury": injury,
        "pollution": pollution,
    }


def combat_preparation_assessment(
    state: WorldState,
    actor_id: str,
    policy: CombatDeploymentPolicy,
    *,
    task_id: str = "",
) -> Dict[str, Any]:
    if actor_id not in state.population:
        return {"allowed": False, "reason": "unknown_actor"}
    if active_battle_for_actor(state, actor_id) is not None:
        return {"allowed": False, "reason": "battle_already_active"}
    if state.population[actor_id].get("vitals", {}).get("health", 1) <= 0:
        return {"allowed": False, "reason": "incapacitated"}
    if state.clock.phase not in policy.setup_phases:
        return {"allowed": False, "reason": "invalid_phase"}
    night_state = state.situations.get("night_world", {}).get("actor_states", {}).get(actor_id, {})
    if night_state.get("layer") != policy.required_world_layer:
        return {"allowed": False, "reason": "night_layer_required"}
    party = party_for_actor(state, actor_id)
    if not isinstance(party, dict) or party.get("leader_id") != actor_id:
        return {"allowed": False, "reason": "party_leader_required"}
    task = _task_for_preparation(state, actor_id, task_id)
    if task is None:
        return {"allowed": False, "reason": "owned_night_task_required"}
    if task.get("execution_region_id") != _actor_region_id(state, actor_id):
        return {
            "allowed": False,
            "reason": "task_location_required",
            "required_region_id": task.get("execution_region_id"),
        }
    return {"allowed": True, "reason": "available", "task": task}


def _preferred_row(actor: Mapping[str, Any], policy: CombatDeploymentPolicy) -> str:
    attributes = actor.get("attributes", {})
    scores = {
        row: sum(
            int(attributes.get(attribute, 5)) * int(weight)
            for attribute, weight in policy.preferred_row_weights[row].items()
        )
        for row in COMBAT_ROWS
    }
    return max(COMBAT_ROWS, key=lambda row: (scores[row], -COMBAT_ROWS.index(row)))


def build_character_card(
    state: WorldState,
    battle_id: str,
    actor_id: str,
    team_id: str,
    policy: CombatDeploymentPolicy,
) -> Dict[str, Any]:
    actor = state.population[actor_id]
    attributes = BaseAttributes(**actor.get("attributes", {}))
    derived = derive_stats(
        attributes,
        identity_anchor_count=len(actor.get("identity_anchor_ids", ())),
    )
    preferred_row = _preferred_row(actor, policy)
    passive_ids: list[str] = []
    personal_trait_id = str(actor.get("personal_trait_id", ""))
    if personal_trait_id:
        passive_ids.append(personal_trait_id)
    passive_ids.extend(map(str, actor.get("relationship_skill_ids", ())))
    for club_id in actor.get("club_ids", ()):
        club = state.organizations.get(str(club_id), {})
        night_skill = str(club.get("night_skill", "")) if isinstance(club, dict) else ""
        if night_skill:
            passive_ids.append(night_skill)
    command_card_ids = list(map(str, actor.get("card_pool_ids", ())))
    if not command_card_ids:
        command_card_ids = [policy.fallback_command_card_id]
    return {
        "character_card_instance_id": f"{battle_id}:character:{actor_id}",
        "actor_id": actor_id,
        "display_name": str(actor.get("display_name", actor_id)),
        "team_id": team_id,
        "deployment_state": "reserve",
        "row": None,
        "allowed_rows": list(policy.allowed_rows),
        "preferred_row": preferred_row,
        "deployment_cost": 0,
        "max_health": actor.get("vitals", {}).get("max_health", derived.max_health),
        "max_focus": actor.get("vitals", {}).get("max_focus", derived.max_focus),
        "defense": round(derived.defense),
        "resistance": max(0, round(derived.stability_threshold / 4)),
        "speed": derived.speed,
        "physical_power": derived.physical_power,
        "technique_power": derived.technique_power,
        "cognitive_power": derived.cognitive_power,
        "support_power": derived.support_power,
        "base_command_id": str(policy.base_commands[preferred_row]),
        "passive_ids": list(dict.fromkeys(passive_ids)),
        "command_card_ids": list(dict.fromkeys(command_card_ids)),
    }


def _build_enemy_unit(
    battle_id: str,
    archetype: Mapping[str, Any],
    sequence: int = 1,
) -> Dict[str, Any]:
    archetype_id = str(archetype["id"])
    enemy_id = f"{battle_id}:enemy:{archetype_id}:{sequence:02d}"
    return {
        "enemy_instance_id": enemy_id,
        "archetype_id": archetype_id,
        "display_name": str(archetype["name"]),
        "row": str(archetype["preferred_row"]),
        "max_health": int(archetype["max_health"]),
        "defense": int(archetype["defense"]),
        "resistance": int(archetype["resistance"]),
        "speed": int(archetype["speed"]),
        "weaknesses": list(map(str, archetype.get("weaknesses", ()))),
        "knowledge_tags": list(map(str, archetype.get("knowledge_tags", ()))),
        "statuses": [],
    }


def _new_battle(
    state: WorldState,
    leader_id: str,
    task: Mapping[str, Any],
    policy: CombatDeploymentPolicy,
    graph: CampusLocationGraph,
) -> Dict[str, Any]:
    metadata = state.metadata["campus_combat"]
    metadata["battle_sequence"] = int(metadata["battle_sequence"]) + 1
    battle_id = f"battle:{int(metadata['battle_sequence']):06d}"
    party = party_for_actor(state, leader_id)
    assert isinstance(party, dict)
    team_id = str(party["party_id"])
    candidate_ids = [
        actor_id for actor_id in party["member_ids"]
        if combat_readiness_assessment(
            state, leader_id, actor_id, policy,
            situation_id=str(task.get("task_id", "")), graph=graph,
        ).get("eligible")
    ][:policy.max_friendly_characters]
    if leader_id not in candidate_ids:
        candidate_ids.insert(0, leader_id)
    character_cards = {
        f"{battle_id}:character:{actor_id}": build_character_card(
            state, battle_id, actor_id, team_id, policy
        )
        for actor_id in candidate_ids
    }
    archetype_id = str(task.get("enemy_archetype_id", ""))
    archetype = state.metadata["campus_combat"]["enemy_archetypes"].get(archetype_id)
    if not isinstance(archetype, dict):
        raise ValueError(f"night task references unknown combat enemy: {archetype_id}")
    enemy = _build_enemy_unit(battle_id, archetype)
    enemy_id = str(enemy["enemy_instance_id"])
    card_ids_by_actor = {
        card["actor_id"]: list(card["command_card_ids"])
        for card in character_cards.values()
    }
    night_states = state.situations["night_world"]["actor_states"]
    battle = {
        "battle_id": battle_id,
        "revision": 1,
        "phase": "setup",
        "round": 1,
        "scene_id": str(state.population[leader_id].get("current_location_id", "")),
        "situation_id": str(task.get("task_id", "")),
        "participant_ids": list(candidate_ids),
        "team_ids": {team_id: list(candidate_ids)},
        "character_cards": character_cards,
        "formations": {team_id: {row: [] for row in COMBAT_ROWS}},
        "enemy_units": {enemy_id: enemy},
        "enemy_formations": {
            row: ([enemy_id] if row == enemy["row"] else []) for row in COMBAT_ROWS
        },
        "reserve_character_card_ids": list(character_cards),
        "actor_decks": card_ids_by_actor,
        "draw_piles": {actor_id: [] for actor_id in candidate_ids},
        "discard_piles": {actor_id: [] for actor_id in candidate_ids},
        "exhaust_piles": {actor_id: [] for actor_id in candidate_ids},
        "reshuffle_counts": {actor_id: 0 for actor_id in candidate_ids},
        "shared_hand_ids": [],
        "insight_row_ids": [],
        "base_command_used_actor_ids": [],
        "command_points": {team_id: 3},
        "command_point_cap": 3,
        "focus": {
            card["actor_id"]: int(state.population[card["actor_id"]].get("vitals", {}).get("focus", card["max_focus"]))
            for card in character_cards.values()
        },
        "health": {
            card["actor_id"]: int(state.population[card["actor_id"]].get("vitals", {}).get("health", card["max_health"]))
            for card in character_cards.values()
        },
        "pollution": {
            actor_id: int(night_states[actor_id].get("pollution", 0))
            for actor_id in candidate_ids
        },
        "statuses": {actor_id: [] for actor_id in candidate_ids},
        "barriers": {actor_id: 0 for actor_id in candidate_ids},
        "enemy_health": {enemy_id: int(enemy["max_health"])},
        "known_weaknesses": [],
        "enemy_intents": {},
        "card_instances": {},
        "result": "active",
        "consequences": {"incapacitated_actor_ids": []},
    }
    return battle


def _battle_from_command(state: WorldState, actor_id: str, parameters: Mapping[str, Any]):
    battle_id = str(parameters.get("battle_id", ""))
    battle = state.battles.get(battle_id) if battle_id else active_battle_for_actor(state, actor_id)
    if not isinstance(battle, dict):
        return None, "unknown_battle"
    expected = parameters.get("expected_battle_revision")
    if expected is not None and int(expected) != int(battle.get("revision", 0)):
        return None, "battle_revision_conflict"
    mapping = state.metadata["campus_combat"]["active_battle_by_actor"]
    if mapping.get(actor_id) != battle.get("battle_id"):
        return None, "battle_control_denied"
    return battle, ""


def _card_from_command(battle: Mapping[str, Any], parameters: Mapping[str, Any]):
    card_id = str(parameters.get("character_card_instance_id", ""))
    card = battle.get("character_cards", {}).get(card_id)
    return (card, card_id) if isinstance(card, dict) else (None, card_id)


def _remove_from_formation(battle: Dict[str, Any], card_id: str) -> None:
    for formation in battle["formations"].values():
        for row in COMBAT_ROWS:
            if card_id in formation[row]:
                formation[row].remove(card_id)


def _assemble_actor(
    context,
    graph: CampusLocationGraph,
    actor_id: str,
    leader_id: str,
) -> TransactionOutcome | None:
    if actor_id == leader_id:
        return None
    state = context.state
    actor = state.population[actor_id]
    destination_id = str(state.population[leader_id].get("current_location_id", ""))
    route = graph.shortest_route(
        str(actor.get("current_location_id", "")), destination_id,
        phase=state.clock.phase, access_tags=actor.get("access_tags", ()),
    )
    if route is None:
        return TransactionOutcome(False, False, "route_unavailable", "队员当前无法沿校园道路抵达。")
    # The explicit player-led assembly supersedes the NPC's completed routine
    # for this phase; keeping that old activity attached to its former place
    # would make the authoritative movement ledger contradictory.
    actor["current_activity"] = None
    actor["current_decision"] = None
    for index, step in enumerate(route.steps):
        actor["current_location_id"] = step.to_id
        context.emit(
            "ACTOR_LOCATION_CHANGED",
            f"{actor.get('display_name', actor_id)}沿校园道路前往战斗集合点。",
            actor_ids=[actor_id], scene_id=step.to_id,
            payload={
                "passage_id": step.passage_id, "from_id": step.from_id,
                "to_id": step.to_id, "travel_minutes": step.travel_minutes,
                "route_index": index, "combat_assembly": True,
            },
            visibility="observable", severity=1,
            knowledge_tags=["location", "party", "combat_assembly"],
        )
    night_state = state.situations["night_world"]["actor_states"][actor_id]
    if night_state.get("layer") != "night":
        night_policy = night_world_policy_from_state(state)
        if night_policy is None:
            return TransactionOutcome(False, False, "night_world_unavailable", "夜相运行时不可用。")
        moon = moon_phase_for_day(night_policy, state.clock.day)
        night_state["layer"] = "night"
        night_state["night_forum_discovered"] = True
        night_state["pollution"] = min(
            100, int(night_state.get("pollution", 0)) + int(moon["entry_pollution"])
        )
        night_state["last_transition_day"] = state.clock.day
        night_state["last_transition_phase"] = state.clock.phase
        state.situations["night_world"]["transition_sequence"] += 1
        context.emit(
            "NIGHT_WORLD_ENTERED",
            f"{actor.get('display_name', actor_id)}在集合点进入了校园夜相。",
            actor_ids=[actor_id], scene_id=destination_id,
            payload={
                "layer": "night", "moon_phase_id": moon["id"],
                "moon_intensity": moon["intensity"], "pollution": night_state["pollution"],
                "action_class": "free", "combat_assembly": True,
            },
            visibility="secret", severity=4,
            knowledge_tags=["night_world", "party", "combat_assembly", "pollution"],
        )
    return None


def _combat_card_blueprints(
    state: WorldState,
    round_policy: CombatRoundPolicy,
) -> Dict[str, Dict[str, Any]]:
    blueprints = {
        str(card_id): deepcopy(dict(payload))
        for card_id, payload in state.metadata.get("campus_abilities", {}).get(
            "card_blueprints", {}
        ).items()
        if isinstance(payload, dict)
    }
    blueprints.update({
        str(card_id): deepcopy(dict(payload))
        for card_id, payload in round_policy.generic_card_blueprints.items()
    })
    blueprints.update({
        str(card_id): deepcopy(dict(payload))
        for card_id, payload in round_policy.base_command_blueprints.items()
    })
    return blueprints


def _character_for_actor(battle: Mapping[str, Any], actor_id: str) -> Dict[str, Any] | None:
    return next(
        (
            card for card in battle.get("character_cards", {}).values()
            if isinstance(card, dict) and card.get("actor_id") == actor_id
        ),
        None,
    )


def legal_combat_targets(
    battle: Mapping[str, Any],
    source_actor_id: str,
    blueprint: Mapping[str, Any],
) -> list[str]:
    """Return authoritative one-target options for a card or base command."""
    living_allies = [
        str(actor_id) for actor_id in battle.get("participant_ids", ())
        if int(battle.get("health", {}).get(actor_id, 0)) > 0
        and isinstance(_character_for_actor(battle, str(actor_id)), dict)
        and _character_for_actor(battle, str(actor_id)).get("deployment_state") == "deployed"
    ]
    living_enemies = {
        str(enemy_id) for enemy_id in battle.get("enemy_units", {})
        if int(battle.get("enemy_health", {}).get(enemy_id, 0)) > 0
    }
    target_kind = str(blueprint.get("target", ""))
    pattern = str(blueprint.get("range_pattern", ""))
    if target_kind in {"ally", "self_or_ally"}:
        if pattern == "same_or_adjacent_ally":
            source = _character_for_actor(battle, source_actor_id)
            if not isinstance(source, dict) or source.get("row") not in COMBAT_ROWS:
                return []
            source_index = COMBAT_ROWS.index(str(source["row"]))
            return [
                actor_id for actor_id in living_allies
                if isinstance(_character_for_actor(battle, actor_id), dict)
                and abs(
                    COMBAT_ROWS.index(str(_character_for_actor(battle, actor_id)["row"]))
                    - source_index
                ) <= 1
            ]
        return living_allies
    if target_kind not in {"enemy", "contextual"}:
        return []
    enemy_formations = battle.get("enemy_formations", {})
    if pattern == "frontmost_enemy":
        for row in COMBAT_ROWS:
            row_targets = [
                str(enemy_id) for enemy_id in enemy_formations.get(row, ())
                if str(enemy_id) in living_enemies
            ]
            if row_targets:
                return row_targets
        return []
    if pattern == "front_two_enemy_rows":
        return [
            str(enemy_id) for row in COMBAT_ROWS[:2]
            for enemy_id in enemy_formations.get(row, ())
            if str(enemy_id) in living_enemies
        ]
    return [
        str(enemy_id) for row in COMBAT_ROWS
        for enemy_id in enemy_formations.get(row, ())
        if str(enemy_id) in living_enemies
    ]


def _effect_power(character: Mapping[str, Any], effect_id: str) -> tuple[int, str]:
    if effect_id == "deal_physical":
        return int(character.get("physical_power", 0)), "physical"
    if effect_id == "deal_technique":
        return int(character.get("technique_power", 0)), "technique"
    if effect_id in {"reveal_pattern", "apply_disruption"}:
        return int(character.get("cognitive_power", 0)), "cognitive"
    if effect_id == "specialization_effect":
        options = {
            "physical": int(character.get("physical_power", 0)),
            "technique": int(character.get("technique_power", 0)),
            "cognitive": int(character.get("cognitive_power", 0)),
        }
        damage_kind = max(options, key=lambda key: (options[key], key))
        return options[damage_kind], damage_kind
    return int(character.get("support_power", 0)), "support"


def resolve_combat_effects(
    battle: Dict[str, Any],
    source_actor_id: str,
    blueprint: Mapping[str, Any],
    target_id: str,
) -> list[Dict[str, Any]]:
    """First deterministic effect pipeline shared by cards and base commands."""
    source = _character_for_actor(battle, source_actor_id)
    if not isinstance(source, dict):
        raise ValueError("combat effect source is not deployed")
    results: list[Dict[str, Any]] = []
    base_power = int(blueprint.get("base_power", 0))
    for effect_id in map(str, blueprint.get("effect_ids", ())):
        scaling_power, power_kind = _effect_power(source, effect_id)
        amount = max(1, base_power + round(scaling_power * 0.6))
        if effect_id in {
            "deal_physical", "deal_technique", "reveal_pattern",
            "apply_disruption", "specialization_effect",
        }:
            enemy = battle["enemy_units"][target_id]
            mitigation = int(
                enemy["defense"] if power_kind in {"physical", "technique"}
                else enemy["resistance"]
            )
            amount = max(1, amount - mitigation)
            weakness = power_kind in enemy.get("weaknesses", ())
            if weakness:
                amount = max(1, round(amount * 1.5))
            before = int(battle["enemy_health"][target_id])
            after = max(0, before - amount)
            battle["enemy_health"][target_id] = after
            if effect_id == "reveal_pattern":
                for weakness_id in enemy.get("weaknesses", ()):
                    known_id = f"{target_id}:{weakness_id}"
                    if known_id not in battle["known_weaknesses"]:
                        battle["known_weaknesses"].append(known_id)
            if effect_id == "apply_disruption" and "disrupted" not in enemy["statuses"]:
                enemy["statuses"].append("disrupted")
            results.append({
                "effect_id": effect_id, "target_id": target_id,
                "amount": amount, "before": before, "after": after,
                "power_kind": power_kind, "weakness": weakness,
            })
            continue
        if effect_id == "grant_guard":
            amount += round(int(source.get("support_power", 0)) * 0.2)
            before = int(battle["barriers"].get(target_id, 0))
            battle["barriers"][target_id] = before + amount
            results.append({
                "effect_id": effect_id, "target_id": target_id,
                "amount": amount, "before": before, "after": before + amount,
            })
            continue
        if effect_id in {"restore_focus", "restore_health"}:
            amount += round(int(source.get("support_power", 0)) * 0.2)
            ledger_name = "focus" if effect_id == "restore_focus" else "health"
            maximum_name = "max_focus" if effect_id == "restore_focus" else "max_health"
            target = _character_for_actor(battle, target_id)
            if not isinstance(target, dict):
                raise ValueError("combat recovery target is invalid")
            before = int(battle[ledger_name].get(target_id, 0))
            after = min(int(target[maximum_name]), before + amount)
            battle[ledger_name][target_id] = after
            results.append({
                "effect_id": effect_id, "target_id": target_id,
                "amount": after - before, "before": before, "after": after,
            })
            continue
        raise ValueError(f"unsupported combat effect: {effect_id}")
    return results


def _finish_victory(context, battle: Dict[str, Any]) -> bool:
    if any(int(value) > 0 for value in battle.get("enemy_health", {}).values()):
        return False
    battle["phase"] = "resolved"
    battle["result"] = "victory"
    battle["revision"] = int(battle["revision"]) + 1
    mapping = context.state.metadata["campus_combat"]["active_battle_by_actor"]
    for actor_id in battle["participant_ids"]:
        if mapping.get(actor_id) == battle["battle_id"]:
            del mapping[actor_id]
    leader_id = next(
        (
            str(actor_id) for actor_id in battle["participant_ids"]
            if context.state.population.get(str(actor_id), {}).get("is_player")
        ),
        str(battle["participant_ids"][0]),
    )
    task_completed = complete_assigned_task(
        context, leader_id, {"task_id": battle["situation_id"]}
    )
    context.emit(
        "COMBAT_VICTORY",
        "夜相异常失去行动能力，行动小队完成了现场处置。",
        actor_ids=battle["participant_ids"], scene_id=battle["scene_id"],
        payload={
            "battle_id": battle["battle_id"], "task_id": battle["situation_id"],
            "task_completed": task_completed,
        },
        visibility="private", severity=4,
        knowledge_tags=["combat", "victory", "night", "task"],
    )
    return True


def _persist_recovery_effects(context, effects):
    for effect in effects:
        if effect["effect_id"] in {"restore_health", "restore_focus"}:
            meter = "health" if effect["effect_id"] == "restore_health" else "focus"
            change_vital(context.state, effect["target_id"], meter, int(effect["amount"]))


def play_combat_card(
    context,
    battle: Dict[str, Any],
    card_instance_id: str,
    target_ids: Iterable[str],
) -> Dict[str, Any]:
    if battle.get("phase") != "player_turn":
        raise ValueError("wrong_battle_phase")
    instance = battle.get("card_instances", {}).get(card_instance_id)
    if not isinstance(instance, dict) or card_instance_id not in battle.get("shared_hand_ids", ()):
        raise ValueError("card_not_in_hand")
    owner_id = str(instance["owner_actor_id"])
    owner = _character_for_actor(battle, owner_id)
    if not isinstance(owner, dict) or owner.get("deployment_state") != "deployed":
        raise ValueError("card_owner_unavailable")
    target_list = list(dict.fromkeys(map(str, target_ids)))
    legal = legal_combat_targets(battle, owner_id, instance)
    if len(target_list) != 1 or target_list[0] not in legal:
        raise ValueError("invalid_combat_target")
    team_id = str(owner["team_id"])
    cost = int(instance["command_cost"])
    available = int(battle["command_points"].get(team_id, 0))
    if available < cost:
        raise ValueError("insufficient_command_points")
    battle["command_points"][team_id] = available - cost
    battle["shared_hand_ids"].remove(card_instance_id)
    battle["discard_piles"][owner_id].append(card_instance_id)
    instance["zone"] = "discard"
    effects = resolve_combat_effects(battle, owner_id, instance, target_list[0])
    _persist_recovery_effects(context, effects)
    battle["revision"] = int(battle["revision"]) + 1
    resolved = not any(int(value) > 0 for value in battle.get("enemy_health", {}).values())
    context.emit(
        "COMBAT_CARD_PLAYED",
        f"{owner.get('display_name', owner_id)}使用了{instance.get('display_name', '指令牌')}。",
        actor_ids=[owner_id], scene_id=battle["scene_id"],
        payload={
            "battle_id": battle["battle_id"], "card_instance_id": card_instance_id,
            "target_ids": target_list, "command_cost": cost,
            "effects": deepcopy(effects), "battle_resolved": resolved,
        },
        visibility="private", severity=3,
        knowledge_tags=["combat", "cards", "effect"],
    )
    if resolved:
        _finish_victory(context, battle)
    return {"effects": effects, "battle_resolved": resolved}


def use_combat_base_command(
    context,
    battle: Dict[str, Any],
    source_actor_id: str,
    target_ids: Iterable[str],
    round_policy: CombatRoundPolicy,
) -> Dict[str, Any]:
    if battle.get("phase") != "player_turn":
        raise ValueError("wrong_battle_phase")
    source = _character_for_actor(battle, source_actor_id)
    if not isinstance(source, dict) or source.get("deployment_state") != "deployed":
        raise ValueError("base_command_actor_unavailable")
    if source_actor_id in battle["base_command_used_actor_ids"]:
        raise ValueError("base_command_already_used")
    command_id = str(source["base_command_id"])
    blueprint = round_policy.base_command_blueprints[command_id]
    target_list = list(dict.fromkeys(map(str, target_ids)))
    legal = legal_combat_targets(battle, source_actor_id, blueprint)
    if len(target_list) != 1 or target_list[0] not in legal:
        raise ValueError("invalid_combat_target")
    team_id = str(source["team_id"])
    cost = int(blueprint["command_cost"])
    available = int(battle["command_points"].get(team_id, 0))
    if available < cost:
        raise ValueError("insufficient_command_points")
    battle["command_points"][team_id] = available - cost
    battle["base_command_used_actor_ids"].append(source_actor_id)
    effects = resolve_combat_effects(battle, source_actor_id, blueprint, target_list[0])
    _persist_recovery_effects(context, effects)
    battle["revision"] = int(battle["revision"]) + 1
    resolved = not any(int(value) > 0 for value in battle.get("enemy_health", {}).values())
    context.emit(
        "COMBAT_BASE_COMMAND_USED",
        f"{source.get('display_name', source_actor_id)}执行了{blueprint.get('name', command_id)}。",
        actor_ids=[source_actor_id], scene_id=battle["scene_id"],
        payload={
            "battle_id": battle["battle_id"], "base_command_id": command_id,
            "target_ids": target_list, "command_cost": cost,
            "effects": deepcopy(effects), "battle_resolved": resolved,
        },
        visibility="private", severity=3,
        knowledge_tags=["combat", "base_command", "effect"],
    )
    if resolved:
        _finish_victory(context, battle)
    return {"effects": effects, "battle_resolved": resolved}


def configured_actor_deck(
    state: WorldState,
    battle: Mapping[str, Any],
    actor_id: str,
    round_policy: CombatRoundPolicy,
) -> list[str]:
    """Build the reproducible eight-card list; duplicate blueprints are legal."""
    blueprints = _combat_card_blueprints(state, round_policy)
    character = next(
        (
            value for value in battle.get("character_cards", {}).values()
            if isinstance(value, dict) and value.get("actor_id") == actor_id
        ),
        None,
    )
    if not isinstance(character, dict) or character.get("deployment_state") != "deployed":
        raise ValueError("only deployed actors receive a combat deck")
    owned = [
        str(card_id) for card_id in character.get("command_card_ids", ())
        if str(card_id) in blueprints
    ]
    repeatable = owned or [round_policy.fallback_card_id]
    selected = list(round_policy.required_generic_card_ids)
    selected.extend(owned)
    cursor = 0
    while len(selected) < round_policy.deck_size_per_actor:
        selected.append(repeatable[cursor % len(repeatable)])
        cursor += 1
    selected = selected[:round_policy.deck_size_per_actor]
    if any(card_id not in blueprints for card_id in selected):
        raise ValueError(f"combat deck for {actor_id} references an unknown card")
    card_types = {str(blueprints[card_id].get("card_type", "")) for card_id in selected}
    if "defense" not in card_types:
        raise ValueError(f"combat deck for {actor_id} requires a defense card")
    if not card_types.intersection({"defense", "support", "control", "knowledge"}):
        raise ValueError(f"combat deck for {actor_id} requires a non-damage card")
    return selected


def _shuffle_draw_pile(context, battle: Dict[str, Any], actor_id: str, *, initial: bool) -> None:
    pile = battle["draw_piles"][actor_id]
    if initial:
        stream_name = f"combat.deck.{battle['battle_id']}.{actor_id}.initial"
    else:
        count = int(battle["reshuffle_counts"].get(actor_id, 0)) + 1
        battle["reshuffle_counts"][actor_id] = count
        stream_name = f"combat.deck.{battle['battle_id']}.{actor_id}.reshuffle.{count}"
    context.rng.stream(stream_name).shuffle(pile)


def _draw_one_card(context, battle: Dict[str, Any], actor_id: str) -> str | None:
    draw_pile = battle["draw_piles"][actor_id]
    discard_pile = battle["discard_piles"][actor_id]
    if not draw_pile and discard_pile:
        draw_pile.extend(discard_pile)
        discard_pile.clear()
        for instance_id in draw_pile:
            battle["card_instances"][instance_id]["zone"] = "draw"
        _shuffle_draw_pile(context, battle, actor_id, initial=False)
    if not draw_pile:
        return None
    instance_id = draw_pile.pop(0)
    battle["card_instances"][instance_id]["zone"] = "hand"
    battle["shared_hand_ids"].append(instance_id)
    return instance_id


def _draw_round_hand(
    context,
    battle: Dict[str, Any],
    round_policy: CombatRoundPolicy,
) -> list[str]:
    drawn: list[str] = []
    deployed_actor_ids = {
        str(card.get("actor_id"))
        for card in battle["character_cards"].values()
        if isinstance(card, dict) and card.get("deployment_state") == "deployed"
    }
    for actor_id in battle["participant_ids"]:
        if actor_id not in deployed_actor_ids:
            continue
        for _ in range(round_policy.cards_drawn_per_actor):
            instance_id = _draw_one_card(context, battle, actor_id)
            if instance_id is not None:
                drawn.append(instance_id)
    return drawn


def start_card_combat(
    context,
    battle: Dict[str, Any],
    round_policy: CombatRoundPolicy,
) -> Dict[str, Any]:
    if battle.get("phase") != "ready":
        raise ValueError("card combat can only start from a locked formation")
    state = context.state
    blueprints = _combat_card_blueprints(state, round_policy)
    battle["actor_decks"] = {}
    battle["draw_piles"] = {}
    battle["discard_piles"] = {}
    battle["exhaust_piles"] = {}
    battle["reshuffle_counts"] = {}
    battle["card_instances"] = {}
    battle["shared_hand_ids"] = []
    battle["base_command_used_actor_ids"] = []
    for actor_id in battle["participant_ids"]:
        blueprint_ids = configured_actor_deck(
            state, battle, actor_id, round_policy
        )
        battle["actor_decks"][actor_id] = list(blueprint_ids)
        battle["draw_piles"][actor_id] = []
        battle["discard_piles"][actor_id] = []
        battle["exhaust_piles"][actor_id] = []
        battle["reshuffle_counts"][actor_id] = 0
        for slot, blueprint_id in enumerate(blueprint_ids, start=1):
            blueprint = blueprints[blueprint_id]
            instance_id = f"{battle['battle_id']}:card:{actor_id}:{slot:02d}"
            battle["card_instances"][instance_id] = {
                "card_instance_id": instance_id,
                "card_id": blueprint_id,
                "display_name": str(blueprint.get("name", blueprint_id)),
                "source_ability_id": str(blueprint.get("source_ability_id", "")),
                "owner_actor_id": actor_id,
                "actor_bound": True,
                "card_type": str(blueprint["card_type"]),
                "command_cost": int(blueprint["command_cost"]),
                "target": str(blueprint["target"]),
                "range_pattern": str(blueprint["range_pattern"]),
                "base_power": int(blueprint["base_power"]),
                "effect_ids": list(map(str, blueprint["effect_ids"])),
                "zone": "draw",
                "retained": False,
            }
            battle["draw_piles"][actor_id].append(instance_id)
        _shuffle_draw_pile(context, battle, actor_id, initial=True)
    battle["round"] = 1
    battle["command_point_cap"] = round_policy.initial_command_points
    for team_id in battle["team_ids"]:
        battle["command_points"][team_id] = round_policy.initial_command_points
    battle["phase"] = "player_turn"
    drawn = _draw_round_hand(context, battle, round_policy)
    battle["revision"] = int(battle["revision"]) + 1
    context.emit(
        "COMBAT_ROUND_STARTED",
        "阵型稳定下来，行动小队抽取了第一轮共享战术手牌。",
        actor_ids=battle["participant_ids"], scene_id=battle["scene_id"],
        payload={
            "battle_id": battle["battle_id"], "round": 1,
            "command_point_cap": battle["command_point_cap"],
            "drawn_card_instance_ids": list(drawn), "runtime_started": True,
        },
        visibility="private", severity=4,
        knowledge_tags=["combat", "cards", "round", "formation"],
    )
    return {"drawn_card_instance_ids": drawn}


def end_combat_round(
    context,
    battle: Dict[str, Any],
    round_policy: CombatRoundPolicy,
) -> Dict[str, Any]:
    if battle.get("phase") != "player_turn":
        raise ValueError("only the player turn can end the combat round")
    retained_ids: list[str] = []
    discarded_ids: list[str] = []
    for instance_id in list(battle["shared_hand_ids"]):
        instance = battle["card_instances"][instance_id]
        if bool(instance.get("retained", False)):
            retained_ids.append(instance_id)
            continue
        actor_id = str(instance["owner_actor_id"])
        battle["shared_hand_ids"].remove(instance_id)
        battle["discard_piles"][actor_id].append(instance_id)
        instance["zone"] = "discard"
        discarded_ids.append(instance_id)
    battle["round"] = int(battle["round"]) + 1
    battle["command_point_cap"] = min(
        round_policy.maximum_command_points,
        round_policy.initial_command_points
        + (int(battle["round"]) - 1) * round_policy.command_point_growth_per_round,
    )
    for team_id in battle["team_ids"]:
        battle["command_points"][team_id] = int(battle["command_point_cap"])
    battle["base_command_used_actor_ids"] = []
    drawn = _draw_round_hand(context, battle, round_policy)
    battle["revision"] = int(battle["revision"]) + 1
    context.emit(
        "COMBAT_ROUND_STARTED",
        f"行动小队进入第 {battle['round']} 轮并补满共享指令点。",
        actor_ids=battle["participant_ids"], scene_id=battle["scene_id"],
        payload={
            "battle_id": battle["battle_id"], "round": battle["round"],
            "command_point_cap": battle["command_point_cap"],
            "discarded_card_instance_ids": discarded_ids,
            "retained_card_instance_ids": retained_ids,
            "drawn_card_instance_ids": drawn,
            "enemy_resolution_status": "pending_effect_pipeline",
        },
        visibility="private", severity=3,
        knowledge_tags=["combat", "cards", "round"],
    )
    return {
        "discarded_card_instance_ids": discarded_ids,
        "retained_card_instance_ids": retained_ids,
        "drawn_card_instance_ids": drawn,
    }


def incapacitate_character(context, battle: Dict[str, Any], card_id: str) -> Dict[str, Any]:
    """Shared step-16 hook: remove a downed actor and invalidate its pending cards."""
    card = battle.get("character_cards", {}).get(card_id)
    if not isinstance(card, dict):
        raise KeyError(f"unknown combat character card: {card_id}")
    if card.get("deployment_state") != "deployed":
        raise ValueError("only a deployed character can become incapacitated")
    actor_id = str(card["actor_id"])
    _remove_from_formation(battle, card_id)
    card["deployment_state"] = "incapacitated"
    card["row"] = None
    if "vitals" in context.state.population[actor_id]:
        change_vital(context.state, actor_id, "health", -context.state.population[actor_id]["vitals"]["health"])
    battle["health"][actor_id] = 0
    statuses = battle["statuses"].setdefault(actor_id, [])
    if "incapacitated" not in statuses:
        statuses.append("incapacitated")
    invalidated: list[str] = []
    for instance_id, instance in battle.get("card_instances", {}).items():
        if not isinstance(instance, dict) or instance.get("owner_actor_id") != actor_id:
            continue
        if instance_id in battle.get("shared_hand_ids", ()):
            battle["shared_hand_ids"].remove(instance_id)
        for zone_name in ("draw_piles", "discard_piles"):
            pile = battle.get(zone_name, {}).get(actor_id, [])
            if instance_id in pile:
                pile.remove(instance_id)
        instance["zone"] = "exhaust"
        pile = battle["exhaust_piles"].setdefault(actor_id, [])
        if instance_id not in pile:
            pile.append(instance_id)
        invalidated.append(instance_id)
    consequences = battle.setdefault("consequences", {})
    downed = consequences.setdefault("incapacitated_actor_ids", [])
    if actor_id not in downed:
        downed.append(actor_id)
    battle["revision"] = int(battle["revision"]) + 1
    context.emit(
        "COMBAT_CHARACTER_INCAPACITATED",
        f"{card.get('display_name', actor_id)}倒下并退出了当前阵型。",
        actor_ids=[actor_id], scene_id=battle.get("scene_id"),
        payload={
            "battle_id": battle["battle_id"], "character_card_instance_id": card_id,
            "invalidated_card_instance_ids": invalidated, "replacement_allowed": False,
        },
        visibility="private", severity=5,
        knowledge_tags=["combat", "injury", "formation"],
    )
    return {"actor_id": actor_id, "invalidated_card_instance_ids": invalidated}


def advance_campus_combat(context) -> Dict[str, int]:
    """Remove unresolved combat safely when daylight or task state invalidates it."""
    state = context.state
    summary = {
        "battle_preparation_interrupted_count": 0,
        "battle_interrupted_count": 0,
    }
    metadata = state.metadata.get("campus_combat", {})
    mapping = metadata.get("active_battle_by_actor", {})
    if not isinstance(mapping, dict):
        return summary
    for battle_id, battle in list(state.battles.items()):
        if not isinstance(battle, dict) or battle.get("phase") == "resolved":
            continue
        task = state.tasks.get(str(battle.get("situation_id", "")), {})
        leader_id = next(
            (
                actor_id for actor_id in battle.get("participant_ids", ())
                if state.population.get(actor_id, {}).get("is_player")
            ),
            "player",
        )
        invalid_task = (
            not isinstance(task, dict)
            or task.get("assignee_id") != leader_id
            or task.get("state") not in {"locked", "in_progress"}
        )
        daylight = state.clock.phase in {"morning", "afternoon"}
        if not daylight and not invalid_task:
            continue
        actor_ids = [
            actor_id for actor_id, mapped_id in list(mapping.items())
            if mapped_id == battle_id
        ]
        for actor_id in actor_ids:
            del mapping[actor_id]
        del state.battles[battle_id]
        preparation = battle.get("phase") in {"setup", "ready"}
        event_type = "BATTLE_PREPARATION_INTERRUPTED" if preparation else "BATTLE_INTERRUPTED"
        context.emit(
            event_type,
            "时段或任务状态变化中止了尚未结算的战斗准备。" if preparation
            else "晨光或任务状态变化中止了尚未完成的卡牌战斗。",
            actor_ids=actor_ids, scene_id=battle.get("scene_id"),
            payload={
                "battle_id": battle_id,
                "reason": "daylight" if daylight else "task_invalidated",
            },
            visibility="private", severity=3,
            knowledge_tags=["combat", "party", "formation", "night"],
        )
        summary[
            "battle_preparation_interrupted_count" if preparation else "battle_interrupted_count"
        ] += 1
    return summary


def make_campus_combat_handler(
    policy: CombatDeploymentPolicy,
    round_policy: CombatRoundPolicy,
    graph: CampusLocationGraph,
):
    def handle(context, command) -> TransactionOutcome:
        state = context.state
        if command.actor_id not in state.population:
            return TransactionOutcome(False, False, "unknown_actor", "行动者不存在。")
        if command.action_id == "START_BATTLE_PREPARATION":
            task_id = str(command.parameters.get("task_id", ""))
            assessment = combat_preparation_assessment(
                state, command.actor_id, policy, task_id=task_id
            )
            if not assessment["allowed"]:
                messages = {
                    "battle_already_active": "已经存在尚未结束的战斗准备。",
                    "invalid_phase": "只有晚间或深夜能准备夜相战斗。",
                    "night_layer_required": "需要先进入夜相。",
                    "party_leader_required": "只有行动小队队长可以建立阵型。",
                    "owned_night_task_required": "需要先在里世界论坛锁定一个夜相任务。",
                    "task_location_required": "需要先抵达任务所在校园区域。",
                }
                return TransactionOutcome(
                    False, False, str(assessment["reason"]),
                    messages.get(str(assessment["reason"]), "当前无法建立战斗准备。"),
                    payload={key: value for key, value in assessment.items() if key != "task"},
                )
            battle = _new_battle(state, command.actor_id, assessment["task"], policy, graph)
            state.battles[battle["battle_id"]] = battle
            for actor_id in battle["participant_ids"]:
                state.metadata["campus_combat"]["active_battle_by_actor"][actor_id] = battle["battle_id"]
            context.emit(
                "BATTLE_PREPARATION_STARTED",
                "行动小队开始为夜相任务配置人物牌与三排阵型。",
                actor_ids=battle["participant_ids"], scene_id=battle["scene_id"],
                payload={
                    "battle_id": battle["battle_id"], "task_id": battle["situation_id"],
                    "candidate_actor_ids": battle["participant_ids"], "action_class": "free",
                },
                visibility="private", severity=4,
                knowledge_tags=["combat", "party", "formation", "night"],
            )
            return TransactionOutcome(
                True, True, "success", "战斗准备已建立，请部署人物牌。",
                commit=True, payload={"battle_id": battle["battle_id"], "action_class": "free"},
            )

        battle, error = _battle_from_command(state, command.actor_id, command.parameters)
        if battle is None:
            messages = {
                "unknown_battle": "没有找到当前战斗准备。",
                "battle_revision_conflict": "阵型已被更新，请刷新后重试。",
                "battle_control_denied": "你不能控制这个战斗准备。",
            }
            return TransactionOutcome(False, False, error, messages.get(error, "战斗准备无效。"))
        if command.action_id == "CANCEL_BATTLE_PREPARATION":
            if battle["phase"] not in {"setup", "ready"}:
                return TransactionOutcome(False, False, "battle_already_running", "战斗开始后不能取消准备。")
            battle_id = str(battle["battle_id"])
            actor_ids = list(battle["participant_ids"])
            del state.battles[battle_id]
            mapping = state.metadata["campus_combat"]["active_battle_by_actor"]
            for actor_id in actor_ids:
                if mapping.get(actor_id) == battle_id:
                    del mapping[actor_id]
            context.emit(
                "BATTLE_PREPARATION_CANCELLED", "行动小队取消了本次阵型准备。",
                actor_ids=actor_ids, scene_id=battle.get("scene_id"),
                payload={"battle_id": battle_id, "action_class": "free"},
                visibility="private", severity=2,
                knowledge_tags=["combat", "party", "formation"],
            )
            return TransactionOutcome(True, True, "success", "已取消战斗准备。", commit=True)

        if command.action_id == "START_CARD_COMBAT":
            if battle["phase"] != "ready":
                return TransactionOutcome(
                    False, False, "formation_not_ready", "需要先部署人物牌并锁定阵型。"
                )
            runtime = start_card_combat(context, battle, round_policy)
            return TransactionOutcome(
                True, True, "success", "卡牌战斗已开始，第一轮共享手牌已抽取。",
                commit=True,
                payload={
                    "battle_id": battle["battle_id"],
                    "battle_revision": battle["revision"],
                    "round": battle["round"],
                    **runtime,
                },
            )

        if command.action_id == "END_COMBAT_ROUND":
            if battle["phase"] != "player_turn":
                return TransactionOutcome(
                    False, False, "wrong_battle_phase", "当前不能结束玩家回合。"
                )
            runtime = end_combat_round(context, battle, round_policy)
            return TransactionOutcome(
                True, True, "success", f"已进入第 {battle['round']} 轮。",
                commit=True,
                payload={
                    "battle_id": battle["battle_id"],
                    "battle_revision": battle["revision"],
                    "round": battle["round"],
                    **runtime,
                },
            )

        if command.action_id in {"PLAY_COMBAT_CARD", "USE_COMBAT_BASE_COMMAND"}:
            try:
                if command.action_id == "PLAY_COMBAT_CARD":
                    runtime = play_combat_card(
                        context,
                        battle,
                        str(command.parameters.get("card_instance_id", "")),
                        command.parameters.get("target_ids", ()),
                    )
                    success_message = (
                        "指令牌已结算，战斗胜利。" if runtime["battle_resolved"]
                        else "指令牌已结算。"
                    )
                else:
                    runtime = use_combat_base_command(
                        context,
                        battle,
                        str(command.parameters.get("source_actor_id", command.actor_id)),
                        command.parameters.get("target_ids", ()),
                        round_policy,
                    )
                    success_message = (
                        "基础指令已结算，战斗胜利。" if runtime["battle_resolved"]
                        else "基础指令已结算。"
                    )
            except ValueError as exc:
                error_code = str(exc)
                messages = {
                    "wrong_battle_phase": "当前不是玩家行动阶段。",
                    "card_not_in_hand": "这张牌不在当前共享手牌中。",
                    "card_owner_unavailable": "出牌角色已经无法行动。",
                    "base_command_actor_unavailable": "该角色当前无法执行基础指令。",
                    "base_command_already_used": "该角色本轮已经执行过基础指令。",
                    "invalid_combat_target": "目标不符合这项行动的排位或阵营限制。",
                    "insufficient_command_points": "共享指令点不足。",
                }
                return TransactionOutcome(
                    False, False, error_code,
                    messages.get(error_code, "战斗效果无法结算。"),
                )
            return TransactionOutcome(
                True, True, "success", success_message, commit=True,
                payload={
                    "battle_id": battle["battle_id"],
                    "battle_revision": battle["revision"],
                    **runtime,
                },
            )

        card, card_id = _card_from_command(battle, command.parameters)
        if command.action_id in {
            "DEPLOY_COMBAT_CHARACTER", "WITHDRAW_COMBAT_CHARACTER", "REPOSITION_COMBAT_CHARACTER",
        } and card is None:
            return TransactionOutcome(False, False, "unknown_character_card", "没有找到这张人物牌。")

        if command.action_id == "DEPLOY_COMBAT_CHARACTER":
            if battle["phase"] != "setup":
                return TransactionOutcome(False, False, "deployment_locked", "阵型已经锁定。")
            if card["deployment_state"] != "reserve":
                return TransactionOutcome(False, False, "character_not_in_reserve", "该人物当前不在候选区。")
            destination_row = str(command.parameters.get("destination_row", ""))
            if destination_row not in card["allowed_rows"]:
                return TransactionOutcome(False, False, "invalid_destination_row", "人物牌不能部署到该排。")
            row = battle["formations"][card["team_id"]][destination_row]
            if len(row) >= policy.row_capacity:
                return TransactionOutcome(False, False, "row_capacity_reached", "这一排最多部署两名队员。")
            readiness = combat_readiness_assessment(
                state, command.actor_id, str(card["actor_id"]), policy,
                situation_id=str(battle.get("situation_id", "")), graph=graph,
            )
            if not readiness.get("eligible"):
                return TransactionOutcome(
                    False, False, str(readiness["reason"]), "该队员当前无法参与本次行动。",
                    payload=readiness,
                )
            assembly_error = _assemble_actor(
                context, graph, str(card["actor_id"]), command.actor_id
            )
            if assembly_error is not None:
                return assembly_error
            card["deployment_state"] = "deployed"
            card["row"] = destination_row
            battle["reserve_character_card_ids"].remove(card_id)
            row.append(card_id)
            battle["pollution"][card["actor_id"]] = int(
                state.situations["night_world"]["actor_states"][card["actor_id"]].get("pollution", 0)
            )
            battle["revision"] = int(battle["revision"]) + 1
            context.emit(
                "COMBAT_CHARACTER_DEPLOYED",
                f"{card['display_name']}被部署到{destination_row}排。",
                actor_ids=[str(card["actor_id"]), command.actor_id], scene_id=battle["scene_id"],
                payload={
                    "battle_id": battle["battle_id"], "character_card_instance_id": card_id,
                    "row": destination_row, "deployment_cost": 0, "action_class": "free",
                },
                visibility="private", severity=3,
                knowledge_tags=["combat", "party", "formation"],
            )
            return TransactionOutcome(
                True, True, "success", "人物牌部署完成。", commit=True,
                payload={"battle_id": battle["battle_id"], "battle_revision": battle["revision"]},
            )

        if command.action_id == "WITHDRAW_COMBAT_CHARACTER":
            if battle["phase"] != "setup":
                return TransactionOutcome(False, False, "deployment_locked", "阵型已经锁定。")
            if card["deployment_state"] != "deployed":
                return TransactionOutcome(False, False, "character_not_deployed", "该人物尚未部署。")
            _remove_from_formation(battle, card_id)
            card["deployment_state"] = "reserve"
            card["row"] = None
            battle["reserve_character_card_ids"].append(card_id)
            battle["revision"] = int(battle["revision"]) + 1
            context.emit(
                "COMBAT_CHARACTER_WITHDRAWN", f"{card['display_name']}返回了候选区。",
                actor_ids=[str(card["actor_id"]), command.actor_id], scene_id=battle["scene_id"],
                payload={"battle_id": battle["battle_id"], "character_card_instance_id": card_id},
                visibility="private", severity=2,
                knowledge_tags=["combat", "party", "formation"],
            )
            return TransactionOutcome(True, True, "success", "人物牌已撤回候选区。", commit=True)

        if command.action_id == "REPOSITION_COMBAT_CHARACTER":
            if battle["phase"] == "ready":
                return TransactionOutcome(False, False, "deployment_locked", "阵型已锁定；取消准备后才能重排。")
            if battle["phase"] not in {"setup", "player_turn"}:
                return TransactionOutcome(False, False, "wrong_battle_phase", "当前阶段不能换位。")
            if card["deployment_state"] != "deployed":
                return TransactionOutcome(False, False, "character_not_deployed", "只有场上的人物牌可以换位。")
            destination_row = str(command.parameters.get("destination_row", ""))
            if destination_row not in card["allowed_rows"]:
                return TransactionOutcome(False, False, "invalid_destination_row", "人物牌不能移动到该排。")
            if card["row"] == destination_row:
                return TransactionOutcome(False, True, "already_in_row", "人物牌已经位于该排。")
            destination = battle["formations"][card["team_id"]][destination_row]
            if len(destination) >= policy.row_capacity:
                return TransactionOutcome(False, False, "row_capacity_reached", "这一排最多部署两名队员。")
            cost = 0
            if battle["phase"] == "player_turn":
                cost = policy.reposition_command_cost
                available = int(battle["command_points"].get(card["team_id"], 0))
                if available < cost:
                    return TransactionOutcome(False, False, "insufficient_command_points", "共享指令点不足。")
                battle["command_points"][card["team_id"]] = available - cost
            old_row = str(card["row"])
            _remove_from_formation(battle, card_id)
            destination.append(card_id)
            card["row"] = destination_row
            battle["revision"] = int(battle["revision"]) + 1
            context.emit(
                "COMBAT_CHARACTER_REPOSITIONED",
                f"{card['display_name']}从{old_row}排移动到{destination_row}排。",
                actor_ids=[str(card["actor_id"]), command.actor_id], scene_id=battle["scene_id"],
                payload={
                    "battle_id": battle["battle_id"], "character_card_instance_id": card_id,
                    "from_row": old_row, "to_row": destination_row,
                    "command_cost": cost, "action_class": "free" if cost == 0 else "combat",
                },
                visibility="private", severity=2,
                knowledge_tags=["combat", "party", "formation"],
            )
            return TransactionOutcome(True, True, "success", "人物牌换位完成。", commit=True)

        if command.action_id == "CONFIRM_BATTLE_DEPLOYMENT":
            if battle["phase"] != "setup":
                return TransactionOutcome(False, False, "deployment_locked", "阵型已经锁定。")
            player_card = next(
                (value for value in battle["character_cards"].values() if value.get("actor_id") == "player"),
                None,
            )
            if not isinstance(player_card, dict) or player_card.get("deployment_state") != "deployed":
                return TransactionOutcome(False, False, "player_must_be_deployed", "玩家人物牌必须上场。")
            deployed_ids = [
                card_id for card_id, value in battle["character_cards"].items()
                if value.get("deployment_state") == "deployed"
            ]
            for reserve_id in list(battle["reserve_character_card_ids"]):
                battle["character_cards"][reserve_id]["deployment_state"] = "withdrawn"
            battle["reserve_character_card_ids"] = []
            deployed_actor_ids = [battle["character_cards"][card_id]["actor_id"] for card_id in deployed_ids]
            battle["participant_ids"] = deployed_actor_ids
            team_id = str(player_card["team_id"])
            battle["team_ids"][team_id] = deployed_actor_ids
            battle["phase"] = "ready"
            battle["revision"] = int(battle["revision"]) + 1
            mapping = state.metadata["campus_combat"]["active_battle_by_actor"]
            for actor_id in list(mapping):
                if mapping[actor_id] == battle["battle_id"] and actor_id not in deployed_actor_ids:
                    del mapping[actor_id]
            context.emit(
                "BATTLE_DEPLOYMENT_CONFIRMED", "行动小队锁定了前中后三排阵型。",
                actor_ids=deployed_actor_ids, scene_id=battle["scene_id"],
                payload={
                    "battle_id": battle["battle_id"],
                    "formation": deepcopy(battle["formations"][team_id]),
                    "replacement_allowed_after_start": False,
                    "runtime_status": "ready_to_start_card_rounds",
                },
                visibility="private", severity=4,
                knowledge_tags=["combat", "party", "formation", "commitment"],
            )
            return TransactionOutcome(
                True, True, "success", "阵型已锁定，可以开始卡牌战斗。",
                commit=True, payload={"battle_id": battle["battle_id"], "battle_revision": battle["revision"]},
            )
        return TransactionOutcome(False, False, "unknown_combat_action", "未知战斗准备行动。")

    return handle


def campus_combat_view(
    state: WorldState,
    viewer_id: str,
    policy: CombatDeploymentPolicy,
    graph: CampusLocationGraph | None = None,
) -> Dict[str, Any]:
    round_policy = combat_round_policy_from_state(state)
    active = active_battle_for_actor(state, viewer_id)
    tasks = _owned_night_tasks(state, viewer_id)
    actor_region = _actor_region_id(state, viewer_id)
    task_views = [
        {
            "task_id": str(task.get("task_id", "")),
            "title": str(task.get("title", "夜相任务")),
            "execution_region_id": str(task.get("execution_region_id", "")),
            "at_scene": task.get("execution_region_id") == actor_region,
        }
        for task in tasks
    ]
    general = combat_preparation_assessment(state, viewer_id, policy)
    party = party_for_actor(state, viewer_id)
    candidate_views = []
    if isinstance(party, dict):
        situation_id = str(active.get("situation_id", "")) if isinstance(active, dict) else ""
        for actor_id in party.get("member_ids", ()):
            assessment = combat_readiness_assessment(
                state, viewer_id, actor_id, policy,
                situation_id=situation_id, graph=graph,
            )
            candidate_views.append({
                "actor_id": actor_id,
                "display_name": state.population.get(actor_id, {}).get("display_name", actor_id),
                **deepcopy(assessment),
            })
    active_view = deepcopy(active) if isinstance(active, dict) else None
    if isinstance(active_view, dict) and active_view.get("phase") == "player_turn":
        card_options: Dict[str, Dict[str, Any]] = {}
        for instance_id in active_view.get("shared_hand_ids", ()):
            instance = active_view.get("card_instances", {}).get(instance_id, {})
            if not isinstance(instance, dict):
                continue
            owner_id = str(instance.get("owner_actor_id", ""))
            owner = _character_for_actor(active_view, owner_id)
            team_id = str(owner.get("team_id", "")) if isinstance(owner, dict) else ""
            target_ids = legal_combat_targets(active_view, owner_id, instance)
            card_options[str(instance_id)] = {
                "target_ids": target_ids,
                "playable": bool(target_ids) and int(
                    active_view.get("command_points", {}).get(team_id, 0)
                ) >= int(instance.get("command_cost", 0)),
            }
        base_options: Dict[str, Dict[str, Any]] = {}
        for actor_id in active_view.get("participant_ids", ()):
            actor_id = str(actor_id)
            character = _character_for_actor(active_view, actor_id)
            if not isinstance(character, dict) or character.get("deployment_state") != "deployed":
                continue
            command_id = str(character.get("base_command_id", ""))
            blueprint = round_policy.base_command_blueprints.get(command_id, {})
            target_ids = legal_combat_targets(active_view, actor_id, blueprint)
            used = actor_id in active_view.get("base_command_used_actor_ids", ())
            team_id = str(character.get("team_id", ""))
            base_options[actor_id] = {
                "base_command_id": command_id,
                "display_name": str(blueprint.get("name", command_id)),
                "command_cost": int(blueprint.get("command_cost", 0)),
                "target_ids": target_ids,
                "used": used,
                "playable": not used and bool(target_ids) and int(
                    active_view.get("command_points", {}).get(team_id, 0)
                ) >= int(blueprint.get("command_cost", 0)),
            }
        active_view["action_options"] = {
            "cards": card_options,
            "base_commands": base_options,
        }
    return {
        "enabled": True,
        "can_prepare": bool(general.get("allowed", False)),
        "preparation_reason": str(general.get("reason", "unavailable")),
        "owned_night_tasks": task_views,
        "candidate_assessments": candidate_views,
        "rules": {
            "max_friendly_characters": policy.max_friendly_characters,
            "row_capacity": policy.row_capacity,
            "rows": list(policy.allowed_rows),
            "initial_deployment_cost": 0,
            "combat_reposition_cost": policy.reposition_command_cost,
            "replacement_allowed_after_start": False,
            "deck_size_per_actor": round_policy.deck_size_per_actor,
            "cards_drawn_per_actor": round_policy.cards_drawn_per_actor,
            "initial_command_points": round_policy.initial_command_points,
            "maximum_command_points": round_policy.maximum_command_points,
        },
        "active_battle": active_view,
    }


def campus_combat_invariant(state: WorldState) -> Iterable[str]:
    metadata = state.metadata.get("campus_combat")
    if metadata is None:
        return ()
    if not isinstance(metadata, dict) or metadata.get("schema_version") != CAMPUS_COMBAT_SCHEMA_VERSION:
        return ("campus combat metadata is invalid",)
    errors: list[str] = []
    try:
        policy = parse_combat_deployment_policy(metadata.get("policy", {}))
        round_policy = parse_combat_round_policy(metadata.get("round_policy", {}))
    except (TypeError, ValueError) as exc:
        return (f"campus combat policy is invalid: {exc}",)
    sequence = metadata.get("battle_sequence")
    enemy_archetypes = metadata.get("enemy_archetypes")
    if not isinstance(enemy_archetypes, dict) or not enemy_archetypes:
        errors.append("campus combat enemy archetypes are invalid")
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
        errors.append("campus combat battle sequence is invalid")
    mapping = metadata.get("active_battle_by_actor")
    if not isinstance(mapping, dict):
        errors.append("campus combat active battle mapping is invalid")
        mapping = {}
    for actor_id, battle_id in mapping.items():
        if actor_id not in state.population or battle_id not in state.battles:
            errors.append(f"campus combat mapping for {actor_id} is stale")
    for battle_id, battle in state.battles.items():
        if not isinstance(battle, dict) or battle.get("battle_id") != battle_id:
            errors.append(f"battle {battle_id} has an invalid record")
            continue
        if battle.get("phase") not in {"setup", "ready", "player_turn", "enemy_turn", "round_end", "resolved"}:
            errors.append(f"battle {battle_id} has an invalid phase")
        cards = battle.get("character_cards")
        formations = battle.get("formations")
        reserves = battle.get("reserve_character_card_ids")
        participants = battle.get("participant_ids")
        if not isinstance(cards, dict) or not isinstance(formations, dict) or not isinstance(reserves, list):
            errors.append(f"battle {battle_id} deployment ledgers are invalid")
            continue
        actor_ids = [card.get("actor_id") for card in cards.values() if isinstance(card, dict)]
        if len(actor_ids) != len(set(actor_ids)) or any(actor_id not in state.population for actor_id in actor_ids):
            errors.append(f"battle {battle_id} character actors are invalid")
        occupied: list[str] = []
        for team_id, formation in formations.items():
            if not isinstance(formation, dict) or set(formation) != set(COMBAT_ROWS):
                errors.append(f"battle {battle_id} formation {team_id} is invalid")
                continue
            for row in COMBAT_ROWS:
                row_cards = formation[row]
                if not isinstance(row_cards, list) or len(row_cards) > policy.row_capacity:
                    errors.append(f"battle {battle_id} {team_id} {row} exceeds capacity")
                    continue
                occupied.extend(row_cards)
        if len(occupied) != len(set(occupied)) or set(occupied).intersection(reserves):
            errors.append(f"battle {battle_id} has duplicate deployed or reserve cards")
        for card_id, card in cards.items():
            if not isinstance(card, dict) or card.get("character_card_instance_id") != card_id:
                errors.append(f"battle {battle_id} character card {card_id} is invalid")
                continue
            deployed = card_id in occupied
            reserved = card_id in reserves
            if deployed != (card.get("deployment_state") == "deployed"):
                errors.append(f"battle {battle_id} character card {card_id} deployment mismatch")
            if reserved != (card.get("deployment_state") == "reserve"):
                errors.append(f"battle {battle_id} character card {card_id} reserve mismatch")
            if deployed and card.get("row") not in COMBAT_ROWS:
                errors.append(f"battle {battle_id} character card {card_id} lacks a row")
            if not deployed and card.get("row") is not None:
                errors.append(f"battle {battle_id} character card {card_id} kept a stale row")
            if not card.get("command_card_ids"):
                errors.append(f"battle {battle_id} character card {card_id} lacks commands")
            for power_name in (
                "physical_power", "technique_power", "cognitive_power", "support_power",
            ):
                value = card.get(power_name)
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    errors.append(
                        f"battle {battle_id} character card {card_id} has invalid {power_name}"
                    )
        if battle.get("phase") != "setup" and reserves:
            errors.append(f"battle {battle_id} kept reserves after deployment lock")
        if battle.get("phase") == "ready" and not any(
            card.get("actor_id") == "player" and card.get("deployment_state") == "deployed"
            for card in cards.values() if isinstance(card, dict)
        ):
            errors.append(f"battle {battle_id} ready formation lacks the player")
        if not isinstance(participants, list) or not participants or len(participants) > policy.max_friendly_characters:
            errors.append(f"battle {battle_id} participant list is invalid")
        for actor_id in participants if isinstance(participants, list) else ():
            if battle.get("phase") != "resolved" and mapping.get(actor_id) != battle_id:
                errors.append(f"battle {battle_id} active participant {actor_id} is not mapped")
        enemy_units = battle.get("enemy_units")
        enemy_formations = battle.get("enemy_formations")
        enemy_health = battle.get("enemy_health")
        if not isinstance(enemy_units, dict) or not enemy_units:
            errors.append(f"battle {battle_id} enemy units are invalid")
        elif not isinstance(enemy_formations, dict) or set(enemy_formations) != set(COMBAT_ROWS):
            errors.append(f"battle {battle_id} enemy formation is invalid")
        elif not isinstance(enemy_health, dict) or set(enemy_health) != set(enemy_units):
            errors.append(f"battle {battle_id} enemy health ledger is invalid")
        else:
            deployed_enemies = [
                str(enemy_id) for row in COMBAT_ROWS
                for enemy_id in enemy_formations.get(row, ())
            ]
            if len(deployed_enemies) != len(set(deployed_enemies)) or set(deployed_enemies) != set(enemy_units):
                errors.append(f"battle {battle_id} enemy formation is not an exact partition")
            for enemy_id, enemy in enemy_units.items():
                if (
                    not isinstance(enemy, dict)
                    or enemy.get("enemy_instance_id") != enemy_id
                    or enemy.get("row") not in COMBAT_ROWS
                    or enemy_id not in enemy_formations.get(enemy.get("row"), ())
                ):
                    errors.append(f"battle {battle_id} enemy {enemy_id} is invalid")
                    continue
                health = enemy_health.get(enemy_id)
                if (
                    isinstance(health, bool) or not isinstance(health, int)
                    or not 0 <= health <= int(enemy.get("max_health", -1))
                ):
                    errors.append(f"battle {battle_id} enemy {enemy_id} health is invalid")
        barriers = battle.get("barriers")
        if not isinstance(barriers, dict) or set(barriers) != set(participants or ()):
            errors.append(f"battle {battle_id} barrier ledger is invalid")
        elif any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in barriers.values()
        ):
            errors.append(f"battle {battle_id} barrier values are invalid")
        if battle.get("phase") == "resolved" and battle.get("result") == "victory" and any(
            int(value) > 0 for value in (enemy_health or {}).values()
        ):
            errors.append(f"battle {battle_id} victory kept a living enemy")
        if battle.get("phase") in {"player_turn", "enemy_turn", "round_end"} or (
            battle.get("phase") == "resolved" and battle.get("card_instances")
        ):
            participant_set = set(participants) if isinstance(participants, list) else set()
            actor_decks = battle.get("actor_decks")
            draw_piles = battle.get("draw_piles")
            discard_piles = battle.get("discard_piles")
            exhaust_piles = battle.get("exhaust_piles")
            reshuffles = battle.get("reshuffle_counts")
            instances = battle.get("card_instances")
            hand = battle.get("shared_hand_ids")
            insight = battle.get("insight_row_ids")
            if not all(isinstance(value, dict) for value in (
                actor_decks, draw_piles, discard_piles, exhaust_piles, reshuffles, instances,
            )) or not isinstance(hand, list) or not isinstance(insight, list):
                errors.append(f"battle {battle_id} card runtime ledgers are invalid")
                continue
            if any(set(ledger) != participant_set for ledger in (
                actor_decks, draw_piles, discard_piles, exhaust_piles, reshuffles,
            )):
                errors.append(f"battle {battle_id} card runtime actor ledgers differ from participants")
            ledger_ids = list(hand) + list(insight)
            zone_by_id = {instance_id: "hand" for instance_id in hand}
            zone_by_id.update({instance_id: "insight" for instance_id in insight})
            for actor_id in participant_set:
                deck = actor_decks.get(actor_id, [])
                if not isinstance(deck, list) or len(deck) != round_policy.deck_size_per_actor:
                    errors.append(f"battle {battle_id} actor {actor_id} does not have eight deck cards")
                    continue
                for zone, ledger in (
                    ("draw", draw_piles), ("discard", discard_piles), ("exhaust", exhaust_piles),
                ):
                    pile = ledger.get(actor_id, [])
                    if not isinstance(pile, list):
                        errors.append(f"battle {battle_id} actor {actor_id} {zone} pile is invalid")
                        continue
                    ledger_ids.extend(pile)
                    zone_by_id.update({instance_id: zone for instance_id in pile})
                count = reshuffles.get(actor_id)
                if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                    errors.append(f"battle {battle_id} actor {actor_id} reshuffle count is invalid")
                instance_blueprints = [
                    instance.get("card_id") for instance in instances.values()
                    if isinstance(instance, dict) and instance.get("owner_actor_id") == actor_id
                ]
                if Counter(instance_blueprints) != Counter(deck):
                    errors.append(f"battle {battle_id} actor {actor_id} deck differs from instances")
            if len(ledger_ids) != len(set(ledger_ids)) or set(ledger_ids) != set(instances):
                errors.append(f"battle {battle_id} card zone ledgers are not an exact partition")
            for instance_id, instance in instances.items():
                if not isinstance(instance, dict) or instance.get("card_instance_id") != instance_id:
                    errors.append(f"battle {battle_id} card instance {instance_id} is invalid")
                    continue
                if instance.get("owner_actor_id") not in participant_set:
                    errors.append(f"battle {battle_id} card instance {instance_id} has an invalid owner")
                if instance.get("zone") != zone_by_id.get(instance_id):
                    errors.append(f"battle {battle_id} card instance {instance_id} zone is inconsistent")
            expected_cap = min(
                round_policy.maximum_command_points,
                round_policy.initial_command_points
                + (int(battle.get("round", 1)) - 1) * round_policy.command_point_growth_per_round,
            )
            if battle.get("command_point_cap") != expected_cap:
                errors.append(f"battle {battle_id} command point cap is inconsistent")
            for team_id in battle.get("team_ids", {}):
                value = battle.get("command_points", {}).get(team_id)
                if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= expected_cap:
                    errors.append(f"battle {battle_id} team {team_id} command points are invalid")
    return errors


__all__ = [
    "CAMPUS_COMBAT_SCHEMA_VERSION", "COMBAT_ACTION_IDS", "active_battle_for_actor",
    "build_character_card", "campus_combat_invariant", "campus_combat_view",
    "advance_campus_combat",
    "combat_policy_from_state", "combat_round_policy_from_state",
    "combat_preparation_assessment", "configured_actor_deck",
    "combat_readiness_assessment", "incapacitate_character", "legal_combat_targets",
    "install_campus_combat", "load_combat_deployment_policy", "load_combat_round_policy",
    "make_campus_combat_handler", "play_combat_card", "resolve_combat_effects",
    "start_card_combat", "end_combat_round", "use_combat_base_command",
]
