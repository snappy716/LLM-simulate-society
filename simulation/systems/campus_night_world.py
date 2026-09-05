"""Authoritative surface/night layer transitions, moon state, and pollution."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping

from simulation.domain.world_state import WorldState
from simulation.systems.transactions import TransactionOutcome


NIGHT_WORLD_SCHEMA_VERSION = 1
NIGHT_WORLD_ACTION_IDS = ("ENTER_NIGHT_WORLD", "EXIT_NIGHT_WORLD")


@dataclass(frozen=True)
class CampusNightWorldPolicy:
    entry_phases: tuple[str, ...]
    entry_region_ids: tuple[str, ...]
    player_entry_access: tuple[str, ...]
    npc_entry_access: tuple[str, ...]
    pollution_lock_threshold: int
    surface_morning_recovery: int
    daily_night_task_count: int
    active_npc_min: int
    active_npc_max: int
    task_views_per_npc_min: int
    task_views_per_npc_max: int
    npc_execute_delay_phases: int
    moon_phases: tuple[Mapping[str, Any], ...]

    def __post_init__(self) -> None:
        if not self.entry_phases or any(phase not in {"evening", "late_night"} for phase in self.entry_phases):
            raise ValueError("night-world entry phases must be evening or late_night")
        if not self.entry_region_ids or len(self.entry_region_ids) != len(set(self.entry_region_ids)):
            raise ValueError("night-world entry regions must be unique and non-empty")
        if not 1 <= self.pollution_lock_threshold <= 100:
            raise ValueError("night-world pollution lock threshold must be between 1 and 100")
        if not 0 <= self.surface_morning_recovery <= 100:
            raise ValueError("night-world recovery must be between 0 and 100")
        if self.daily_night_task_count < 1:
            raise ValueError("night forum must publish at least one task")
        if not 1 <= self.active_npc_min <= self.active_npc_max:
            raise ValueError("night-world active NPC range is invalid")
        if self.daily_night_task_count < self.active_npc_max:
            raise ValueError("night forum task count must cover the maximum active NPC count")
        if not 1 <= self.task_views_per_npc_min <= self.task_views_per_npc_max:
            raise ValueError("night forum viewer range is invalid")
        if self.npc_execute_delay_phases < 0:
            raise ValueError("night forum execution delay cannot be negative")
        expected_day = 1
        for phase in self.moon_phases:
            if int(phase.get("start_day", 0)) != expected_day:
                raise ValueError("night-world moon phases must cover demo days contiguously")
            end_day = int(phase.get("end_day", 0))
            if end_day < expected_day or not 0 <= int(phase.get("intensity", -1)) <= 100:
                raise ValueError("night-world moon phase range or intensity is invalid")
            for key in ("entry_pollution", "exposure_pollution"):
                if not 0 <= int(phase.get(key, -1)) <= 100:
                    raise ValueError(f"night-world {key} is invalid")
            expected_day = end_day + 1
        if expected_day != 29:
            raise ValueError("night-world moon phases must cover all 28 demo days")


def load_campus_night_world_policy(registry) -> CampusNightWorldPolicy:
    payload = registry.get("configuration", "night_world")
    forum = payload.get("night_forum", {})
    return CampusNightWorldPolicy(
        entry_phases=tuple(map(str, payload.get("entry_phases", ()))),
        entry_region_ids=tuple(map(str, payload.get("entry_region_ids", ()))),
        player_entry_access=tuple(map(str, payload.get("player_entry_access", ()))),
        npc_entry_access=tuple(map(str, payload.get("npc_entry_access", ()))),
        pollution_lock_threshold=int(payload.get("pollution_lock_threshold", 0)),
        surface_morning_recovery=int(payload.get("surface_morning_recovery", 0)),
        daily_night_task_count=int(forum.get("daily_task_count", 0)),
        active_npc_min=int(forum.get("active_npc_min", 0)),
        active_npc_max=int(forum.get("active_npc_max", 0)),
        task_views_per_npc_min=int(forum.get("task_views_per_npc_min", 0)),
        task_views_per_npc_max=int(forum.get("task_views_per_npc_max", 0)),
        npc_execute_delay_phases=int(forum.get("npc_execute_delay_phases", -1)),
        moon_phases=tuple(deepcopy(payload.get("moon_phases", ()))),
    )


def install_campus_night_world(state: WorldState, policy: CampusNightWorldPolicy) -> None:
    if "night_world" in state.situations:
        raise ValueError("campus night world is already installed")
    state.situations["night_world"] = {
        "schema_version": NIGHT_WORLD_SCHEMA_VERSION,
        "policy": {
            "entry_phases": list(policy.entry_phases),
            "entry_region_ids": list(policy.entry_region_ids),
            "player_entry_access": list(policy.player_entry_access),
            "npc_entry_access": list(policy.npc_entry_access),
            "pollution_lock_threshold": policy.pollution_lock_threshold,
            "surface_morning_recovery": policy.surface_morning_recovery,
            "daily_night_task_count": policy.daily_night_task_count,
            "active_npc_min": policy.active_npc_min,
            "active_npc_max": policy.active_npc_max,
            "task_views_per_npc_min": policy.task_views_per_npc_min,
            "task_views_per_npc_max": policy.task_views_per_npc_max,
            "npc_execute_delay_phases": policy.npc_execute_delay_phases,
            "moon_phases": deepcopy(list(policy.moon_phases)),
        },
        "actor_states": {
            actor_id: {
                "actor_id": actor_id,
                "layer": "surface",
                "pollution": 0,
                "night_forum_discovered": False,
                "last_transition_day": None,
                "last_transition_phase": None,
            }
            for actor_id in sorted(state.population)
        },
        "active_day": None,
        "active_actor_ids": [],
        "last_night_day": None,
        "last_night_actor_count": 0,
        "transition_sequence": 0,
    }


def night_world_policy_from_state(state: WorldState) -> CampusNightWorldPolicy | None:
    payload = state.situations.get("night_world", {}).get("policy")
    if not isinstance(payload, dict):
        return None
    return CampusNightWorldPolicy(
        entry_phases=tuple(map(str, payload.get("entry_phases", ()))),
        entry_region_ids=tuple(map(str, payload.get("entry_region_ids", ()))),
        player_entry_access=tuple(map(str, payload.get("player_entry_access", ()))),
        npc_entry_access=tuple(map(str, payload.get("npc_entry_access", ()))),
        pollution_lock_threshold=int(payload.get("pollution_lock_threshold", 0)),
        surface_morning_recovery=int(payload.get("surface_morning_recovery", 0)),
        daily_night_task_count=int(payload.get("daily_night_task_count", 0)),
        active_npc_min=int(payload.get("active_npc_min", 0)),
        active_npc_max=int(payload.get("active_npc_max", 0)),
        task_views_per_npc_min=int(payload.get("task_views_per_npc_min", 0)),
        task_views_per_npc_max=int(payload.get("task_views_per_npc_max", 0)),
        npc_execute_delay_phases=int(payload.get("npc_execute_delay_phases", -1)),
        moon_phases=tuple(deepcopy(payload.get("moon_phases", ()))),
    )


def moon_phase_for_day(policy: CampusNightWorldPolicy, day: int) -> Dict[str, Any]:
    cycle_day = ((max(1, day) - 1) % 28) + 1
    for phase in policy.moon_phases:
        if int(phase["start_day"]) <= cycle_day <= int(phase["end_day"]):
            return {**deepcopy(dict(phase)), "cycle_day": cycle_day}
    raise ValueError(f"no moon phase covers cycle day {cycle_day}")


def pollution_stage(value: int) -> str:
    if value >= 85:
        return "critical"
    if value >= 60:
        return "severe"
    if value >= 30:
        return "noticeable"
    return "stable"


def _actor_region_id(state: WorldState, actor_id: str) -> str:
    location_id = str(state.population[actor_id].get("current_location_id", ""))
    place = state.places.get(location_id, {})
    if not isinstance(place, dict):
        return ""
    return location_id if place.get("node_type") == "region" else str(place.get("region_id", ""))


def night_entry_assessment(
    state: WorldState,
    actor_id: str,
    policy: CampusNightWorldPolicy,
) -> Dict[str, Any]:
    if actor_id not in state.population:
        return {"allowed": False, "reason": "unknown_actor"}
    aggregate = state.situations.get("night_world", {})
    actor_state = aggregate.get("actor_states", {}).get(actor_id, {})
    if actor_state.get("layer") == "night":
        return {"allowed": False, "reason": "already_in_night_world"}
    if state.clock.phase not in policy.entry_phases:
        return {"allowed": False, "reason": "invalid_phase"}
    access = str(state.population[actor_id].get("night_access", "unaware"))
    allowed_access = policy.player_entry_access if actor_id == "player" else policy.npc_entry_access
    if access not in allowed_access:
        return {"allowed": False, "reason": "insufficient_night_access"}
    region_id = _actor_region_id(state, actor_id)
    if region_id not in policy.entry_region_ids:
        return {"allowed": False, "reason": "invalid_entry_location"}
    pollution = int(actor_state.get("pollution", 0))
    if pollution >= policy.pollution_lock_threshold:
        return {"allowed": False, "reason": "pollution_lock", "pollution": pollution}
    return {
        "allowed": True,
        "reason": "available",
        "region_id": region_id,
        "access": access,
        "moon": moon_phase_for_day(policy, state.clock.day),
    }


def make_campus_night_world_handler(policy: CampusNightWorldPolicy):
    def handle(context, command) -> TransactionOutcome:
        state = context.state
        if command.actor_id not in state.population:
            return TransactionOutcome(False, False, "unknown_actor", "行动者不存在。")
        aggregate = state.situations["night_world"]
        actor_state = aggregate["actor_states"][command.actor_id]
        if command.action_id == "ENTER_NIGHT_WORLD":
            assessment = night_entry_assessment(state, command.actor_id, policy)
            if not assessment["allowed"]:
                messages = {
                    "already_in_night_world": "已经位于夜相中。",
                    "invalid_phase": "只有晚间或深夜才能进入夜相。",
                    "insufficient_night_access": "目前还无法稳定感知并进入夜相。",
                    "invalid_entry_location": "当前位置不能作为夜相入口。",
                    "pollution_lock": "污染过高，继续进入夜相会失去自我稳定。",
                }
                return TransactionOutcome(
                    False, False, str(assessment["reason"]),
                    messages.get(str(assessment["reason"]), "目前无法进入夜相。"),
                )
            moon = assessment["moon"]
            actor_state["layer"] = "night"
            actor_state["night_forum_discovered"] = True
            actor_state["pollution"] = min(
                100, int(actor_state["pollution"]) + int(moon["entry_pollution"])
            )
            actor_state["last_transition_day"] = state.clock.day
            actor_state["last_transition_phase"] = state.clock.phase
            aggregate["transition_sequence"] += 1
            context.emit(
                "NIGHT_WORLD_ENTERED",
                f"{state.population[command.actor_id].get('display_name', command.actor_id)}进入了校园夜相。",
                actor_ids=[command.actor_id],
                scene_id=str(state.population[command.actor_id].get("current_location_id", "")) or None,
                payload={
                    "layer": "night", "moon_phase_id": moon["id"],
                    "moon_intensity": moon["intensity"], "pollution": actor_state["pollution"],
                    "action_class": "free",
                },
                visibility="secret", severity=4,
                knowledge_tags=["night_world", "moonlight", "pollution", "transition"],
            )
            return TransactionOutcome(
                True, True, "success", "已进入夜相。", commit=True,
                payload={"actor_state": deepcopy(actor_state), "moon": moon, "action_class": "free"},
            )
        if command.action_id == "EXIT_NIGHT_WORLD":
            if actor_state.get("layer") != "night":
                return TransactionOutcome(False, False, "not_in_night_world", "当前并不在夜相中。")
            actor_state["layer"] = "surface"
            actor_state["last_transition_day"] = state.clock.day
            actor_state["last_transition_phase"] = state.clock.phase
            aggregate["transition_sequence"] += 1
            context.emit(
                "NIGHT_WORLD_EXITED",
                f"{state.population[command.actor_id].get('display_name', command.actor_id)}返回了表世界。",
                actor_ids=[command.actor_id],
                scene_id=str(state.population[command.actor_id].get("current_location_id", "")) or None,
                payload={"layer": "surface", "pollution": actor_state["pollution"], "action_class": "free"},
                visibility="secret", severity=3,
                knowledge_tags=["night_world", "pollution", "transition"],
            )
            return TransactionOutcome(
                True, True, "success", "已返回表世界。", commit=True,
                payload={"actor_state": deepcopy(actor_state), "action_class": "free"},
            )
        return TransactionOutcome(False, False, "unknown_night_world_action", "未知夜相行动。")

    return handle


def advance_campus_night_world(context, policy: CampusNightWorldPolicy) -> Dict[str, int]:
    """Apply exposure, morning recovery, and mandatory daylight return."""
    state = context.state
    aggregate = state.situations["night_world"]
    moon = moon_phase_for_day(policy, state.clock.day)
    summary = {"night_auto_exit_count": 0, "night_exposure_count": 0, "pollution_recovery_count": 0}
    for actor_id, actor_state in aggregate["actor_states"].items():
        if state.clock.phase in {"morning", "afternoon"} and actor_state["layer"] == "night":
            actor_state["layer"] = "surface"
            actor_state["last_transition_day"] = state.clock.day
            actor_state["last_transition_phase"] = state.clock.phase
            aggregate["transition_sequence"] += 1
            summary["night_auto_exit_count"] += 1
            context.emit(
                "NIGHT_WORLD_AUTO_EXITED", "晨光迫使夜相中的行动者返回表世界。",
                actor_ids=[actor_id], payload={"pollution": actor_state["pollution"]},
                visibility="secret", severity=3,
                knowledge_tags=["night_world", "transition", "daylight"],
            )
        if state.clock.phase == "morning" and actor_state["layer"] == "surface":
            before = int(actor_state["pollution"])
            actor_state["pollution"] = max(0, before - policy.surface_morning_recovery)
            summary["pollution_recovery_count"] += int(actor_state["pollution"] != before)
        elif state.clock.phase in policy.entry_phases and actor_state["layer"] == "night":
            actor_state["pollution"] = min(
                100, int(actor_state["pollution"]) + int(moon["exposure_pollution"])
            )
            summary["night_exposure_count"] += 1
    return summary


def night_world_public_view(state: WorldState, policy: CampusNightWorldPolicy) -> Dict[str, Any]:
    aggregate = state.situations.get("night_world", {})
    actor_state = aggregate.get("actor_states", {}).get("player", {
        "actor_id": "player", "layer": "surface", "pollution": 0,
        "night_forum_discovered": False,
        "last_transition_day": None, "last_transition_phase": None,
    })
    assessment = night_entry_assessment(state, "player", policy) if aggregate else {
        "allowed": False, "reason": "not_installed",
    }
    moon = moon_phase_for_day(policy, state.clock.day)
    return {
        "enabled": bool(aggregate),
        "current_layer": actor_state.get("layer", "surface"),
        "pollution": int(actor_state.get("pollution", 0)),
        "pollution_stage": pollution_stage(int(actor_state.get("pollution", 0))),
        "can_enter": bool(assessment.get("allowed", False)),
        "entry_reason": str(assessment.get("reason", "not_installed")),
        "can_exit": actor_state.get("layer") == "night",
        "moon": moon,
        "night_forum_unlocked": bool(actor_state.get("night_forum_discovered", False)),
        "night_forum_accessible": actor_state.get("layer") == "night",
        "active_npc_count": sum(
            1
            for actor_id in aggregate.get("active_actor_ids", ())
            if actor_id != "player"
            and aggregate.get("actor_states", {}).get(actor_id, {}).get("layer") == "night"
        ),
        "last_night_npc_count": int(aggregate.get("last_night_actor_count", 0)),
    }


def campus_night_world_invariant(state: WorldState) -> Iterable[str]:
    aggregate = state.situations.get("night_world")
    if aggregate is None:
        return ()
    errors: list[str] = []
    if not isinstance(aggregate, dict) or aggregate.get("schema_version") != NIGHT_WORLD_SCHEMA_VERSION:
        return ("campus night-world aggregate is invalid",)
    actor_states = aggregate.get("actor_states")
    if not isinstance(actor_states, dict) or set(actor_states) != set(state.population):
        return ("campus night-world actor states do not match population",)
    for actor_id, actor_state in actor_states.items():
        if not isinstance(actor_state, dict) or actor_state.get("actor_id") != actor_id:
            errors.append(f"night-world state for {actor_id} is invalid")
            continue
        if actor_state.get("layer") not in {"surface", "night"}:
            errors.append(f"night-world layer for {actor_id} is invalid")
        pollution = actor_state.get("pollution")
        if isinstance(pollution, bool) or not isinstance(pollution, int) or not 0 <= pollution <= 100:
            errors.append(f"night-world pollution for {actor_id} is invalid")
        if not isinstance(actor_state.get("night_forum_discovered"), bool):
            errors.append(f"night-world forum discovery for {actor_id} is invalid")
        if state.clock.phase in {"morning", "afternoon"} and actor_state.get("layer") == "night":
            errors.append(f"night-world actor {actor_id} remained in night layer during daylight")
    sequence = aggregate.get("transition_sequence")
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
        errors.append("night-world transition sequence is invalid")
    active_ids = aggregate.get("active_actor_ids")
    if not isinstance(active_ids, list) or len(active_ids) != len(set(active_ids)):
        errors.append("night-world active actor list is invalid")
    elif any(actor_id not in state.population or actor_id == "player" for actor_id in active_ids):
        errors.append("night-world active actor list references an invalid NPC")
    active_day = aggregate.get("active_day")
    if active_day is not None and (isinstance(active_day, bool) or not isinstance(active_day, int) or active_day < 1):
        errors.append("night-world active day is invalid")
    last_night_day = aggregate.get("last_night_day")
    if last_night_day is not None and (
        isinstance(last_night_day, bool) or not isinstance(last_night_day, int) or last_night_day < 1
    ):
        errors.append("night-world last night day is invalid")
    last_count = aggregate.get("last_night_actor_count")
    if isinstance(last_count, bool) or not isinstance(last_count, int) or last_count < 0:
        errors.append("night-world last active count is invalid")
    return errors


__all__ = [
    "NIGHT_WORLD_ACTION_IDS", "NIGHT_WORLD_SCHEMA_VERSION", "CampusNightWorldPolicy",
    "advance_campus_night_world", "campus_night_world_invariant",
    "install_campus_night_world", "load_campus_night_world_policy",
    "make_campus_night_world_handler", "moon_phase_for_day",
    "night_entry_assessment", "night_world_public_view", "pollution_stage",
    "night_world_policy_from_state",
]
