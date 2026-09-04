"""Small read-only projections consumed by Godot during kernel migration."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

from simulation.domain.world_state import WorldState
from simulation.systems.campus_schedules import current_schedule_slot


KERNEL_STATUS_VIEW_VERSION = 1
CAMPUS_WORLD_VIEW_VERSION = 7


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
                "task_id", "forum", "title", "description", "objective",
                "action_id", "activity_id", "allowed_phases", "scene_id", "created_day", "expires_day",
                "state", "assignee_id", "lock_revision", "reward", "tags",
                "required_skill_ids", "required_item_ids", "history",
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
        })
    task_counts: Dict[str, int] = {}
    for task in public_tasks.values():
        state_name = str(task.get("state", "unknown"))
        task_counts[state_name] = task_counts.get(state_name, 0) + 1
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
    }


__all__ = [
    "CAMPUS_WORLD_VIEW_VERSION",
    "KERNEL_STATUS_VIEW_VERSION",
    "campus_world_view",
    "kernel_status_view",
]
