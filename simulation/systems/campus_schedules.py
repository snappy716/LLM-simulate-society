"""Deterministic weekly schedules with access, opening, and capacity fallback."""
from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, Mapping, Sequence

from simulation.domain.entities import PHASES
from simulation.domain.locations import CampusLocationGraph
from simulation.domain.schedules import (
    CampusScheduleTemplate,
    PlannedScheduleSlot,
    ScheduleSlotTemplate,
    parse_schedule_template,
)
from simulation.domain.world_state import WorldState
from simulation.systems.content_registry import ContentRegistry


LOCATION_TOKENS = {
    "home",
    "primary",
    "college_classroom",
    "college_practical",
    "club_or_library",
    "club_or_square",
    "library",
}

COLLEGE_CLASSROOMS = {
    "psychology": "humanities_classroom_pool",
    "humanities": "humanities_classroom_pool",
    "sports": "indoor_sports_hall",
}

COLLEGE_PRACTICALS = {
    "math_physics": "general_lab_pool",
    "bio_chemistry": "biochemistry_secure_lab",
    "earth_space": "earth_space_building",
    "artificial_intelligence": "ai_lab_pool",
    "psychology": "psychology_research_lab",
    "humanities": "humanities_seminar_pool",
    "medicine": "hospital_clinic",
    "sports": "indoor_sports_hall",
}


def load_campus_schedule_templates(
    registry: ContentRegistry,
    graph: CampusLocationGraph,
) -> Dict[str, CampusScheduleTemplate]:
    templates = {
        schedule_id: parse_schedule_template(payload)
        for schedule_id, payload in registry.all("schedule_template").items()
    }
    errors: list[str] = []
    for schedule_id, template in templates.items():
        for day in (template.weekday, template.weekend):
            for slot in day.values():
                if slot.location not in LOCATION_TOKENS and slot.location not in graph.node_ids:
                    errors.append(
                        f"schedule {schedule_id} references unknown location or token: {slot.location}"
                    )
    if errors:
        raise ValueError("invalid campus schedules: " + "; ".join(errors))
    return templates


def _stable_rank(master_seed: int, actor_id: str, day_index: int, phase: str) -> str:
    return hashlib.sha256(
        f"{master_seed}:schedule:{actor_id}:{day_index}:{phase}".encode("utf-8")
    ).hexdigest()


def _resolve_location_token(actor: Mapping[str, Any], token: str) -> str:
    if token == "home":
        return str(actor["home_location_id"])
    if token == "primary":
        return str(actor.get("primary_location_id") or actor["home_location_id"])
    if token == "library":
        return "library_reading_hall"
    if token == "college_classroom":
        return COLLEGE_CLASSROOMS.get(str(actor.get("college_id")), "science_classroom_pool")
    if token == "college_practical":
        if (
            actor.get("college_id") == "bio_chemistry"
            and "biosafety_access" not in actor.get("access_tags", ())
        ):
            return "general_lab_pool"
        return COLLEGE_PRACTICALS.get(
            str(actor.get("college_id")),
            str(actor.get("primary_location_id") or "general_lab_pool"),
        )
    if token in {"club_or_library", "club_or_square"}:
        if actor.get("club_ids"):
            return "club_room_pool"
        return "library_reading_hall" if token == "club_or_library" else "mirror_lake_square"
    return token


def _candidate_locations(actor: Mapping[str, Any], slot: ScheduleSlotTemplate) -> list[str]:
    requested = _resolve_location_token(actor, slot.location)
    fallbacks = [
        requested,
        str(actor.get("primary_location_id") or ""),
        "library_reading_hall",
        "mirror_lake_square",
        str(actor.get("home_location_id") or ""),
    ]
    if slot.activity_id == "REST":
        fallbacks.insert(0, str(actor.get("home_location_id") or ""))
    return list(dict.fromkeys(location for location in fallbacks if location))


def _lineage(graph: CampusLocationGraph, location_id: str) -> tuple[str, ...]:
    result: list[str] = []
    cursor = location_id
    seen: set[str] = set()
    while cursor in graph.locations and cursor not in seen:
        seen.add(cursor)
        result.append(cursor)
        cursor = graph.locations[cursor].parent_id
    return tuple(result)


def _can_enter(
    graph: CampusLocationGraph,
    actor: Mapping[str, Any],
    location_id: str,
    phase: str,
) -> bool:
    if location_id not in graph.node_ids or not graph.is_open(location_id, phase):
        return False
    location = graph.locations.get(location_id)
    if location is None:
        return True
    return set(location.access_tags).issubset(set(actor.get("access_tags", ())))


def _has_capacity(
    graph: CampusLocationGraph,
    occupancy: Counter[str],
    location_id: str,
) -> bool:
    return all(
        occupancy[node_id] < graph.locations[node_id].capacity
        for node_id in _lineage(graph, location_id)
    )


def _occupy(graph: CampusLocationGraph, occupancy: Counter[str], location_id: str) -> None:
    for node_id in _lineage(graph, location_id):
        occupancy[node_id] += 1


