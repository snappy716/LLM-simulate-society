"""Small read-only projections consumed by Godot during kernel migration."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

from simulation.domain.world_state import WorldState
from simulation.systems.campus_schedules import current_schedule_slot


KERNEL_STATUS_VIEW_VERSION = 1
CAMPUS_WORLD_VIEW_VERSION = 4


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
    cast = {
        npc_id: {
            key: deepcopy(record.get(key))
            for key in (
                "npc_id", "display_name", "role_kind", "college_id", "occupation_id",
                "current_location_id", "home_location_id", "home_room_key",
                "simulation_tier", "night_access", "appearance_seed",
                "current_activity",
            )
        }
        for npc_id, record in state.population.items()
        if npc_id != "player" and isinstance(record, dict)
    }
    for npc_id in cast:
        cast[npc_id]["current_plan"] = current_schedule_slot(state, npc_id)
    schedule = state.metadata.get("campus_schedule", {})
    week_day = str((state.clock.day - 1) % 7)
    planned_occupancy = schedule.get("planned_occupancy", {})
    current_occupancy = planned_occupancy.get(week_day, {}).get(state.clock.phase, {})
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
    }


__all__ = [
    "CAMPUS_WORLD_VIEW_VERSION",
    "KERNEL_STATUS_VIEW_VERSION",
    "campus_world_view",
    "kernel_status_view",
]
