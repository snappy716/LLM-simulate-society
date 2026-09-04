"""Small read-only projections consumed by Godot during kernel migration."""
from __future__ import annotations

import base64
import json
from copy import deepcopy
from typing import Any, Dict

from simulation.domain.world_state import WorldState
from simulation.systems.campus_schedules import current_schedule_slot


KERNEL_STATUS_VIEW_VERSION = 1
CAMPUS_WORLD_VIEW_VERSION = 10
NPC_CHRONICLE_VIEW_VERSION = 1


def _chronicle_cursor(actor_id: str, entry_id: str, filter_name: str) -> str:
    raw = json.dumps(
        {"actor_id": actor_id, "entry_id": entry_id, "filter": filter_name},
        ensure_ascii=True, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _parse_chronicle_cursor(cursor: str, actor_id: str, filter_name: str) -> str:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid chronicle cursor") from exc
    if not isinstance(payload, dict):
        raise ValueError("invalid chronicle cursor payload")
    if payload.get("actor_id") != actor_id or payload.get("filter") != filter_name:
        raise ValueError("chronicle cursor does not match this query")
    entry_id = payload.get("entry_id")
    if not isinstance(entry_id, str) or not entry_id:
        raise ValueError("invalid chronicle cursor entry")
    return entry_id


def _chronicle_visibility(state: WorldState, entry: Dict[str, Any], viewer_id: str) -> Dict[str, str] | None:
    if viewer_id == entry.get("actor_id"):
        return {"certainty": "reliable", "source": "self"}
    learned = state.chronicles.get("known_by", {}).get(viewer_id, {}).get(entry.get("entry_id"))
    if isinstance(learned, dict):
        return {"certainty": str(learned["certainty"]), "source": str(learned["source"])}
    if entry.get("visibility") == "public":
        return {"certainty": "reliable", "source": "public"}
    place = state.places.get(str(entry.get("scene_id", "")), {})
    place_tags = set(place.get("tags", ())) if isinstance(place, dict) else set()
    public_routine = (
        entry.get("visibility") == "observable"
        and entry.get("summary_key") == "activity_completed"
        and entry.get("phase") != "late_night"
        and not {"private", "restricted", "night"}.intersection(place_tags)
    )
    if public_routine:
        return {"certainty": "reported", "source": "campus_record"}
    return None


def _chronicle_display_summary(state: WorldState, entry: Dict[str, Any]) -> str:
    parameters = entry.get("parameters", {})
    if entry.get("summary_key") == "activity_completed":
        activity_id = str(parameters.get("activity_id", "校园活动"))
        place = state.places.get(str(entry.get("scene_id", "")), {})
        place_name = place.get("name", entry.get("scene_id", "未知地点")) if isinstance(place, dict) else "未知地点"
        return f"在{place_name}完成了{activity_id}。"
    if entry.get("summary_key") == "routine_actions_completed":
        actions = parameters.get("actions", ())
        return "完成了日常安排" + (f"（{'、'.join(map(str, actions))}）" if actions else "。")
    return str(parameters.get("public_summary", entry.get("event_type", "发生了一件事。")))


def npc_chronicle_view(
    state: WorldState,
    npc_id: str,
    *,
    viewer_id: str = "player",
    cursor: str = "",
    limit: int = 20,
    filter_name: str = "recent",
) -> Dict[str, Any]:
    """Return a privacy-filtered, newest-first page without polluting the world snapshot."""
    state.require_valid()
    if npc_id not in state.population:
        raise ValueError(f"unknown NPC: {npc_id}")
    if viewer_id not in state.population:
        raise ValueError(f"unknown chronicle viewer: {viewer_id}")
    if filter_name not in {"recent", "important", "all"}:
        raise ValueError(f"unsupported chronicle filter: {filter_name}")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
        raise ValueError("chronicle limit must be between 1 and 50")
    aggregate = state.chronicles
    ids = list(reversed(aggregate.get("by_actor", {}).get(npc_id, ())))
    entries = aggregate.get("entries", {})
    visible: list[Dict[str, Any]] = []
    earliest_recent_day = max(1, state.clock.day - 6)
    for entry_id in ids:
        entry = entries.get(entry_id)
        if not isinstance(entry, dict):
            continue
        if filter_name == "recent" and int(entry.get("day", 0)) < earliest_recent_day:
            continue
        if filter_name == "important" and int(entry.get("importance", 0)) < 2:
            continue
        visibility = _chronicle_visibility(state, entry, viewer_id)
        if visibility is None:
            continue
        payload = deepcopy(entry)
        payload.update(visibility)
        payload["scene_name"] = state.places.get(str(entry.get("scene_id", "")), {}).get(
            "name", entry.get("scene_id", "未知地点")
        )
        payload["related_actor_names"] = [
            state.population.get(actor_id, {}).get("display_name", actor_id)
            for actor_id in entry.get("related_actor_ids", ())
        ]
        payload["display_summary"] = _chronicle_display_summary(state, entry)
        visible.append(payload)
    if cursor:
        after_id = _parse_chronicle_cursor(cursor, npc_id, filter_name)
        position = next(
            (index for index, item in enumerate(visible) if item["entry_id"] == after_id),
            None,
        )
        if position is None:
            raise ValueError("chronicle cursor is stale or not visible")
        visible = visible[position + 1:]
    page = visible[:limit]
    has_more = len(visible) > limit
    next_cursor = _chronicle_cursor(npc_id, page[-1]["entry_id"], filter_name) if has_more and page else ""
    actor = state.population[npc_id]
    return {
        "view_version": NPC_CHRONICLE_VIEW_VERSION,
        "world_revision": state.revision,
        "actor": {
            "npc_id": npc_id,
            "display_name": actor.get("display_name", npc_id),
        },
        "filter": filter_name,
        "items": page,
        "has_more": has_more,
        "next_cursor": next_cursor,
        "knowledge_note": "只显示玩家已目击、公开可查、被告知或调查获得的记录。",
    }


def kernel_status_view(state: WorldState, *, busy: bool = False) -> Dict[str, Any]:
    state.require_valid()
    return {
        "view_version": KERNEL_STATUS_VIEW_VERSION,
        "revision": state.revision,
        "clock": {
            "day": state.clock.day,
            "phase": state.clock.phase,
            "minute": state.clock.minute,
        },
        "content_version": state.content_version,
        "busy": bool(busy),
    }


def campus_world_view(state: WorldState) -> Dict[str, Any]:
    """Project only the campus data Godot needs for movement and population UI."""
    state.require_valid()
    player = deepcopy(state.population.get("player", {}))
    actor_budgets = state.action_economy.get("actors", {})
    player["action_budget"] = deepcopy(actor_budgets.get("player", {}))
    player["current_plan"] = current_schedule_slot(state, "player")
    player["knowledge_progress"] = deepcopy(
        state.knowledge.get("actors", {}).get("player", {})
    )
    ability_system = state.metadata.get("campus_abilities", {})
    ability_definitions = ability_system.get("definitions", {})
    card_blueprints = ability_system.get("card_blueprints", {})

    def public_abilities(actor: Dict[str, Any]) -> list[Dict[str, Any]]:
        result: list[Dict[str, Any]] = []
        for ability_id, progress in actor.get("ability_progress", {}).items():
            definition = ability_definitions.get(ability_id)
            if not isinstance(definition, dict):
                continue
            result.append({
                "ability_id": ability_id,
                "name": definition.get("name", ability_id),
                "source_kind": definition.get("source_kind", "common"),
                "profile_id": definition.get("profile_id", ""),
                "check_tags": deepcopy(definition.get("check_tags", [])),
                "surface_modifier": definition.get("surface_modifier", 0),
                "rank": progress.get("rank", 1),
                "experience": progress.get("experience", 0),
                "card_id": definition.get("card_id", ""),
            })
        return sorted(result, key=lambda entry: (entry["source_kind"] != "common", entry["ability_id"]))

    def public_cards(actor: Dict[str, Any]) -> list[Dict[str, Any]]:
        return [
            deepcopy(card_blueprints[card_id])
            for card_id in actor.get("card_pool_ids", ())
            if card_id in card_blueprints
        ]

    player["abilities"] = public_abilities(player)
    player["card_pool"] = public_cards(player)
    cast = {
        npc_id: {
            key: deepcopy(record.get(key))
            for key in (
                "npc_id", "display_name", "role_kind", "college_id", "occupation_id",
                "current_location_id", "home_location_id", "home_room_key",
                "simulation_tier", "night_access", "appearance_seed",
                "current_activity", "needs", "emotions", "activity_progress",
                "last_activity_effects",
            )
        }
        for npc_id, record in state.population.items()
        if npc_id != "player" and isinstance(record, dict)
    }
    for npc_id in cast:
        source_record = state.population.get(npc_id, {})
        decision = source_record.get("current_decision") if isinstance(source_record, dict) else None
        cast[npc_id]["current_plan"] = (
            {
                key: deepcopy(decision.get(key))
                for key in ("activity_id", "action_class", "location_id", "day", "phase")
            }
            if isinstance(decision, dict)
            and decision.get("day") == state.clock.day
            and decision.get("phase") == state.clock.phase
            else current_schedule_slot(state, npc_id)
        )
        cast[npc_id]["knowledge_progress"] = deepcopy(
            state.knowledge.get("actors", {}).get(npc_id, {})
        )
        cast[npc_id]["abilities"] = public_abilities(source_record)
        cast[npc_id]["card_pool_ids"] = list(source_record.get("card_pool_ids", ()))
    schedule = state.metadata.get("campus_schedule", {})
    week_day = str((state.clock.day - 1) % 7)
    planned_occupancy = schedule.get("planned_occupancy", {})
    current_occupancy = planned_occupancy.get(week_day, {}).get(state.clock.phase, {})
    public_tasks = {}
    for task_id, task in state.tasks.items():
        if not isinstance(task, dict):
            continue
        issuer = state.population.get(str(task.get("issuer_id", "")), {})
        assignee = state.population.get(str(task.get("assignee_id", "")), {})
        place = state.places.get(str(task.get("scene_id", "")), {})
        public_tasks[task_id] = {
            key: deepcopy(task.get(key))
            for key in (
                "task_id", "template_id", "forum", "issuer_id", "title", "description", "objective",
                "action_id", "activity_id", "allowed_phases", "scene_id", "execution_region_id",
                "created_day", "expires_day",
                "state", "assignee_id", "lock_revision", "reward", "tags",
                "required_skill_ids", "required_item_ids", "history",
                "organization_id", "social_consequences", "social_result",
                "chain_parent_template_id", "unlocked_follow_up_template_ids",
            )
        }
        public_tasks[task_id].update({
            "issuer_name": issuer.get("display_name", "校园用户"),
            "assignee_name": assignee.get("display_name", "") if isinstance(assignee, dict) else "",
            "scene_name": place.get("name", task.get("scene_id", "")) if isinstance(place, dict) else task.get("scene_id", ""),
            "viewer_count": len(task.get("viewer_ids", ())),
            "considering_count": len(task.get("considering_ids", ())),
            "viewed_by_player": "player" in task.get("viewer_ids", ()),
            "owned_by_player": task.get("assignee_id") == "player",
            "organization_name": (
                state.organizations.get(str(task.get("organization_id", "")), {}).get("name", "")
            ),
        })
    task_counts: Dict[str, int] = {}
    for task in public_tasks.values():
        state_name = str(task.get("state", "unknown"))
        task_counts[state_name] = task_counts.get(state_name, 0) + 1
    player_relationships = {}
    for issuer_id, targets in state.relationships.items():
        if not isinstance(targets, dict):
            continue
        dimensions = targets.get("player")
        if isinstance(dimensions, dict):
            player_relationships[issuer_id] = {
                "display_name": state.population.get(issuer_id, {}).get(
                    "display_name", issuer_id
                ),
                **deepcopy(dimensions),
            }
    player_organizations = {
        organization_id: {
            "organization_id": organization_id,
            "name": organization.get("name", organization_id),
            "reputation": int(organization.get("reputation_by_actor", {}).get("player", 0)),
            "completed_task_count": int(
                organization.get("completed_tasks_by_actor", {}).get("player", 0)
            ),
            "is_member": "player" in organization.get("member_ids", ()),
        }
        for organization_id, organization in state.organizations.items()
        if isinstance(organization, dict)
        and (
            "player" in organization.get("member_ids", ())
            or "player" in organization.get("reputation_by_actor", {})
        )
    }
    return {
        "view_version": CAMPUS_WORLD_VIEW_VERSION,
        "revision": state.revision,
        "clock": {
            "day": state.clock.day,
            "phase": state.clock.phase,
            "minute": state.clock.minute,
        },
        "content_version": state.content_version,
        "player": player,
        "places": deepcopy(state.places),
        "passages": deepcopy(state.metadata.get("campus_passages", {})),
        "interior_templates": deepcopy(state.metadata.get("interior_templates", {})),
        "population": cast,
        "population_summary": deepcopy(state.metadata.get("campus_population", {})),
        "action_economy": {
            "policy": deepcopy(state.action_economy.get("policy", {})),
            "player": deepcopy(actor_budgets.get("player", {})),
        },
        "schedule": {
            "cycle_days": schedule.get("cycle_days", 0),
            "current_planned_occupancy": deepcopy(current_occupancy),
            "capacity_redirect_count": schedule.get("capacity_redirect_count", 0),
        },
        "forums": deepcopy(state.forums),
        "tasks": public_tasks,
        "task_summary": {
            "total": len(public_tasks),
            "by_state": task_counts,
            "available": sum(
                count for name, count in task_counts.items()
                if name in {"open", "viewed", "considering"}
            ),
            "mine": sum(1 for task in public_tasks.values() if task.get("owned_by_player")),
        },
        "social": {
            "player_relationships": player_relationships,
            "player_organizations": player_organizations,
        },
    }


__all__ = [
    "CAMPUS_WORLD_VIEW_VERSION",
    "KERNEL_STATUS_VIEW_VERSION",
    "NPC_CHRONICLE_VIEW_VERSION",
    "campus_world_view",
    "kernel_status_view",
    "npc_chronicle_view",
]
