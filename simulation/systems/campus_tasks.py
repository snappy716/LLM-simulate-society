"""Authoritative surface-forum tasks shared by players and autonomous NPCs."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

from simulation.actions.commands import SimulationCommand
from simulation.domain.activities import CampusActivityDefinition
from simulation.domain.campus import RELATIONSHIP_NAMES
from simulation.domain.entities import PHASES
from simulation.domain.locations import CampusLocationGraph
from simulation.domain.world_state import WorldState
from simulation.systems.content_registry import ContentRegistry
from simulation.systems.campus_social import apply_task_social_consequence
from simulation.systems.transactions import TransactionOutcome


AVAILABLE_STATES = {"open", "viewed", "considering"}
ACTIVE_STATES = {"locked", "in_progress"}
TERMINAL_STATES = {"completed", "failed", "abandoned", "expired"}
TASK_STATES = AVAILABLE_STATES | ACTIVE_STATES | TERMINAL_STATES


@dataclass(frozen=True)
class CampusForumPolicy:
    daily_surface_task_count: int
    npc_viewers_per_phase_min: int
    npc_viewers_per_phase_max: int
    npc_claim_delay_phases_min: int
    npc_claim_delay_phases_max: int
    npc_execute_delay_phases: int
    protected_schedule_priority: int
    emergent_tasks: Dict[str, Any]
    social_consequences: Dict[str, Dict[str, Any]]

    def __post_init__(self) -> None:
        if self.daily_surface_task_count < 1:
            raise ValueError("daily_surface_task_count must be positive")
        if not 0 <= self.npc_viewers_per_phase_min <= self.npc_viewers_per_phase_max:
            raise ValueError("invalid forum viewer range")
        if not 1 <= self.npc_claim_delay_phases_min <= self.npc_claim_delay_phases_max:
            raise ValueError("invalid NPC claim delay")
        if self.npc_execute_delay_phases < 1:
            raise ValueError("NPC task execution must be delayed by at least one phase")
        if not 0 <= self.protected_schedule_priority <= 100:
            raise ValueError("protected schedule priority must be between 0 and 100")
        max_emergent = self.emergent_tasks.get("max_per_day")
        max_hook = self.emergent_tasks.get("max_hook_per_day")
        cooldown = self.emergent_tasks.get("source_cooldown_days")
        if isinstance(max_emergent, bool) or not isinstance(max_emergent, int) or max_emergent < 0:
            raise ValueError("emergent task daily limit must be a non-negative integer")
        if isinstance(max_hook, bool) or not isinstance(max_hook, int) or not 0 <= max_hook <= max_emergent:
            raise ValueError("emergent hook task limit must fit inside the daily limit")
        if isinstance(cooldown, bool) or not isinstance(cooldown, int) or cooldown < 1:
            raise ValueError("emergent task source cooldown must be positive")
        for need_name, rule in self.emergent_tasks.get("need_rules", {}).items():
            if not isinstance(rule, dict) or not 0 <= int(rule.get("threshold", -1)) <= 100:
                raise ValueError(f"invalid emergent task need rule: {need_name}")
        if not isinstance(self.emergent_tasks.get("hook_rules", {}), dict):
            raise ValueError("emergent task hook rules must be a mapping")
        for outcome in ("completed", "abandoned", "expired"):
            consequence = self.social_consequences.get(outcome)
            if not isinstance(consequence, dict):
                raise ValueError(f"missing social consequence policy: {outcome}")
            relationship = consequence.get("issuer_relationship", {})
            if not isinstance(relationship, dict):
                raise ValueError(f"{outcome} issuer relationship consequence must be a mapping")
            for dimension, delta in relationship.items():
                if dimension not in RELATIONSHIP_NAMES:
                    raise ValueError(f"unsupported relationship consequence: {dimension}")
                if isinstance(delta, bool) or not isinstance(delta, int):
                    raise ValueError(f"relationship consequence {dimension} must be an integer")
            reputation = consequence.get("organization_reputation", 0)
            if isinstance(reputation, bool) or not isinstance(reputation, int):
                raise ValueError("organization reputation consequence must be an integer")


def load_campus_forum_policy(registry: ContentRegistry) -> CampusForumPolicy:
    payload = registry.get("configuration", "forum_policy")
    policy = CampusForumPolicy(
        daily_surface_task_count=int(payload.get("daily_surface_task_count", 0)),
        npc_viewers_per_phase_min=int(payload.get("npc_viewers_per_phase_min", 0)),
        npc_viewers_per_phase_max=int(payload.get("npc_viewers_per_phase_max", 0)),
        npc_claim_delay_phases_min=int(payload.get("npc_claim_delay_phases_min", 0)),
        npc_claim_delay_phases_max=int(payload.get("npc_claim_delay_phases_max", 0)),
        npc_execute_delay_phases=int(payload.get("npc_execute_delay_phases", 0)),
        protected_schedule_priority=int(payload.get("protected_schedule_priority", 90)),
        emergent_tasks=deepcopy(payload.get("emergent_tasks", {})),
        social_consequences=deepcopy(payload.get("social_consequences", {})),
    )
    template_ids = set(registry.ids("surface_task_template"))
    configured_templates = {
        str(rule.get("template_id", ""))
        for group_name in ("need_rules", "hook_rules")
        for rule in policy.emergent_tasks.get(group_name, {}).values()
        if isinstance(rule, dict)
    }
    unknown = configured_templates - template_ids
    if unknown:
        raise ValueError(f"emergent tasks reference unknown templates: {sorted(unknown)}")
    return policy


def load_surface_task_templates(registry: ContentRegistry) -> Dict[str, Dict[str, Any]]:
    templates = registry.all("surface_task_template")
    if not templates:
        raise ValueError("at least one surface task template is required")
    required = {"id", "title", "description", "objective", "activity_id", "scene_id"}
    for template_id, template in templates.items():
        missing = required - set(template)
        if missing:
            raise ValueError(f"surface task {template_id} missing fields: {sorted(missing)}")
        if int(template.get("expires_after_days", 0)) < 1:
            raise ValueError(f"surface task {template_id} must last at least one day")
    return templates


def phase_index(day: int, phase: str) -> int:
    phases = [item.value for item in PHASES]
    return (day - 1) * len(phases) + phases.index(phase)


def _history(day: int, phase: str, kind: str, message: str) -> Dict[str, Any]:
    return {"day": day, "phase": phase, "kind": kind, "message": message}


def _issuer_candidates(state: WorldState, role_kinds: Sequence[str]) -> list[str]:
    allowed = set(role_kinds)
    result = [
        actor_id
        for actor_id, actor in state.population.items()
        if actor_id != "player"
        and isinstance(actor, dict)
        and (not allowed or actor.get("role_kind") in allowed)
    ]
    return sorted(result)


def publish_surface_tasks(
    state: WorldState,
    templates: Mapping[str, Mapping[str, Any]],
    policy: CampusForumPolicy,
    rng,
) -> list[str]:
    forum = state.forums.setdefault("surface", {})
    if int(forum.get("last_published_day", 0)) >= state.clock.day:
        return []
    unlocked = set(forum.get("unlocked_template_ids", ()))
    published_single_run = set(forum.get("published_single_run_template_ids", ()))
    eligible_ids = [
        template_id
        for template_id, template in sorted(templates.items())
        if (not template.get("locked_until_unlocked") or template_id in unlocked)
        and (not template.get("single_run") or template_id not in published_single_run)
    ]
    count = min(policy.daily_surface_task_count, len(eligible_ids))
    pending = [
        template_id
        for template_id in forum.get("pending_follow_up_template_ids", ())
        if template_id in eligible_ids
    ][:count]
    remaining = [template_id for template_id in eligible_ids if template_id not in pending]
    chosen_ids = [*pending, *rng.sample(remaining, count - len(pending))]
    published: list[str] = []
    current_index = phase_index(state.clock.day, state.clock.phase)
    daily_sequence = int(forum.get("published_total", 0))
    for template_id in chosen_ids:
        template = templates[template_id]
        issuers = _issuer_candidates(state, template.get("issuer_role_kinds", ()))
        if not issuers:
            raise ValueError(f"surface task {template_id} has no valid issuer")
        issuer_id = rng.choice(issuers)
        daily_sequence += 1
        task_id = f"surface:d{state.clock.day:02d}:{daily_sequence:04d}:{template_id}"
        claim_delay = rng.randint(
            policy.npc_claim_delay_phases_min,
            policy.npc_claim_delay_phases_max,
        )
        preferred_clubs = list(template.get("preferred_club_ids", ()))
        organization_id = str(template.get("organization_id") or "")
        task = {
            "task_id": task_id,
            "template_id": template_id,
            "forum": "surface",
            "issuer_id": issuer_id,
            "title": str(template["title"]),
            "description": str(template["description"]),
            "objective": str(template["objective"]),
            "action_id": str(template["activity_id"]),
            "activity_id": str(template["activity_id"]),
            "allowed_phases": list(template.get("allowed_phases", ())),
            "scene_id": str(template["scene_id"]),
            "execution_region_id": str(
                state.places[str(template["scene_id"])].get("region_id")
                or template["scene_id"]
            ),
            "created_day": state.clock.day,
            "expires_day": state.clock.day + int(template.get("expires_after_days", 1)) - 1,
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
            "preferred_club_ids": preferred_clubs,
            "organization_id": organization_id or None,
            "social_consequences": deepcopy(
                template.get("social_consequences", policy.social_consequences)
            ),
            "follow_up_template_ids": list(template.get("follow_up_template_ids", ())),
            "chain_parent_template_id": template.get("chain_parent_template_id"),
            "npc_claim_phase_index": current_index + claim_delay,
            "npc_execute_after_phase_index": None,
            "history": [
                _history(state.clock.day, state.clock.phase, "published", "任务已发布到校园互助论坛。")
            ],
        }
        state.tasks[task_id] = task
        published.append(task_id)
        if template.get("single_run"):
            published_single_run.add(template_id)
    forum["pending_follow_up_template_ids"] = [
        template_id
        for template_id in forum.get("pending_follow_up_template_ids", ())
        if template_id not in chosen_ids
    ]
    forum.update({
        "forum_id": "surface",
        "name": "校园互助论坛",
        "enabled": True,
        "last_published_day": state.clock.day,
        "published_total": daily_sequence,
        "published_single_run_template_ids": sorted(published_single_run),
    })
    return published


def install_campus_forums(
    state: WorldState,
    templates: Mapping[str, Mapping[str, Any]],
    policy: CampusForumPolicy,
    rng_pool,
) -> None:
    state.forums = {
        "surface": {
            "forum_id": "surface",
            "name": "校园互助论坛",
            "enabled": True,
            "last_published_day": 0,
            "published_total": 0,
            "completed_template_ids": [],
            "unlocked_template_ids": [],
            "pending_follow_up_template_ids": [],
            "published_single_run_template_ids": [],
            "emergent_last_published_day_by_source": {},
        },
        "night": {
            "forum_id": "night",
            "name": "夜间异常论坛",
            "enabled": False,
            "unlock_hint": "尚未获得访问权限",
        },
    }
    state.tasks = {}
    publish_surface_tasks(state, templates, policy, rng_pool.stream("campus_forum"))


def _emergent_source_is_available(
    state: WorldState,
    source_key: str,
    policy: CampusForumPolicy,
) -> bool:
    forum = state.forums["surface"]
    last_day = forum.get("emergent_last_published_day_by_source", {}).get(source_key)
    if isinstance(last_day, int) and state.clock.day - last_day < int(
        policy.emergent_tasks["source_cooldown_days"]
    ):
        return False
    return not any(
        isinstance(task, dict)
        and task.get("origin_ref_id") == source_key
        and task.get("state") not in TERMINAL_STATES
        for task in state.tasks.values()
    )


def _emergent_candidates(
    state: WorldState,
    policy: CampusForumPolicy,
    rng,
) -> list[Dict[str, Any]]:
    candidates: list[Dict[str, Any]] = []
    need_rules = policy.emergent_tasks.get("need_rules", {})
    for actor_id, actor in sorted(state.population.items()):
        if actor_id == "player" or not isinstance(actor, dict):
            continue
        for need_name, rule in sorted(need_rules.items()):
            value = int(actor.get("needs", {}).get(need_name, 0))
            threshold = int(rule.get("threshold", 101))
            source_key = f"need:{actor_id}:{need_name}"
            if value < threshold or not _emergent_source_is_available(state, source_key, policy):
                continue
            candidates.append({
                "score": value + (8 if actor_id in state.cognition.get("focused_ids", ()) else 0)
                + rng.uniform(-3.0, 3.0),
                "origin_kind": "need",
                "origin_ref_id": source_key,
                "issuer_id": actor_id,
                "preferred_assignee_id": None,
                "need_name": need_name,
                "need_value": value,
                "rule": rule,
                "hook": None,
            })
    hook_rules = policy.emergent_tasks.get("hook_rules", {})
    for hook in state.cognition.get("interactions", {}).get("hooks", ()):
        if not isinstance(hook, dict) or hook.get("state") != "open":
            continue
        rule = hook_rules.get(str(hook.get("hook_type", "")))
        source_key = f"hook:{hook.get('hook_id', '')}"
        if not isinstance(rule, dict) or not _emergent_source_is_available(state, source_key, policy):
            continue
        age = max(
            0,
            phase_index(state.clock.day, state.clock.phase)
            - phase_index(int(hook["created_day"]), str(hook["created_phase"])),
        )
        if age < 1:
            continue
        candidates.append({
            "score": 125 + age + rng.uniform(-2.0, 2.0),
            "origin_kind": "interaction_hook",
            "origin_ref_id": source_key,
            "issuer_id": str(hook["actor_id"]),
            "preferred_assignee_id": str(hook["target_id"]),
            "need_name": None,
            "need_value": None,
            "rule": rule,
            "hook": hook,
        })
    return sorted(
        candidates,
        key=lambda item: (-float(item["score"]), item["origin_ref_id"]),
    )


def publish_emergent_surface_tasks(
    context,
    templates: Mapping[str, Mapping[str, Any]],
    policy: CampusForumPolicy,
) -> list[str]:
    """Turn real NPC pressure and unresolved promises into bounded forum work."""
    if context.state.clock.phase != PHASES[0].value:
        return []
    limit = int(policy.emergent_tasks.get("max_per_day", 0))
    if limit <= 0:
        return []
    rng = context.rng.stream("campus_emergent_tasks")
    forum = context.state.forums["surface"]
    published: list[str] = []
    sequence = int(forum.get("published_total", 0))
    current_index = phase_index(context.state.clock.day, context.state.clock.phase)
    candidates = _emergent_candidates(context.state, policy, rng)
    hook_limit = int(policy.emergent_tasks.get("max_hook_per_day", 0))
    hook_candidates = [item for item in candidates if item["origin_kind"] == "interaction_hook"]
    need_candidates = [item for item in candidates if item["origin_kind"] == "need"]
    selected = [*hook_candidates[:hook_limit], *need_candidates[: max(0, limit - hook_limit)]]
    for candidate in selected[:limit]:
        rule = candidate["rule"]
        template = templates[str(rule["template_id"])]
        issuer_id = str(candidate["issuer_id"])
        issuer = context.state.population[issuer_id]
        issuer_name = str(issuer.get("display_name", issuer_id))
        scene_id = str(template["scene_id"])
        if rule.get("scene_policy") == "issuer_primary":
            scene_id = str(issuer.get("primary_location_id", scene_id))
        sequence += 1
        origin_token = str(candidate["origin_ref_id"]).replace(":", "_")
        task_id = (
            f"surface:d{context.state.clock.day:02d}:{sequence:04d}:"
            f"emergent_{origin_token}"
        )
        organization_id = None
        issuer_clubs = list(issuer.get("club_ids", ()))
        if candidate["origin_kind"] == "interaction_hook" and issuer_clubs:
            target = context.state.population.get(candidate["preferred_assignee_id"], {})
            shared = sorted(set(issuer_clubs) & set(target.get("club_ids", ())))
            organization_id = shared[0] if shared else None
        elif candidate["need_name"] == "commitment_pressure" and issuer_clubs:
            organization_id = issuer_clubs[0]
        claim_delay = rng.randint(
            policy.npc_claim_delay_phases_min,
            policy.npc_claim_delay_phases_max,
        )
        tags = list(dict.fromkeys([*template.get("tags", ()), *rule.get("tags", ())]))
        task = {
            "task_id": task_id,
            "template_id": str(template["id"]),
            "forum": "surface",
            "issuer_id": issuer_id,
            "title": str(rule["title"]),
            "description": str(rule["description"]).format(issuer=issuer_name),
            "objective": str(rule["objective"]),
            "action_id": str(template["activity_id"]),
            "activity_id": str(template["activity_id"]),
            "allowed_phases": list(template.get("allowed_phases", ())),
            "scene_id": scene_id,
            "execution_region_id": str(
                context.state.places[scene_id].get("region_id") or scene_id
            ),
            "created_day": context.state.clock.day,
            "expires_day": context.state.clock.day + int(template.get("expires_after_days", 2)) - 1,
            "state": "open",
            "assignee_id": None,
            "lock_revision": 0,
            "viewer_ids": [],
            "considering_ids": [],
            "helper_ids": [],
            "required_skill_ids": list(template.get("required_skill_ids", ())),
            "required_item_ids": list(template.get("required_item_ids", ())),
            "reward": {"wealth": max(0, int(rule.get("reward_wealth", 0)))},
            "tags": tags,
            "preferred_college_ids": [issuer["college_id"]] if issuer.get("college_id") else [],
            "preferred_club_ids": issuer_clubs,
            "preferred_assignee_id": candidate["preferred_assignee_id"],
            "organization_id": organization_id,
            "social_consequences": deepcopy(policy.social_consequences),
            "follow_up_template_ids": [],
            "chain_parent_template_id": None,
            "npc_claim_phase_index": current_index + claim_delay,
            "npc_execute_after_phase_index": None,
            "origin_kind": candidate["origin_kind"],
            "origin_ref_id": candidate["origin_ref_id"],
            "origin_summary": (
                "由未解决的双方约定产生" if candidate["origin_kind"] == "interaction_hook"
                else f"由发布者的{candidate['need_name']}需求产生"
            ),
            "issuer_need_key": candidate["need_name"],
            "issuer_need_before": candidate["need_value"],
            "issuer_need_delta_on_completion": int(rule.get("issuer_need_delta", 0)),
            "history": [
                _history(
                    context.state.clock.day,
                    context.state.clock.phase,
                    "published",
                    "NPC 根据自己的实际需求或约定发布了任务。",
                )
            ],
        }
        context.state.tasks[task_id] = task
        published.append(task_id)
        forum.setdefault("emergent_last_published_day_by_source", {})[
            candidate["origin_ref_id"]
        ] = context.state.clock.day
        hook = candidate.get("hook")
        if isinstance(hook, dict):
            hook["state"] = "task_posted"
            hook["linked_task_id"] = task_id
        context.emit(
            "FORUM_TASK_PUBLISHED",
            f"{issuer_name}发布了《{task['title']}》。",
            actor_ids=[issuer_id],
            target_ids=[candidate["preferred_assignee_id"]]
            if candidate["preferred_assignee_id"] else [],
            scene_id=scene_id,
            payload={
                "task_id": task_id,
                "forum": "surface",
                "origin_kind": task["origin_kind"],
                "origin_ref_id": task["origin_ref_id"],
            },
            visibility="public",
            severity=2,
            knowledge_tags=["forum", "task", "emergent", task["origin_kind"]],
        )
    forum["published_total"] = sequence
    return published


def _actor_has_active_task(state: WorldState, actor_id: str) -> bool:
    actor = state.population.get(actor_id, {})
    if not isinstance(actor, dict):
        return False
    task_id = actor.get("active_forum_task_id")
    task = state.tasks.get(task_id) if isinstance(task_id, str) else None
    return bool(
        isinstance(task, dict)
        and task.get("assignee_id") == actor_id
        and task.get("state") in ACTIVE_STATES
    )


def _candidate_score(
    state: WorldState,
    graph: CampusLocationGraph,
    task: Mapping[str, Any],
    actor_id: str,
) -> float:
    actor = state.population[actor_id]
    score = 20.0
    if actor.get("college_id") in set(task.get("preferred_college_ids", ())):
        score += 30.0
    if set(actor.get("club_ids", ())) & set(task.get("preferred_club_ids", ())):
        score += 40.0
    if set(task.get("required_skill_ids", ())).issubset(set(actor.get("skill_ids", ()))):
        score += 20.0
    if task.get("preferred_assignee_id") == actor_id:
        score += 45.0
    personality = actor.get("personality", {})
    needs = actor.get("needs", {})
    score += 0.16 * float(personality.get("altruism", 50))
    score += 0.10 * float(personality.get("conscientiousness", 50))
    score += 0.12 * float(needs.get("money", 0))
    route = graph.shortest_route(
        str(actor.get("current_location_id", "")),
        str(task.get("scene_id", "")),
        phase=state.clock.phase,
        access_tags=actor.get("access_tags", ()),
    )
    score -= 50.0 if route is None else min(30.0, route.total_minutes * 0.4)
    return score


def advance_surface_forum(
    context,
    graph: CampusLocationGraph,
    templates: Mapping[str, Mapping[str, Any]],
    policy: CampusForumPolicy,
) -> Dict[str, int]:
    """Publish, expire, browse, and atomically claim tasks at each phase start."""
    rng = context.rng.stream("campus_forum")
    summary = {
        "forum_published_count": 0,
        "forum_emergent_published_count": 0,
        "forum_expired_count": 0,
        "forum_new_view_count": 0,
        "forum_consider_count": 0,
        "forum_npc_claim_count": 0,
    }
    for task_id, task in context.state.tasks.items():
        if (
            isinstance(task, dict)
            and task.get("state") not in TERMINAL_STATES
            and context.state.clock.day > int(task.get("expires_day", 0))
        ):
            assignee_id = task.get("assignee_id")
            assignee = context.state.population.get(assignee_id)
            if isinstance(assignee, dict):
                assignee.pop("active_forum_task_id", None)
                task["social_result"] = apply_task_social_consequence(
                    context.state, str(assignee_id), task, "expired"
                )
            task["state"] = "expired"
            task["lock_revision"] = int(task.get("lock_revision", 0)) + 1
            task.setdefault("history", []).append(
                _history(context.state.clock.day, context.state.clock.phase, "expired", "任务已超过截止日期。")
            )
            _settle_origin_hook(context.state, task, "expired")
            context.emit(
                "FORUM_TASK_EXPIRED",
                f"《{task['title']}》已超过截止日期。",
                actor_ids=[str(assignee_id)] if assignee_id else [],
                target_ids=[task["issuer_id"]],
                scene_id=task["scene_id"],
                payload={
                    "task_id": task_id,
                    "social_result": deepcopy(task.get("social_result", {})),
                },
                knowledge_tags=["forum", "task", "expired"],
            )
            summary["forum_expired_count"] += 1
    if context.state.clock.phase == PHASES[0].value:
        published = publish_surface_tasks(context.state, templates, policy, rng)
        summary["forum_published_count"] = len(published)
        emergent = publish_emergent_surface_tasks(context, templates, policy)
        summary["forum_emergent_published_count"] = len(emergent)

    now = phase_index(context.state.clock.day, context.state.clock.phase)
    npc_ids = [actor_id for actor_id in sorted(context.state.population) if actor_id != "player"]
    for task_id in sorted(context.state.tasks):
        task = context.state.tasks[task_id]
        if not isinstance(task, dict) or task.get("state") not in AVAILABLE_STATES:
            continue
        candidates = [
            actor_id for actor_id in npc_ids
            if not _actor_has_active_task(context.state, actor_id)
            and actor_id != task.get("issuer_id")
        ]
        if not candidates:
            continue
        unseen = [actor_id for actor_id in candidates if actor_id not in task["viewer_ids"]]
        view_count = min(
            len(unseen),
            rng.randint(policy.npc_viewers_per_phase_min, policy.npc_viewers_per_phase_max),
        )
        for actor_id in rng.sample(unseen, view_count):
            task["viewer_ids"].append(actor_id)
            summary["forum_new_view_count"] += 1
        if task["viewer_ids"] and task.get("state") == "open":
            task["state"] = "viewed"

        ranked = sorted(
            (
                (_candidate_score(context.state, graph, task, actor_id), actor_id)
                for actor_id in task["viewer_ids"]
                if actor_id in candidates
            ),
            key=lambda item: (-item[0], item[1]),
        )
        for _, actor_id in ranked[: min(3, len(ranked))]:
            if actor_id not in task["considering_ids"]:
                task["considering_ids"].append(actor_id)
                summary["forum_consider_count"] += 1
        if task["considering_ids"] and task.get("state") in {"open", "viewed"}:
            task["state"] = "considering"

        if now < int(task.get("npc_claim_phase_index", now + 1)):
            continue
        claimant = next(
            (
                actor_id for _, actor_id in ranked
                if actor_id in task["considering_ids"]
                and not _actor_has_active_task(context.state, actor_id)
            ),
            None,
        )
        if claimant is None:
            continue
        task["assignee_id"] = claimant
        task["state"] = "locked"
        task["lock_revision"] = int(task.get("lock_revision", 0)) + 1
        task["npc_execute_after_phase_index"] = now + policy.npc_execute_delay_phases
        assignee = context.state.population[claimant]
        assignee["active_forum_task_id"] = task_id
        task.setdefault("history", []).append(
            _history(
                context.state.clock.day,
                context.state.clock.phase,
                "claimed",
                f"{assignee.get('display_name', claimant)} 接下了任务。",
            )
        )
        summary["forum_npc_claim_count"] += 1
        context.emit(
            "FORUM_TASK_CLAIMED",
            f"{assignee.get('display_name', claimant)} 接下了《{task['title']}》。",
            actor_ids=[claimant],
            target_ids=[task["issuer_id"]],
            scene_id=task["scene_id"],
            payload={"task_id": task_id, "forum": "surface"},
            knowledge_tags=["forum", "task"],
        )
    return summary


def make_task_aware_decision_selector(base_selector, definitions, graph, policy):
    def select(context, actor_id, schedule_plan, occupancy):
        now = phase_index(context.state.clock.day, context.state.clock.phase)
        task_id = context.state.population[actor_id].get("active_forum_task_id")
        task = context.state.tasks.get(task_id) if isinstance(task_id, str) else None
        if not isinstance(task, dict) or task.get("assignee_id") != actor_id or task.get("state") != "locked":
            task = None
        if task is not None:
            definition = definitions.get(task.get("activity_id"))
            execute_after = task.get("npc_execute_after_phase_index")
            route = graph.shortest_route(
                str(context.state.population[actor_id].get("current_location_id", "")),
                str(task.get("scene_id", "")),
                phase=context.state.clock.phase,
                access_tags=context.state.population[actor_id].get("access_tags", ()),
            )
            if (
                definition is not None
                and context.state.clock.phase in definition.allowed_phases
                and isinstance(execute_after, int)
                and now >= execute_after
                and int(schedule_plan.get("priority", 0)) < policy.protected_schedule_priority
                and route is not None
            ):
                return {
                    "activity_id": definition.activity_id,
                    "action_class": definition.action_class,
                    "location_id": task["scene_id"],
                    "priority": 85,
                    "decision_source": "task",
                    "decision_reason": "accepted_forum_task",
                    "reason_codes": ["deadline", "commitment", "reward"],
                    "scheduled_activity_id": schedule_plan.get("activity_id", ""),
                    "scheduled_location_id": schedule_plan.get("location_id", ""),
                    "candidate_count": 1,
                    "score": 100.0,
                    "score_jitter": 0.0,
                    "score_contributions": {"task_commitment": 100.0},
                    "route_minutes": route.total_minutes,
                    "task_id": task["task_id"],
                    "day": context.state.clock.day,
                    "phase": context.state.clock.phase,
                }
        return base_selector(context, actor_id, schedule_plan, occupancy)

    return select


def _apply_reward(state: WorldState, actor_id: str, task: Mapping[str, Any]) -> Dict[str, int]:
    actor = state.population[actor_id]
    reward = task.get("reward", {})
    wealth = max(0, int(reward.get("wealth", 0)))
    if wealth:
        actor["wealth"] = int(actor.get("wealth", 0)) + wealth
    return {"wealth": wealth}


def _apply_issuer_need_result(state: WorldState, task: Mapping[str, Any]) -> Dict[str, Any]:
    need_name = task.get("issuer_need_key")
    delta = int(task.get("issuer_need_delta_on_completion", 0))
    issuer = state.population.get(str(task.get("issuer_id", "")))
    if not isinstance(need_name, str) or not need_name or not isinstance(issuer, dict) or delta == 0:
        return {}
    needs = issuer.setdefault("needs", {})
    before = int(needs.get(need_name, 0))
    after = max(0, min(100, before + delta))
    needs[need_name] = after
    return {
        "issuer_id": task["issuer_id"],
        "need_key": need_name,
        "before": before,
        "after": after,
        "delta": after - before,
    }


def _settle_origin_hook(state: WorldState, task: Mapping[str, Any], outcome: str) -> None:
    if task.get("origin_kind") != "interaction_hook":
        return
    source_key = str(task.get("origin_ref_id", ""))
    hook_id = source_key.removeprefix("hook:")
    for hook in state.cognition.get("interactions", {}).get("hooks", ()):
        if hook.get("hook_id") == hook_id and hook.get("state") == "task_posted":
            hook["state"] = "completed" if outcome == "completed" else "expired"
            hook["resolved_day"] = state.clock.day
            hook["resolved_phase"] = state.clock.phase
            break


def _unlock_follow_up_tasks(state: WorldState, task: Mapping[str, Any]) -> list[str]:
    forum = state.forums.setdefault("surface", {})
    completed = set(forum.get("completed_template_ids", ()))
    completed.add(str(task.get("template_id", "")))
    forum["completed_template_ids"] = sorted(item for item in completed if item)
    unlocked = set(forum.get("unlocked_template_ids", ()))
    pending = list(forum.get("pending_follow_up_template_ids", ()))
    newly_unlocked: list[str] = []
    for template_id in task.get("follow_up_template_ids", ()):
        if template_id not in unlocked:
            unlocked.add(template_id)
            newly_unlocked.append(template_id)
            if template_id not in pending:
                pending.append(template_id)
    forum["unlocked_template_ids"] = sorted(unlocked)
    forum["pending_follow_up_template_ids"] = pending
    return newly_unlocked


def complete_assigned_task(context, actor_id: str, plan: Mapping[str, Any]) -> bool:
    task_id = str(plan.get("task_id", ""))
    task = context.state.tasks.get(task_id)
    if not isinstance(task, dict) or task.get("assignee_id") != actor_id or task.get("state") != "locked":
        return False
    task["state"] = "in_progress"
    task["lock_revision"] = int(task.get("lock_revision", 0)) + 1
    reward = _apply_reward(context.state, actor_id, task)
    issuer_need_result = _apply_issuer_need_result(context.state, task)
    social_result = apply_task_social_consequence(
        context.state, actor_id, task, "completed"
    )
    unlocked_follow_ups = _unlock_follow_up_tasks(context.state, task)
    task["state"] = "completed"
    task["lock_revision"] += 1
    actor = context.state.population[actor_id]
    task.setdefault("history", []).append(
        _history(
            context.state.clock.day,
            context.state.clock.phase,
            "completed",
            f"{actor.get('display_name', actor_id)} 完成了任务。",
        )
    )
    actor.pop("active_forum_task_id", None)
    task["social_result"] = social_result
    task["unlocked_follow_up_template_ids"] = unlocked_follow_ups
    task["issuer_need_result"] = issuer_need_result
    _settle_origin_hook(context.state, task, "completed")
    context.emit(
        "FORUM_TASK_COMPLETED",
        f"{actor.get('display_name', actor_id)} 完成了《{task['title']}》。",
        actor_ids=[actor_id],
        target_ids=[task["issuer_id"]],
        scene_id=task["scene_id"],
        payload={
            "task_id": task_id,
            "reward": reward,
            "social_result": social_result,
            "unlocked_follow_up_template_ids": unlocked_follow_ups,
            "issuer_need_result": issuer_need_result,
            "origin_kind": task.get("origin_kind", "template"),
            "origin_ref_id": task.get("origin_ref_id"),
        },
        knowledge_tags=["forum", "task", "completed"],
    )
    return True


def make_surface_forum_phase_upkeep(graph, templates, policy, base_upkeep):
    def upkeep(context):
        summary = dict(base_upkeep(context)) if base_upkeep is not None else {}
        summary.update(advance_surface_forum(context, graph, templates, policy))
        return summary

    return upkeep


def make_forum_task_handler(activity_handler):
    def handle(context, command: SimulationCommand) -> TransactionOutcome:
        task_id = str(command.parameters.get("task_id", ""))
        task = context.state.tasks.get(task_id)
        if not isinstance(task, dict):
            return TransactionOutcome(False, False, "unknown_task", "论坛任务不存在。")
        action = command.action_id
        actor = context.state.population.get(command.actor_id)
        if not isinstance(actor, dict):
            return TransactionOutcome(False, False, "unknown_actor", "行动者不存在。")

        if action == "VIEW_FORUM_TASK":
            if command.actor_id in task["viewer_ids"]:
                return TransactionOutcome(False, True, "already_viewed", "已经查看过该任务。")
            task["viewer_ids"].append(command.actor_id)
            if task["state"] == "open":
                task["state"] = "viewed"
            context.emit(
                "FORUM_TASK_VIEWED",
                f"{actor.get('display_name', command.actor_id)} 查看了《{task['title']}》。",
                actor_ids=[command.actor_id],
                payload={"task_id": task_id},
                visibility="private",
                knowledge_tags=["forum", "task"],
            )
            return TransactionOutcome(True, True, "success", "已查看任务。", commit=True)

        if action == "CLAIM_FORUM_TASK":
            expected = command.parameters.get("expected_task_revision")
            if isinstance(expected, bool) or not isinstance(expected, int):
                return TransactionOutcome(False, False, "missing_task_revision", "缺少任务版本。")
            if expected != int(task.get("lock_revision", 0)):
                return TransactionOutcome(False, False, "task_revision_conflict", "任务状态刚刚发生了变化。")
            if task.get("state") not in AVAILABLE_STATES or task.get("assignee_id"):
                return TransactionOutcome(False, False, "task_unavailable", "任务已经被别人接下。")
            if _actor_has_active_task(context.state, command.actor_id):
                return TransactionOutcome(False, False, "actor_has_active_task", "请先完成或放弃当前任务。")
            if command.actor_id not in task["viewer_ids"]:
                task["viewer_ids"].append(command.actor_id)
            task["assignee_id"] = command.actor_id
            task["state"] = "locked"
            task["lock_revision"] = expected + 1
            task["npc_execute_after_phase_index"] = None
            actor["active_forum_task_id"] = task_id
            task.setdefault("history", []).append(
                _history(context.state.clock.day, context.state.clock.phase, "claimed", "玩家接下了任务。")
            )
            context.emit(
                "FORUM_TASK_CLAIMED",
                f"玩家接下了《{task['title']}》。",
                actor_ids=[command.actor_id],
                target_ids=[task["issuer_id"]],
                scene_id=task["scene_id"],
                payload={"task_id": task_id, "forum": "surface"},
                knowledge_tags=["forum", "task"],
            )
            return TransactionOutcome(True, True, "success", "任务已锁定给你。", commit=True)

        if action == "ABANDON_FORUM_TASK":
            if task.get("assignee_id") != command.actor_id or task.get("state") not in ACTIVE_STATES:
                return TransactionOutcome(False, False, "task_not_owned", "你没有持有这个任务。")
            task["assignee_id"] = None
            task["state"] = "open" if context.state.clock.day <= int(task["expires_day"]) else "expired"
            task["lock_revision"] = int(task.get("lock_revision", 0)) + 1
            actor.pop("active_forum_task_id", None)
            task["social_result"] = apply_task_social_consequence(
                context.state, command.actor_id, task, "abandoned"
            )
            task.setdefault("history", []).append(
                _history(context.state.clock.day, context.state.clock.phase, "abandoned", "玩家放弃了任务，任务重新开放。")
            )
            context.emit(
                "FORUM_TASK_ABANDONED",
                f"玩家放弃了《{task['title']}》。",
                actor_ids=[command.actor_id],
                target_ids=[task["issuer_id"]],
                scene_id=task["scene_id"],
                payload={
                    "task_id": task_id,
                    "social_result": deepcopy(task.get("social_result", {})),
                },
                knowledge_tags=["forum", "task", "abandoned"],
            )
            return TransactionOutcome(True, True, "success", "任务已放弃。", commit=True)

        if action == "COMPLETE_FORUM_TASK":
            if task.get("assignee_id") != command.actor_id or task.get("state") != "locked":
                return TransactionOutcome(False, False, "task_not_owned", "你没有持有这个任务。")
            current_location = actor.get("current_location_id")
            if current_location not in {
                task.get("scene_id"), task.get("execution_region_id")
            }:
                return TransactionOutcome(False, False, "task_wrong_location", "请先前往任务地点。")
            activity_command = SimulationCommand(
                command_id=f"{command.command_id}:activity",
                actor_id=command.actor_id,
                action_id=str(task["activity_id"]),
                target_ids=command.target_ids,
                parameters={"location_id": current_location, "forum_task_id": task_id},
                expected_world_revision=context.state.revision,
                issued_day=command.issued_day,
                issued_phase=command.issued_phase,
                issued_minute=command.issued_minute,
                source=command.source,
            )
            activity_outcome = activity_handler(context, activity_command)
            if not activity_outcome.success:
                return activity_outcome
            complete_assigned_task(context, command.actor_id, {"task_id": task_id})
            return TransactionOutcome(
                True,
                True,
                "success",
                "任务完成，奖励已经结算。",
                commit=True,
                payload={
                    "task_id": task_id,
                    "reward": dict(task.get("reward", {})),
                    "social_result": deepcopy(task.get("social_result", {})),
                    "unlocked_follow_up_template_ids": list(
                        task.get("unlocked_follow_up_template_ids", ())
                    ),
                    "issuer_need_result": deepcopy(task.get("issuer_need_result", {})),
                },
            )

        return TransactionOutcome(False, False, "unsupported_task_action", "不支持的论坛任务操作。")

    return handle


def make_campus_task_invariant(
    definitions: Mapping[str, CampusActivityDefinition],
):
    def invariant(state: WorldState) -> Iterable[str]:
        errors: list[str] = []
        active_by_actor: Dict[str, int] = {}
        for task_id, task in state.tasks.items():
            if not isinstance(task, dict):
                errors.append(f"task {task_id} must be a mapping")
                continue
            if task.get("task_id") != task_id:
                errors.append(f"task {task_id} id mismatch")
            if task.get("state") not in TASK_STATES:
                errors.append(f"task {task_id} has invalid state")
            if task.get("scene_id") not in state.places:
                errors.append(f"task {task_id} references unknown place")
            if task.get("execution_region_id") not in state.places:
                errors.append(f"task {task_id} references unknown execution region")
            if task.get("activity_id") not in definitions:
                errors.append(f"task {task_id} references unknown activity")
            if task.get("issuer_id") not in state.population:
                errors.append(f"task {task_id} references unknown issuer")
            preferred_assignee = task.get("preferred_assignee_id")
            if preferred_assignee is not None and preferred_assignee not in state.population:
                errors.append(f"task {task_id} references unknown preferred assignee")
            organization_id = task.get("organization_id")
            if organization_id is not None and organization_id not in state.organizations:
                errors.append(f"task {task_id} references unknown organization")
            if int(task.get("expires_day", 0)) < int(task.get("created_day", 1)):
                errors.append(f"task {task_id} has invalid dates")
            revision = task.get("lock_revision")
            if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
                errors.append(f"task {task_id} has invalid lock revision")
            assignee = task.get("assignee_id")
            if task.get("state") in ACTIVE_STATES and assignee not in state.population:
                errors.append(f"task {task_id} active without valid assignee")
            if assignee and task.get("state") in ACTIVE_STATES:
                active_by_actor[assignee] = active_by_actor.get(assignee, 0) + 1
        for actor_id, count in active_by_actor.items():
            if count > 1:
                errors.append(f"actor {actor_id} owns multiple active tasks")
            actor = state.population.get(actor_id, {})
            if isinstance(actor, dict) and actor.get("active_forum_task_id") not in state.tasks:
                errors.append(f"actor {actor_id} references unknown active task")
        for actor_id, actor in state.population.items():
            if not isinstance(actor, dict) or "active_forum_task_id" not in actor:
                continue
            task = state.tasks.get(actor["active_forum_task_id"])
            if not isinstance(task, dict) or task.get("assignee_id") != actor_id or task.get("state") not in ACTIVE_STATES:
                errors.append(f"actor {actor_id} active task pointer is inconsistent")
        return errors

    return invariant


__all__ = [
    "CampusForumPolicy",
    "advance_surface_forum",
    "complete_assigned_task",
    "install_campus_forums",
    "load_campus_forum_policy",
    "load_surface_task_templates",
    "make_campus_task_invariant",
    "make_forum_task_handler",
    "make_surface_forum_phase_upkeep",
    "make_task_aware_decision_selector",
    "phase_index",
    "publish_surface_tasks",
    "publish_emergent_surface_tasks",
]
