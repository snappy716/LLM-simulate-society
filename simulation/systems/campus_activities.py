"""Execute NPC schedule slots through the authoritative campus movement rules."""
from __future__ import annotations

from typing import Any, Dict, Iterable

from simulation.actions.commands import CommandSource, SimulationCommand
from simulation.domain.action_economy import ActionEconomyPolicy
from simulation.domain.locations import CampusLocationGraph
from simulation.domain.world_state import WorldState
from simulation.systems.campus_locations import make_traverse_location_handler
from simulation.systems.campus_schedules import current_schedule_slot
from simulation.systems.time import consume_major_action


ACTIVITY_STATUSES = {"completed", "blocked"}


def _activity_record(
    state: WorldState,
    plan: Dict[str, Any],
    *,
    status: str,
    route_step_count: int,
    block_code: str = "",
) -> Dict[str, Any]:
    return {
        "activity_id": str(plan.get("activity_id", "")),
        "action_class": str(plan.get("action_class", "")),
        "location_id": str(plan.get("location_id", "")),
        "day": state.clock.day,
        "phase": state.clock.phase,
        "status": status,
        "route_step_count": route_step_count,
        "block_code": block_code,
    }


def make_scheduled_npc_phase_executor(
    graph: CampusLocationGraph,
    policy: ActionEconomyPolicy,
    traverse_handler=None,
):
    """Build a phase-start callback that moves and activates every scheduled NPC.

    The player is deliberately excluded: schedules advise the player but never
    take control away from them. NPC traversal calls the same handler used by
    player movement, so access, opening hours, exits, events, and location
    mutation have one source of truth.
    """
    traverse = traverse_handler or make_traverse_location_handler(graph)

    def execute(context, phase_command) -> Dict[str, int]:
        summary = {
            "planned_actor_count": 0,
            "moved_actor_count": 0,
            "route_step_count": 0,
            "major_activity_count": 0,
            "free_activity_count": 0,
            "blocked_actor_count": 0,
        }
        for actor_id in sorted(context.state.population):
            if actor_id == "player":
                continue
            actor = context.state.population.get(actor_id)
            if not isinstance(actor, dict):
                continue
            plan = current_schedule_slot(context.state, actor_id)
            if not plan:
                actor["current_activity"] = _activity_record(
                    context.state,
                    {},
                    status="blocked",
                    route_step_count=0,
                    block_code="missing_schedule_slot",
                )
                summary["blocked_actor_count"] += 1
                context.emit(
                    "NPC_ACTIVITY_BLOCKED",
                    f"{actor_id} 当前没有可执行的日程。",
                    actor_ids=[actor_id],
                    payload={"code": "missing_schedule_slot"},
                    visibility="private",
                    knowledge_tags=["schedule", "activity"],
                )
                continue

            summary["planned_actor_count"] += 1
            destination_id = str(plan.get("location_id", ""))
            route = graph.shortest_route(
                str(actor.get("current_location_id", "")),
                destination_id,
                phase=context.state.clock.phase,
                access_tags=actor.get("access_tags", ()),
            )
            if route is None:
                actor["current_activity"] = _activity_record(
                    context.state,
                    plan,
                    status="blocked",
                    route_step_count=0,
                    block_code="route_unavailable",
                )
                summary["blocked_actor_count"] += 1
                context.emit(
                    "NPC_ACTIVITY_BLOCKED",
                    f"{actor_id} 无法抵达计划地点 {destination_id}。",
                    actor_ids=[actor_id],
                    scene_id=str(actor.get("current_location_id", "")) or None,
                    payload={
                        "code": "route_unavailable",
                        "activity_id": plan.get("activity_id"),
                        "destination_id": destination_id,
                    },
                    visibility="private",
                    knowledge_tags=["schedule", "activity", "location"],
                )
                continue

            for step_index, step in enumerate(route.steps):
                movement_command = SimulationCommand(
                    command_id=f"{phase_command.command_id}:{actor_id}:move:{step_index}",
                    actor_id=actor_id,
                    action_id="TRAVERSE_LOCATION_PASSAGE",
                    expected_world_revision=context.state.revision,
                    parameters={"passage_id": step.passage_id},
                    issued_day=context.state.clock.day,
                    issued_phase=context.state.clock.phase,
                    issued_minute=context.state.clock.minute,
                    source=CommandSource.RULE.value,
                )
                outcome = traverse(context, movement_command)
                if not outcome.success:
                    raise RuntimeError(
                        f"scheduled route became invalid for {actor_id}: "
                        f"{step.passage_id} ({outcome.code})"
                    )

            route_step_count = len(route.steps)
            summary["route_step_count"] += route_step_count
            if route_step_count:
                summary["moved_actor_count"] += 1

            action_class = str(plan.get("action_class", ""))
            if action_class == "major":
                activity_command = SimulationCommand(
                    command_id=f"{phase_command.command_id}:{actor_id}:activity",
                    actor_id=actor_id,
                    action_id=str(plan.get("activity_id", "SCHEDULED_ACTIVITY")),
                    expected_world_revision=context.state.revision,
                    issued_day=context.state.clock.day,
                    issued_phase=context.state.clock.phase,
                    issued_minute=context.state.clock.minute,
                    source=CommandSource.RULE.value,
                )
                spent = consume_major_action(context.state, policy, activity_command)
                if not spent.success:
                    raise RuntimeError(
                        f"scheduled major action could not execute for {actor_id}: {spent.code}"
                    )
                summary["major_activity_count"] += 1
            elif action_class == "free":
                summary["free_activity_count"] += 1
            else:
                raise ValueError(f"unsupported schedule action class: {action_class}")

            actor["current_activity"] = _activity_record(
                context.state,
                plan,
                status="completed",
                route_step_count=route_step_count,
            )
            context.emit(
                "NPC_ACTIVITY_COMPLETED",
                f"{actor_id} 在 {destination_id} 完成 {plan.get('activity_id')}。",
                actor_ids=[actor_id],
                scene_id=destination_id,
                payload={
                    "activity_id": plan.get("activity_id"),
                    "action_class": action_class,
                    "location_id": destination_id,
                    "route_step_count": route_step_count,
                },
                visibility="private",
                knowledge_tags=["schedule", "activity"],
            )
        return summary

    return execute


def campus_activity_invariant(state: WorldState) -> Iterable[str]:
    errors: list[str] = []
    for actor_id, actor in state.population.items():
        if not isinstance(actor, dict):
            continue
        activity = actor.get("current_activity")
        if activity is None:
            continue
        if not isinstance(activity, dict):
            errors.append(f"actor {actor_id} current_activity must be a mapping")
            continue
        if activity.get("status") not in ACTIVITY_STATUSES:
            errors.append(f"actor {actor_id} current_activity has invalid status")
        if activity.get("day") != state.clock.day or activity.get("phase") != state.clock.phase:
            errors.append(f"actor {actor_id} current_activity clock mismatch")
        location_id = activity.get("location_id")
        if location_id and location_id not in state.places:
            errors.append(f"actor {actor_id} current_activity references unknown place")
        steps = activity.get("route_step_count")
        if isinstance(steps, bool) or not isinstance(steps, int) or steps < 0:
            errors.append(f"actor {actor_id} current_activity route steps must be non-negative")
        if activity.get("status") == "completed" and actor.get("current_location_id") != location_id:
            errors.append(f"actor {actor_id} completed activity away from its location")
    return errors


__all__ = [
    "ACTIVITY_STATUSES",
    "campus_activity_invariant",
    "make_scheduled_npc_phase_executor",
]