def install_campus_schedules(
    state: WorldState,
    graph: CampusLocationGraph,
    templates: Mapping[str, CampusScheduleTemplate],
) -> None:
    """Build a repeating seven-day plan for every actor without moving them yet."""
    if not state.population:
        raise ValueError("campus population must be installed before schedules")
    if "campus_schedule" in state.metadata:
        raise ValueError("campus schedules are already initialized")

    player = state.population.get("player")
    if isinstance(player, dict):
        player.setdefault("schedule_id", "new_psychology_student_weekday")
        player.setdefault("primary_location_id", "humanities_psychology_building")
        player.setdefault("club_ids", [])

    missing_templates = {
        str(actor.get("schedule_id"))
        for actor in state.population.values()
        if isinstance(actor, dict) and actor.get("schedule_id") not in templates
    }
    if missing_templates:
        raise ValueError("unknown actor schedule templates: " + ", ".join(sorted(missing_templates)))

    desired: Dict[tuple[int, str], list[tuple[str, ScheduleSlotTemplate]]] = defaultdict(list)
    for actor_id, actor in state.population.items():
        if not isinstance(actor, dict):
            continue
        template = templates[str(actor["schedule_id"])]
        for day_index in range(7):
            day_plan = template.weekday if day_index < 5 else template.weekend
            for phase in PHASES:
                desired[(day_index, phase.value)].append((actor_id, day_plan[phase.value]))

    direct_occupancy: Dict[str, Dict[str, Dict[str, int]]] = {}
    redirects = 0
    for day_index in range(7):
        day_key = str(day_index)
        direct_occupancy[day_key] = {}
        for phase in PHASES:
            phase_name = phase.value
            hierarchy_occupancy: Counter[str] = Counter()
            assigned: Counter[str] = Counter()
            requests = sorted(
                desired[(day_index, phase_name)],
                key=lambda item: (
                    -item[1].priority,
                    _stable_rank(state.master_seed, item[0], day_index, phase_name),
                ),
            )
            for actor_id, slot in requests:
                actor = state.population[actor_id]
                requested = _resolve_location_token(actor, slot.location)
                requested_legal = _can_enter(graph, actor, requested, phase_name)
                chosen = ""
                for candidate in _candidate_locations(actor, slot):
                    if not _can_enter(graph, actor, candidate, phase_name):
                        continue
                    if _has_capacity(graph, hierarchy_occupancy, candidate):
                        chosen = candidate
                        break
                if not chosen:
                    raise ValueError(
                        f"no legal schedule fallback for {actor_id} on day {day_index} {phase_name}"
                    )
                _occupy(graph, hierarchy_occupancy, chosen)
                assigned[chosen] += 1
                redirected = chosen != requested
                if redirected:
                    redirects += 1
                planned = PlannedScheduleSlot(
                    activity_id=slot.activity_id,
                    action_class=slot.action_class,
                    priority=slot.priority,
                    requested_location_id=requested,
                    location_id=chosen,
                    capacity_redirected=redirected,
                    redirect_reason=(
                        "capacity" if redirected and requested_legal else
                        "closed_or_access" if redirected else ""
                    ),
                )
                actor.setdefault("weekly_schedule", {}).setdefault(day_key, {})[
                    phase_name
                ] = planned.to_dict()
            direct_occupancy[day_key][phase_name] = dict(sorted(assigned.items()))

    state.metadata["campus_schedule"] = {
        "cycle_days": 7,
        "actor_count": len(state.population),
        "slot_count": len(state.population) * 7 * len(PHASES),
        "capacity_redirect_count": redirects,
        "planned_occupancy": direct_occupancy,
    }


def current_schedule_slot(state: WorldState, actor_id: str) -> Dict[str, Any]:
    actor = state.population.get(actor_id)
    if not isinstance(actor, dict):
        return {}
    week_day = str((state.clock.day - 1) % 7)
    weekly = actor.get("weekly_schedule", {})
    day = weekly.get(week_day, {}) if isinstance(weekly, dict) else {}
    slot = day.get(state.clock.phase, {}) if isinstance(day, dict) else {}
    return dict(slot) if isinstance(slot, dict) else {}


def campus_schedule_invariant(state: WorldState) -> Iterable[str]:
    if "campus_schedule" not in state.metadata:
        return ()
    errors: list[str] = []
    phase_names = {phase.value for phase in PHASES}
    for actor_id, actor in state.population.items():
        if not isinstance(actor, dict):
            errors.append(f"schedule actor {actor_id} must be a mapping")
            continue
        weekly = actor.get("weekly_schedule")
        if not isinstance(weekly, dict) or set(weekly) != {str(day) for day in range(7)}:
            errors.append(f"actor {actor_id} must have a seven-day schedule")
            continue
        for day_key, day in weekly.items():
            if not isinstance(day, dict) or set(day) != phase_names:
                errors.append(f"actor {actor_id} day {day_key} must define all phases")
                continue
            for phase, slot in day.items():
                if not isinstance(slot, dict):
                    errors.append(f"actor {actor_id} {day_key} {phase} slot must be a mapping")
                    continue
                location_id = slot.get("location_id")
                if location_id not in state.places:
                    errors.append(f"actor {actor_id} schedule references unknown place: {location_id}")
                if slot.get("action_class") not in {"free", "major"}:
                    errors.append(f"actor {actor_id} schedule has invalid action class")
    return errors


__all__ = [
    "LOCATION_TOKENS",
    "campus_schedule_invariant",
    "current_schedule_slot",
    "install_campus_schedules",
    "load_campus_schedule_templates",
]
