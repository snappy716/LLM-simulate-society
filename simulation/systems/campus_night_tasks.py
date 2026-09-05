"""Restricted night forum and deterministic autonomous night participation."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Iterable, Mapping

from simulation.domain.entities import PHASES
from simulation.domain.locations import CampusLocationGraph
from simulation.domain.world_state import WorldState
from simulation.systems.campus_night_world import (
    CampusNightWorldPolicy,
    moon_phase_for_day,
    night_entry_assessment,
)
from simulation.systems.campus_schedules import current_schedule_slot
from simulation.systems.campus_social import apply_task_social_consequence
from simulation.systems.campus_tasks import ACTIVE_STATES, AVAILABLE_STATES, TERMINAL_STATES, phase_index


def load_night_task_templates(registry) -> Dict[str, Dict[str, Any]]:
    templates = registry.all("night_task_template")
    if not templates:
        raise ValueError("at least one night task template is required")
    required = {
        "id", "title", "description", "objective", "activity_id", "scene_id",
        "enemy_archetype_id",
    }
    for template_id, template in templates.items():
        missing = required - set(template)
        if missing:
            raise ValueError(f"night task {template_id} missing fields: {sorted(missing)}")
        if template.get("scene_id") not in registry.ids("campus_location") and template.get(
            "scene_id"
        ) not in registry.ids("campus_region"):
            raise ValueError(f"night task {template_id} references an unknown campus place")
        if template.get("enemy_archetype_id") not in registry.ids("enemy_archetype"):
            raise ValueError(f"night task {template_id} references an unknown enemy archetype")
    return templates


def _history(day: int, phase: str, kind: str, message: str) -> Dict[str, Any]:
    return {"day": day, "phase": phase, "kind": kind, "message": message}


def _actor_has_active_task(state: WorldState, actor_id: str) -> bool:
    task_id = state.population.get(actor_id, {}).get("active_forum_task_id")
    task = state.tasks.get(str(task_id)) if task_id else None
    return bool(
        isinstance(task, dict)
        and task.get("assignee_id") == actor_id
        and task.get("state") in ACTIVE_STATES
    )


def _eligible_night_npcs(
    context,
    policy: CampusNightWorldPolicy,
) -> list[tuple[float, str]]:
    state = context.state
    rng = context.rng.stream("campus_night_participation")
    result: list[tuple[float, str]] = []
    for actor_id, actor in sorted(state.population.items()):
        if actor_id == "player" or not isinstance(actor, dict) or _actor_has_active_task(state, actor_id):
            continue
        assessment = night_entry_assessment(state, actor_id, policy)
        if not assessment.get("allowed"):
            continue
        schedule = current_schedule_slot(state, actor_id)
        if schedule and int(schedule.get("priority", 0)) >= 90:
            continue
        week_day = str((state.clock.day - 1) % 7)
        late_night_schedule = actor.get("weekly_schedule", {}).get(week_day, {}).get(
            "late_night", {}
        )
        if isinstance(late_night_schedule, dict) and int(late_night_schedule.get("priority", 0)) >= 90:
            continue
        personality = actor.get("personality", {})
        needs = actor.get("needs", {})
        actor_state = state.situations["night_world"]["actor_states"][actor_id]
        score = 30.0
        score += 28.0 if actor.get("night_access") == "willing" else 10.0
        score += 0.24 * float(personality.get("risk_tolerance", 50))
        score += 0.14 * float(personality.get("altruism", 50))
        score += 0.12 * float(needs.get("curiosity", 0))
        score -= 0.45 * float(actor_state.get("pollution", 0))
        score += rng.uniform(-8.0, 8.0)
        result.append((score, actor_id))
    return sorted(result, key=lambda item: (-item[0], item[1]))


def _enter_autonomous_npcs(context, policy: CampusNightWorldPolicy) -> list[str]:
    state = context.state
    aggregate = state.situations["night_world"]
    if state.clock.phase != "evening" or aggregate.get("active_day") == state.clock.day:
        return []
    ranked = _eligible_night_npcs(context, policy)
    rng = context.rng.stream("campus_night_participation")
    target_count = min(len(ranked), rng.randint(policy.active_npc_min, policy.active_npc_max))
    selected = [actor_id for _, actor_id in ranked[:target_count]]
    moon = moon_phase_for_day(policy, state.clock.day)
    for actor_id in selected:
        actor_state = aggregate["actor_states"][actor_id]
        actor_state["layer"] = "night"
        actor_state["night_forum_discovered"] = True
        actor_state["pollution"] = min(
            100, int(actor_state.get("pollution", 0)) + int(moon["entry_pollution"])
        )
        actor_state["last_transition_day"] = state.clock.day
        actor_state["last_transition_phase"] = state.clock.phase
        aggregate["transition_sequence"] += 1
        context.emit(
            "NIGHT_WORLD_ENTERED",
            f"{state.population[actor_id].get('display_name', actor_id)}主动进入了校园夜相。",
            actor_ids=[actor_id],
            scene_id=str(state.population[actor_id].get("current_location_id", "")) or None,
            payload={
                "layer": "night",
                "moon_phase_id": moon["id"],
                "moon_intensity": moon["intensity"],
                "pollution": actor_state["pollution"],
                "action_class": "free",
                "autonomous": True,
            },
            visibility="secret",
            severity=4,
            knowledge_tags=["night_world", "night", "pollution", "transition"],
        )
    aggregate["active_day"] = state.clock.day
    aggregate["active_actor_ids"] = selected
    return selected


def _publish_night_tasks(
    context,
    templates: Mapping[str, Mapping[str, Any]],
    policy: CampusNightWorldPolicy,
    social_consequences: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    state = context.state
    forum = state.forums["night"]
    if state.clock.phase != "evening" or int(forum.get("last_published_day", 0)) >= state.clock.day:
        return []
    rng = context.rng.stream("campus_night_forum")
    template_ids = sorted(templates)
    issuer_ids = [
        actor_id
        for actor_id, actor in sorted(state.population.items())
        if actor_id != "player" and actor.get("night_access") in policy.npc_entry_access
    ]
    if not issuer_ids:
        raise ValueError("night forum has no eligible issuers")
    sequence = int(forum.get("published_total", 0))
    published: list[str] = []
    now = phase_index(state.clock.day, state.clock.phase)
    for _ in range(policy.daily_night_task_count):
        template_id = rng.choice(template_ids)
        template = templates[template_id]
        sequence += 1
        task_id = f"night:d{state.clock.day:02d}:{sequence:04d}:{template_id}"
        task = {
            "task_id": task_id,
            "template_id": template_id,
            "forum": "night",
            "world_layer": "night",
            "issuer_id": rng.choice(issuer_ids),
            "title": str(template["title"]),
            "description": str(template["description"]),
            "objective": str(template["objective"]),
            "action_id": str(template["activity_id"]),
            "activity_id": str(template["activity_id"]),
            "enemy_archetype_id": str(template["enemy_archetype_id"]),
            "allowed_phases": list(template.get("allowed_phases", ("evening", "late_night"))),
            "scene_id": str(template["scene_id"]),
            "execution_region_id": str(
                state.places[str(template["scene_id"])].get("region_id") or template["scene_id"]
            ),
            "created_day": state.clock.day,
            "expires_day": state.clock.day,
            "state": "open",
            "assignee_id": None,
            "lock_revision": 0,
            "viewer_ids": [],
            "considering_ids": [],
            "helper_ids": [],
            "required_skill_ids": list(template.get("required_skill_ids", ())),
            "required_item_ids": list(template.get("required_item_ids", ())),
            "reward": dict(template.get("reward", {})),
            "tags": list(template.get("tags", ())),
            "preferred_college_ids": list(template.get("preferred_college_ids", ())),
            "preferred_club_ids": list(template.get("preferred_club_ids", ())),
            "organization_id": None,
            "social_consequences": deepcopy(social_consequences),
            "follow_up_template_ids": [],
            "chain_parent_template_id": None,
            "npc_claim_phase_index": now,
            "npc_execute_after_phase_index": None,
            "history": [
                _history(state.clock.day, state.clock.phase, "published", "异常委托已发布到夜间论坛。")
            ],
        }
        state.tasks[task_id] = task
        published.append(task_id)
        context.emit(
            "FORUM_TASK_PUBLISHED",
            f"夜间论坛发布了《{task['title']}》。",
            target_ids=[task["issuer_id"]],
            scene_id=task["scene_id"],
            payload={"task_id": task_id, "forum": "night", "world_layer": "night"},
            visibility="secret",
            severity=3,
            knowledge_tags=["forum", "task", "night"],
        )
    forum.update({
        "last_published_day": state.clock.day,
        "published_total": sequence,
        "last_batch_count": len(published),
    })
    return published


def _task_score(
    state: WorldState,
    graph: CampusLocationGraph,
    actor_id: str,
    task: Mapping[str, Any],
) -> float | None:
    actor = state.population[actor_id]
    route = graph.shortest_route(
        str(actor.get("current_location_id", "")),
        str(task.get("scene_id", "")),
        phase=state.clock.phase,
        access_tags=actor.get("access_tags", ()),
    )
    if route is None:
        return None
    attributes = actor.get("attributes", {})
    score = 20.0 - min(30.0, route.total_minutes * 0.35)
    if actor.get("college_id") in task.get("preferred_college_ids", ()):
        score += 32.0
    if set(actor.get("club_ids", ())) & set(task.get("preferred_club_ids", ())):
        score += 24.0
    if set(task.get("required_skill_ids", ())).issubset(set(actor.get("skill_ids", ()))):
        score += 14.0
    score += 1.5 * float(attributes.get("insight", 5))
    score += 1.0 * float(attributes.get("focus", 5))
    return score


def _assign_night_tasks(
    context,
    graph: CampusLocationGraph,
    policy: CampusNightWorldPolicy,
) -> Dict[str, int]:
    state = context.state
    aggregate = state.situations["night_world"]
    if state.clock.phase not in policy.entry_phases or aggregate.get("active_day") != state.clock.day:
        return {"night_task_view_count": 0, "night_npc_claim_count": 0}
    rng = context.rng.stream("campus_night_forum")
    viewed = 0
    claimed = 0
    for actor_id in aggregate.get("active_actor_ids", ()):
        if _actor_has_active_task(state, actor_id):
            continue
        schedule = current_schedule_slot(state, actor_id)
        if schedule and int(schedule.get("priority", 0)) >= 90:
            continue
        candidates = [
            task
            for task in state.tasks.values()
            if isinstance(task, dict)
            and task.get("forum") == "night"
            and task.get("state") in AVAILABLE_STATES
            and task.get("issuer_id") != actor_id
        ]
        if not candidates:
            break
        unseen = [task for task in candidates if actor_id not in task.get("viewer_ids", ())]
        view_count = min(
            len(unseen),
            rng.randint(policy.task_views_per_npc_min, policy.task_views_per_npc_max),
        )
        for task in rng.sample(unseen, view_count):
            task["viewer_ids"].append(actor_id)
            if task["state"] == "open":
                task["state"] = "viewed"
            viewed += 1
        ranked = sorted(
            (
                (score, str(task["task_id"]), task)
                for task in candidates
                if actor_id in task.get("viewer_ids", ())
                for score in [_task_score(state, graph, actor_id, task)]
                if score is not None
            ),
            key=lambda item: (-item[0], item[1]),
        )
        if not ranked:
            continue
        task = ranked[0][2]
        if actor_id not in task["considering_ids"]:
            task["considering_ids"].append(actor_id)
        task["assignee_id"] = actor_id
        task["state"] = "locked"
        task["lock_revision"] = int(task.get("lock_revision", 0)) + 1
        task["npc_execute_after_phase_index"] = (
            phase_index(state.clock.day, state.clock.phase) + policy.npc_execute_delay_phases
        )
        state.population[actor_id]["active_forum_task_id"] = task["task_id"]
        task["history"].append(
            _history(
                state.clock.day,
                state.clock.phase,
                "claimed",
                f"{state.population[actor_id].get('display_name', actor_id)} 接下了任务。",
            )
        )
        context.emit(
            "FORUM_TASK_CLAIMED",
            f"{state.population[actor_id].get('display_name', actor_id)} 接下了《{task['title']}》。",
            actor_ids=[actor_id],
            target_ids=[task["issuer_id"]],
            scene_id=task["scene_id"],
            payload={"task_id": task["task_id"], "forum": "night", "world_layer": "night"},
            visibility="secret",
            severity=3,
            knowledge_tags=["forum", "task", "night"],
        )
        claimed += 1
    return {"night_task_view_count": viewed, "night_npc_claim_count": claimed}


def _expire_previous_night(context) -> int:
    state = context.state
    if state.clock.phase != PHASES[0].value:
        return 0
    expired = 0
    for task in state.tasks.values():
        if (
            not isinstance(task, dict)
            or task.get("forum") != "night"
            or task.get("state") in TERMINAL_STATES
            or state.clock.day <= int(task.get("expires_day", 0))
        ):
            continue
        assignee_id = task.get("assignee_id")
        actor = state.population.get(str(assignee_id)) if assignee_id else None
        if isinstance(actor, dict):
            actor.pop("active_forum_task_id", None)
            task["social_result"] = apply_task_social_consequence(
                state, str(assignee_id), task, "expired"
            )
        task["state"] = "expired"
        task["lock_revision"] = int(task.get("lock_revision", 0)) + 1
        task["history"].append(
            _history(state.clock.day, state.clock.phase, "expired", "晨光到来，异常委托已经失效。")
        )
        context.emit(
            "FORUM_TASK_EXPIRED",
            f"夜间委托《{task['title']}》随晨光失效。",
            actor_ids=[str(assignee_id)] if assignee_id else [],
            target_ids=[task["issuer_id"]],
            scene_id=task["scene_id"],
            payload={"task_id": task["task_id"], "forum": "night"},
            visibility="secret",
            severity=3,
            knowledge_tags=["forum", "task", "night", "expired"],
        )
        expired += 1
    aggregate = state.situations["night_world"]
    if aggregate.get("active_actor_ids"):
        aggregate["last_night_day"] = aggregate.get("active_day")
        aggregate["last_night_actor_count"] = len(aggregate["active_actor_ids"])
    aggregate["active_day"] = None
    aggregate["active_actor_ids"] = []
    return expired


def advance_campus_night_forum(
    context,
    graph: CampusLocationGraph,
    templates: Mapping[str, Mapping[str, Any]],
    policy: CampusNightWorldPolicy,
    social_consequences: Mapping[str, Mapping[str, Any]],
) -> Dict[str, int]:
    """Publish, populate, browse, and claim the restricted forum each phase."""
    summary = {
        "night_task_published_count": 0,
        "night_task_expired_count": _expire_previous_night(context),
        "night_npc_enter_count": 0,
        "night_task_view_count": 0,
        "night_npc_claim_count": 0,
    }
    published = _publish_night_tasks(context, templates, policy, social_consequences)
    summary["night_task_published_count"] = len(published)
    entered = _enter_autonomous_npcs(context, policy)
    summary["night_npc_enter_count"] = len(entered)
    summary.update(_assign_night_tasks(context, graph, policy))
    return summary


def campus_night_task_invariant(state: WorldState) -> Iterable[str]:
    errors: list[str] = []
    aggregate = state.situations.get("night_world", {})
    actor_states = aggregate.get("actor_states", {})
    for task_id, task in state.tasks.items():
        if not isinstance(task, dict) or task.get("forum") != "night":
            continue
        if task.get("world_layer") != "night":
            errors.append(f"night task {task_id} has an invalid world layer")
        assignee_id = task.get("assignee_id")
        if task.get("state") in ACTIVE_STATES:
            if assignee_id not in state.population:
                errors.append(f"night task {task_id} has no valid assignee")
            elif actor_states.get(assignee_id, {}).get("layer") != "night":
                errors.append(f"night task {task_id} is assigned outside the night layer")
        if any(phase not in {"evening", "late_night"} for phase in task.get("allowed_phases", ())):
            errors.append(f"night task {task_id} allows a daylight phase")
    return errors


__all__ = [
    "advance_campus_night_forum",
    "campus_night_task_invariant",
    "load_night_task_templates",
]
