"""Small read-only projections consumed by Godot during kernel migration."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

from simulation.domain.world_state import WorldState


KERNEL_STATUS_VIEW_VERSION = 1
CAMPUS_WORLD_VIEW_VERSION = 1


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
    cast = {
        npc_id: {
            key: deepcopy(record.get(key))
            for key in (
                "npc_id", "display_name", "role_kind", "college_id", "occupation_id",
                "current_location_id", "home_location_id", "home_room_key",
                "simulation_tier", "night_access", "appearance_seed",
            )
        }
        for npc_id, record in state.population.items()
        if npc_id != "player" and isinstance(record, dict)
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
    }


__all__ = [
    "CAMPUS_WORLD_VIEW_VERSION",
    "KERNEL_STATUS_VIEW_VERSION",
    "campus_world_view",
    "kernel_status_view",
]
