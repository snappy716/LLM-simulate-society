"""Sparse campus relationships and organization reputation consequences."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Iterable, Mapping

from simulation.domain.campus import RELATIONSHIP_NAMES
from simulation.domain.world_state import WorldState


DEFAULT_RELATIONSHIP: Dict[str, int] = {
    "familiarity": 0,
    "trust": 50,
    "closeness": 0,
    "respect": 0,
    "suspicion": 0,
    "fear": 0,
    "obligation": 0,
    "conflict": 0,
}


def install_campus_social_state(
    state: WorldState,
    clubs: Mapping[str, Mapping[str, Any]],
) -> None:
    """Install club membership and empty sparse relationship ledgers."""
    if state.relationships or state.organizations:
        raise ValueError("campus social aggregates are already initialized")
    for actor_id in sorted(state.population):
        state.relationships[actor_id] = {}
    for club_id, definition in sorted(clubs.items()):
        member_ids = sorted(
            actor_id
            for actor_id, actor in state.population.items()
            if isinstance(actor, dict) and club_id in actor.get("club_ids", ())
        )
        state.organizations[club_id] = {
            "organization_id": club_id,
            "name": str(definition.get("name", club_id)),
            "surface_skill": str(definition.get("surface_skill", "")),
            "night_skill": str(definition.get("night_skill", "")),
            "task_tags": list(definition.get("task_tags", ())),
            "member_ids": member_ids,
            "reputation_by_actor": {},
            "completed_tasks_by_actor": {},
        }


def relationship_between(state: WorldState, owner_id: str, target_id: str) -> Dict[str, int]:
    if owner_id not in state.population or target_id not in state.population:
        raise KeyError("relationship actors must exist in the campus population")
    owner_relations = state.relationships.setdefault(owner_id, {})
    relation = owner_relations.setdefault(target_id, deepcopy(DEFAULT_RELATIONSHIP))
    return relation


def adjust_relationship(
    state: WorldState,
    owner_id: str,
    target_id: str,
    deltas: Mapping[str, Any],
) -> Dict[str, int]:
    relation = relationship_between(state, owner_id, target_id)
    applied: Dict[str, int] = {}
    for dimension, raw_delta in deltas.items():
        if dimension not in RELATIONSHIP_NAMES:
            raise ValueError(f"unsupported relationship dimension: {dimension}")
        if isinstance(raw_delta, bool) or not isinstance(raw_delta, int):
            raise ValueError(f"relationship delta {dimension} must be an integer")
        before = int(relation[dimension])
        after = max(0, min(100, before + raw_delta))
        relation[dimension] = after
        applied[dimension] = after - before
    return applied


def adjust_organization_reputation(
    state: WorldState,
    organization_id: str,
    actor_id: str,
    delta: int,
    *,
    completed: bool = False,
) -> Dict[str, int]:
    organization = state.organizations.get(organization_id)
    if not isinstance(organization, dict):
        raise KeyError(f"unknown organization: {organization_id}")
    if actor_id not in state.population:
        raise KeyError(f"unknown actor: {actor_id}")
    reputation = organization.setdefault("reputation_by_actor", {})
    before = int(reputation.get(actor_id, 0))
    after = max(-100, min(100, before + delta))
    reputation[actor_id] = after
    completed_count = int(
        organization.setdefault("completed_tasks_by_actor", {}).get(actor_id, 0)
    )
    if completed:
        completed_count += 1
        organization["completed_tasks_by_actor"][actor_id] = completed_count
    return {
        "reputation_delta": after - before,
        "reputation": after,
        "completed_task_count": completed_count,
    }


def apply_task_social_consequence(
    state: WorldState,
    actor_id: str,
    task: Mapping[str, Any],
    outcome: str,
) -> Dict[str, Any]:
    consequence = task.get("social_consequences", {}).get(outcome, {})
    if not isinstance(consequence, dict):
        raise ValueError(f"task social consequence {outcome} must be a mapping")
    issuer_id = str(task.get("issuer_id", ""))
    relationship_delta = adjust_relationship(
        state,
        issuer_id,
        actor_id,
        consequence.get("issuer_relationship", {}),
    )
    result: Dict[str, Any] = {
        "outcome": outcome,
        "issuer_id": issuer_id,
        "relationship_delta": relationship_delta,
    }
    organization_id = task.get("organization_id")
    organization_delta = int(consequence.get("organization_reputation", 0))
    if isinstance(organization_id, str) and organization_id:
        result["organization_id"] = organization_id
        result["organization"] = adjust_organization_reputation(
            state,
            organization_id,
            actor_id,
            organization_delta,
            completed=outcome == "completed",
        )
        membership = state.organizations[organization_id].get("memberships", {}).get(actor_id)
        club_policy = state.metadata.get("campus_clubs", {}).get("policy", {})
        if outcome == "completed" and isinstance(membership, dict) and club_policy:
            contribution_gain = int(club_policy.get("task_contribution", 0))
            resource_gain = int(club_policy.get("task_resource_gain", 0))
            membership["contribution"] = int(membership.get("contribution", 0)) + contribution_gain
            resources = state.organizations[organization_id].get("resources", {})
            resource_before = int(resources.get("current", 0))
            resource_after = min(int(resources.get("capacity", 0)), resource_before + resource_gain)
            resources["current"] = resource_after
            resources["earned_total"] = int(resources.get("earned_total", 0)) + resource_after - resource_before
            result["club_contribution"] = {
                "contribution_gain": contribution_gain,
                "contribution": membership["contribution"],
                "resource_gain": resource_after - resource_before,
                "resource": resource_after,
            }
    return result


def campus_social_invariant(state: WorldState) -> Iterable[str]:
    errors: list[str] = []
    for owner_id, targets in state.relationships.items():
        if owner_id not in state.population:
            errors.append(f"relationship owner {owner_id} is unknown")
            continue
        if not isinstance(targets, dict):
            errors.append(f"relationships for {owner_id} must be a mapping")
            continue
        for target_id, relation in targets.items():
            if target_id not in state.population:
                errors.append(f"relationship target {target_id} is unknown")
            if not isinstance(relation, dict) or set(relation) != set(RELATIONSHIP_NAMES):
                errors.append(f"relationship {owner_id}->{target_id} has invalid dimensions")
                continue
            for dimension, value in relation.items():
                if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
                    errors.append(
                        f"relationship {owner_id}->{target_id} {dimension} is out of range"
                    )
    for organization_id, organization in state.organizations.items():
        if not isinstance(organization, dict):
            errors.append(f"organization {organization_id} must be a mapping")
            continue
        if organization.get("organization_id") != organization_id:
            errors.append(f"organization {organization_id} id mismatch")
        members = organization.get("member_ids", [])
        if len(members) != len(set(members)):
            errors.append(f"organization {organization_id} has duplicate members")
        for actor_id in members:
            actor = state.population.get(actor_id)
            if not isinstance(actor, dict) or organization_id not in actor.get("club_ids", ()):
                errors.append(f"organization {organization_id} has invalid member {actor_id}")
        for actor_id, reputation in organization.get("reputation_by_actor", {}).items():
            if actor_id not in state.population:
                errors.append(f"organization {organization_id} reputation actor is unknown")
            if isinstance(reputation, bool) or not isinstance(reputation, int) or not -100 <= reputation <= 100:
                errors.append(f"organization {organization_id} reputation is out of range")
    return errors


__all__ = [
    "DEFAULT_RELATIONSHIP",
    "adjust_organization_reputation",
    "adjust_relationship",
    "apply_task_social_consequence",
    "campus_social_invariant",
    "install_campus_social_state",
    "relationship_between",
]
