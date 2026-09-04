"""Authoritative club membership, activity, resources, promotion, and tactics."""
from __future__ import annotations

import hashlib
from copy import deepcopy
from typing import Any, Dict, Iterable, Mapping, Sequence

from simulation.domain.clubs import CLUB_RANKS, CampusClubPolicy, parse_club_policy
from simulation.domain.world_state import WorldState
from simulation.systems.content_registry import ContentRegistry
from simulation.systems.campus_social import adjust_relationship, relationship_between
from simulation.systems.transactions import TransactionOutcome


CLUB_ACTIVITY_IDS = {"CLUB_OR_PERSONAL_ACTIVITY", "CLUB_OR_SELF_STUDY", "CLUB_ACTIVITY"}


def load_campus_club_policy(registry: ContentRegistry) -> CampusClubPolicy:
    return parse_club_policy(registry.document("organizations/clubs.json"))


def _leadership_score(actor_id: str, actor: Mapping[str, Any], club_id: str) -> tuple[int, str]:
    personality = actor.get("personality", {})
    attributes = actor.get("attributes", {})
    score = (
        int(personality.get("conscientiousness", 50))
        + int(personality.get("extraversion", 50)) // 2
        + int(attributes.get("expression", 5)) * 5
    )
    digest = hashlib.sha256(f"{club_id}:{actor_id}".encode("utf-8")).hexdigest()
    return score, digest


def install_campus_clubs(
    state: WorldState,
    clubs: Mapping[str, Mapping[str, Any]],
    policy: CampusClubPolicy,
) -> None:
    """Upgrade the social organization skeleton into the club authority ledger."""
    if not state.organizations:
        raise ValueError("campus social state must be installed before club runtime")
    if "campus_clubs" in state.metadata:
        raise ValueError("campus club runtime is already installed")
    for club_id, definition in sorted(clubs.items()):
        organization = state.organizations.get(club_id)
        if not isinstance(organization, dict):
            raise ValueError(f"missing social organization for club {club_id}")
        members = list(organization.get("member_ids", ()))
        ranked = sorted(
            members,
            key=lambda actor_id: _leadership_score(
                actor_id, state.population.get(actor_id, {}), club_id
            ),
            reverse=True,
        )
        leader_id = ranked[0] if ranked else ""
        # Leave one core-member seat open so contribution-based promotion can
        # happen during the demo instead of being permanently blocked at boot.
        initial_core_count = max(1, policy.core_member_limit - 1)
        core_ids = set(ranked[1:1 + initial_core_count])
        memberships: Dict[str, Dict[str, Any]] = {}
        for actor_id in sorted(members):
            rank = "leader" if actor_id == leader_id else "core_member" if actor_id in core_ids else "member"
            contribution = int(policy.rank_thresholds[rank])
            memberships[actor_id] = {
                "actor_id": actor_id,
                "rank": rank,
                "contribution": contribution,
                "attendance_count": 0,
                "absence_count": 0,
                "joined_day": 1,
                "last_attendance_marker": "",
                "promotion_history": [],
            }
        organization.update({
            "category": str(definition.get("category", "")),
            "surface_skill": str(definition.get("surface_skill", "")),
            "night_skill": str(definition.get("night_skill", "")),
            "signature_resource": str(definition.get("signature_resource", "")),
            "college_overlap_ids": list(definition.get("college_overlap_ids", ())),
            "activity_slots": deepcopy(definition.get("activity_slots", ())),
            "memberships": memberships,
            "leader_id": leader_id,
            "resources": {
                "resource_id": str(definition.get("signature_resource", "")),
                "current": policy.initial_resource,
                "capacity": policy.resource_capacity,
                "earned_total": 0,
                "spent_total": 0,
            },
            "activity_count": 0,
            "last_upkeep_day": 0,
            "history": [],
            "team_tactic": {
                "tactic_id": str(definition.get("night_skill", "")),
                "name": str(definition.get("night_skill_name", definition.get("night_skill", ""))),
                "resource_cost": policy.tactic_resource_cost,
                "minimum_participants": 2,
                "required_rank": "core_member",
            },
        })
    state.metadata["campus_clubs"] = {
        "policy": policy.to_dict(),
        "last_upkeep_marker": "",
    }


def _membership(state: WorldState, club_id: str, actor_id: str) -> Dict[str, Any] | None:
    club = state.organizations.get(club_id)
    if not isinstance(club, dict):
        return None
    membership = club.get("memberships", {}).get(actor_id)
    return membership if isinstance(membership, dict) else None


def club_has_activity(state: WorldState, club_id: str, day: int, phase: str) -> bool:
    club = state.organizations.get(club_id)
    if not isinstance(club, dict):
        return False
    weekday = (day - 1) % 7
    return any(
        isinstance(slot, dict)
        and slot.get("phase") == phase
        and weekday in slot.get("days", ())
        for slot in club.get("activity_slots", ())
    )


def validate_club_activity(context, command, definition) -> TransactionOutcome | None:
    """Validate an explicitly selected club before generic activity effects run."""
    if definition.activity_id not in CLUB_ACTIVITY_IDS and definition.category != "club":
        return None
    club_id = str(command.parameters.get("club_id", ""))
    if not club_id:
        return None
    if club_id not in context.state.organizations:
        return TransactionOutcome(False, False, "unknown_club", "社团不存在。")
    if _membership(context.state, club_id, command.actor_id) is None:
        return TransactionOutcome(False, False, "not_a_member", "当前不是该社团成员。")
    if not club_has_activity(
        context.state, club_id, context.state.clock.day, context.state.clock.phase
    ):
        return TransactionOutcome(False, False, "club_activity_not_scheduled", "该社团当前没有安排活动。")
    return None


def _append_history(club: Dict[str, Any], state: WorldState, event: str, **payload: Any) -> None:
    club.setdefault("history", []).append({
        "day": state.clock.day,
        "phase": state.clock.phase,
        "event": event,
        **payload,
    })


def _promote_if_eligible(
    context,
    club_id: str,
    actor_id: str,
    policy: CampusClubPolicy,
) -> Dict[str, Any] | None:
    club = context.state.organizations[club_id]
    membership = club["memberships"][actor_id]
    if membership["rank"] != "member":
        return None
    core_count = sum(
        1 for record in club["memberships"].values()
        if record.get("rank") == "core_member"
    )
    leader_id = str(club.get("leader_id", ""))
    leader_relation = relationship_between(context.state, leader_id, actor_id)
    event_ready = (
        int(club.get("completed_tasks_by_actor", {}).get(actor_id, 0)) >= 1
        or int(membership["attendance_count"]) >= 4
    )
    if (
        int(membership["contribution"]) < int(policy.rank_thresholds["core_member"])
        or int(membership["attendance_count"]) < 3
        or int(leader_relation.get("trust", 0)) < 52
        or int(leader_relation.get("suspicion", 0)) > 30
        or not event_ready
        or core_count >= policy.core_member_limit
    ):
        return None
    previous = membership["rank"]
    membership["rank"] = "core_member"
    record = {
        "day": context.state.clock.day,
        "phase": context.state.clock.phase,
        "from_rank": previous,
        "to_rank": "core_member",
    }
    membership["promotion_history"].append(record)
    _append_history(club, context.state, "promotion", actor_id=actor_id, **record)
    context.emit(
        "CLUB_MEMBER_PROMOTED",
        f"{context.state.population[actor_id].get('display_name', actor_id)} 晋升为 {club['name']} 骨干。",
        actor_ids=[actor_id],
        payload={"club_id": club_id, "club_name": club["name"], **record},
        visibility="public",
        severity=3,
        knowledge_tags=["club", "organization", "promotion"],
    )
    return record


def settle_club_activity(
    context,
    command,
    definition,
    policy: CampusClubPolicy,
) -> Dict[str, Any]:
    if definition.activity_id not in CLUB_ACTIVITY_IDS and definition.category != "club":
        return {}
    actor = context.state.population.get(command.actor_id, {})
    club_ids = [
        club_id for club_id in actor.get("club_ids", ())
        if _membership(context.state, club_id, command.actor_id) is not None
        and club_has_activity(
            context.state, club_id, context.state.clock.day, context.state.clock.phase
        )
    ]
    requested = str(command.parameters.get("club_id", ""))
    if requested:
        if requested not in club_ids:
            raise ValueError(f"actor {command.actor_id} is not a member of {requested}")
        club_id = requested
    elif club_ids:
        digest = hashlib.sha256(
            f"{context.state.master_seed}:club-attendance:{context.state.clock.day}:{context.state.clock.phase}:{command.actor_id}".encode("utf-8")
        ).digest()
        club_id = sorted(club_ids)[int.from_bytes(digest[:2], "big") % len(club_ids)]
    else:
        return {"club_activity": False, "reason": "no_membership"}
    membership = _membership(context.state, club_id, command.actor_id)
    assert membership is not None
    marker = f"{context.state.clock.day}:{context.state.clock.phase}"
    if membership.get("last_attendance_marker") == marker:
        return {"club_activity": False, "reason": "already_attended", "club_id": club_id}
    club = context.state.organizations[club_id]
    personality = actor.get("personality", {})
    bonus = min(2, int(personality.get("conscientiousness", 50)) // 35)
    overlap_bonus = 1 if actor.get("college_id") in club.get("college_overlap_ids", ()) else 0
    contribution_gain = policy.activity_contribution + bonus + overlap_bonus
    membership["attendance_count"] = int(membership.get("attendance_count", 0)) + 1
    membership["contribution"] = int(membership.get("contribution", 0)) + contribution_gain
    membership["last_attendance_marker"] = marker
    leader_id = str(club.get("leader_id", ""))
    relationship_change: Dict[str, int] = {}
    if leader_id and leader_id != command.actor_id:
        relationship_change = adjust_relationship(
            context.state,
            leader_id,
            command.actor_id,
            {"familiarity": 1, "trust": 1, "respect": 1 if overlap_bonus else 0},
        )
    resources = club["resources"]
    before_resource = int(resources["current"])
    after_resource = min(int(resources["capacity"]), before_resource + policy.activity_resource_gain)
    resources["current"] = after_resource
    resources["earned_total"] = int(resources.get("earned_total", 0)) + after_resource - before_resource
    club["activity_count"] = int(club.get("activity_count", 0)) + 1
    _append_history(
        club, context.state, "activity", actor_id=command.actor_id,
        contribution_gain=contribution_gain, resource_gain=after_resource - before_resource,
    )
    context.emit(
        "CLUB_ACTIVITY_ATTENDED",
        f"{actor.get('display_name', command.actor_id)} 参加了 {club['name']} 的活动。",
        actor_ids=[command.actor_id],
        scene_id=str(actor.get("current_location_id", "")) or None,
        payload={
            "club_id": club_id,
            "club_name": club["name"],
            "activity_id": definition.activity_id,
            "contribution_gain": contribution_gain,
            "contribution": membership["contribution"],
            "resource_gain": after_resource - before_resource,
            "resource": after_resource,
            "rank": membership["rank"],
            "leader_relationship_delta": relationship_change,
        },
        visibility="observable",
        severity=2,
        knowledge_tags=["club", "organization", "attendance"],
    )
    promotion = _promote_if_eligible(context, club_id, command.actor_id, policy)
    return {
        "club_activity": True,
        "club_id": club_id,
        "club_name": club["name"],
        "contribution_gain": contribution_gain,
        "contribution": membership["contribution"],
        "resource_gain": after_resource - before_resource,
        "resource": after_resource,
        "rank": membership["rank"],
        "leader_relationship_delta": relationship_change,
        "promotion": promotion,
    }


def advance_club_upkeep(context, policy: CampusClubPolicy) -> Dict[str, int]:
    """Charge daily shared-resource upkeep once when a new morning starts."""
    summary = {"club_upkeep_count": 0, "club_resource_spent": 0, "club_recruit_count": 0}
    if context.state.clock.phase != "morning":
        return summary
    aggregate = context.state.metadata["campus_clubs"]
    marker = str(context.state.clock.day)
    if aggregate.get("last_upkeep_marker") == marker:
        return summary
    aggregate["last_upkeep_marker"] = marker
    for club_id, club in sorted(context.state.organizations.items()):
        previous_day = context.state.clock.day - 1
        previous_day_had_activity = previous_day >= 1 and any(
            club_has_activity(context.state, club_id, previous_day, phase)
            for phase in ("morning", "afternoon", "evening")
        )
        if previous_day_had_activity:
            for membership in club["memberships"].values():
                if not str(membership.get("last_attendance_marker", "")).startswith(
                    f"{previous_day}:"
                ):
                    membership["absence_count"] = int(membership.get("absence_count", 0)) + 1
        resources = club["resources"]
        before = int(resources["current"])
        spent = min(before, policy.daily_resource_cost)
        resources["current"] = before - spent
        resources["spent_total"] = int(resources.get("spent_total", 0)) + spent
        club["last_upkeep_day"] = context.state.clock.day
        _append_history(club, context.state, "daily_upkeep", resource_spent=spent)
        summary["club_upkeep_count"] += 1
        summary["club_resource_spent"] += spent
    # Every club and student decides independently. There is deliberately no
    # campus-wide daily quota or hard membership cap; repeated memberships make
    # later applications less attractive through commitment pressure instead.
    if context.state.clock.day >= 2:
        for club_id in sorted(context.state.organizations):
            club = context.state.organizations[club_id]
            candidates = []
            for actor_id, actor in context.state.population.items():
                if actor_id == "player" or not isinstance(actor, dict) or actor.get("role_kind") != "student":
                    continue
                admission = _admission_status(context.state, actor_id, club_id, policy)
                if not admission["eligible"]:
                    continue
                digest = hashlib.sha256(
                    f"{context.state.master_seed}:club-recruit:{context.state.clock.day}:{club_id}:{actor_id}".encode("utf-8")
                ).digest()
                daily_impulse = int.from_bytes(digest[:2], "big") % 101
                score = (
                    (35 if admission["college_overlap"] else 0)
                    + int(actor.get("personality", {}).get("openness", 50))
                    + int(actor.get("personality", {}).get("extraversion", 50)) // 2
                    + daily_impulse
                    - len(actor.get("club_ids", ())) * policy.existing_membership_penalty
                    - int(actor.get("needs", {}).get("commitment_pressure", 0)) // 2
                )
                if score < policy.recruitment_score_threshold:
                    continue
                candidates.append((score, actor_id, actor))
            for candidate_score, actor_id, actor in sorted(candidates, reverse=True):
                actor.setdefault("club_ids", []).append(club_id)
                for skill_id in (club["surface_skill"], club["night_skill"]):
                    if skill_id not in actor.setdefault("skill_ids", []):
                        actor["skill_ids"].append(skill_id)
                anchor = f"club:{club_id}"
                if anchor not in actor.setdefault("identity_anchor_ids", []):
                    actor["identity_anchor_ids"].append(anchor)
                club["member_ids"].append(actor_id)
                club["memberships"][actor_id] = {
                    "actor_id": actor_id, "rank": "member", "contribution": 0,
                    "attendance_count": 0, "absence_count": 0,
                    "joined_day": context.state.clock.day, "last_attendance_marker": "",
                    "promotion_history": [],
                }
                _append_history(club, context.state, "autonomous_recruitment", actor_id=actor_id, decision_score=candidate_score)
                context.emit(
                    "CLUB_MEMBER_RECRUITED",
                    f"{actor.get('display_name', actor_id)} 自主加入了 {club['name']}。",
                    actor_ids=[actor_id], payload={"club_id": club_id, "club_name": club["name"], "rank": "member", "decision_score": candidate_score},
                    visibility="public", severity=2, knowledge_tags=["club", "organization", "membership", "autonomous"],
                )
                summary["club_recruit_count"] += 1
            club["member_ids"].sort()
    return summary


def _admission_status(
    state: WorldState,
    actor_id: str,
    club_id: str,
    policy: CampusClubPolicy,
) -> Dict[str, Any]:
    actor = state.population.get(actor_id)
    club = state.organizations.get(club_id)
    if not isinstance(actor, dict) or not isinstance(club, dict):
        return {"eligible": False, "reason": "unknown_actor_or_club"}
    if actor_id in club.get("memberships", {}):
        return {"eligible": False, "reason": "already_member"}
    reputation = int(club.get("reputation_by_actor", {}).get(actor_id, 0))
    completed = int(club.get("completed_tasks_by_actor", {}).get(actor_id, 0))
    overlap = actor.get("college_id") in club.get("college_overlap_ids", ())
    personality = actor.get("personality", {})
    social_fit = (
        int(personality.get("extraversion", 50))
        + int(actor.get("attributes", {}).get("expression", 5)) * 5 >= 95
    )
    eligible = overlap or reputation >= 2 or completed >= 1 or social_fit
    return {
        "eligible": eligible,
        "reason": "eligible" if eligible else "requirements_not_met",
        "college_overlap": overlap,
        "reputation": reputation,
        "completed_tasks": completed,
        "social_fit": social_fit,
    }


def club_catalog_view(state: WorldState, viewer_id: str = "player") -> Dict[str, Any]:
    raw_policy = state.metadata.get("campus_clubs", {}).get("policy", {})
    if not isinstance(raw_policy, dict) or "rank_thresholds" not in raw_policy:
        return {}
    policy = CampusClubPolicy(
        rank_thresholds=raw_policy["rank_thresholds"],
        activity_contribution=int(raw_policy["activity_contribution"]),
        activity_resource_gain=int(raw_policy["activity_resource_gain"]),
        task_contribution=int(raw_policy["task_contribution"]),
        task_resource_gain=int(raw_policy["task_resource_gain"]),
        daily_resource_cost=int(raw_policy["daily_resource_cost"]),
        resource_capacity=int(raw_policy["resource_capacity"]),
        initial_resource=int(raw_policy["initial_resource"]),
        core_member_limit=int(raw_policy["core_member_limit"]),
        tactic_resource_cost=int(raw_policy["tactic_resource_cost"]),
        recruitment_score_threshold=int(raw_policy["recruitment_score_threshold"]),
        existing_membership_penalty=int(raw_policy["existing_membership_penalty"]),
    )
    result: Dict[str, Any] = {}
    for club_id, club in sorted(state.organizations.items()):
        leader_id = str(club.get("leader_id", ""))
        membership = club.get("memberships", {}).get(viewer_id)
        admission = _admission_status(state, viewer_id, club_id, policy)
        tactic = deepcopy(club.get("team_tactic", {}))
        tactic["unlocked_for_viewer"] = bool(
            isinstance(membership, dict)
            and membership.get("rank") in {"core_member", "leader"}
        )
        tactic["resource_ready"] = int(club.get("resources", {}).get("current", 0)) >= int(tactic.get("resource_cost", 0))
        result[club_id] = {
            "organization_id": club_id,
            "name": club.get("name", club_id),
            "category": club.get("category", ""),
            "member_count": len(club.get("member_ids", ())),
            "leader_id": leader_id,
            "leader_name": state.population.get(leader_id, {}).get("display_name", leader_id),
            "resources": deepcopy(club.get("resources", {})),
            "surface_skill": club.get("surface_skill", ""),
            "team_tactic": tactic,
            "viewer_membership": deepcopy(membership) if isinstance(membership, dict) else None,
            "admission": admission,
            "activity_slots": deepcopy(club.get("activity_slots", [])),
            "activity_open_now": club_has_activity(
                state, club_id, state.clock.day, state.clock.phase
            ),
        }
    return result


def make_campus_club_handler(policy: CampusClubPolicy):
    def handle(context, command) -> TransactionOutcome:
        actor = context.state.population.get(command.actor_id)
        club_id = str(command.parameters.get("club_id", ""))
        club = context.state.organizations.get(club_id)
        if not isinstance(actor, dict):
            return TransactionOutcome(False, False, "unknown_actor", "行动者不存在。")
        if not isinstance(club, dict):
            return TransactionOutcome(False, False, "unknown_club", "社团不存在。")
        if command.action_id == "JOIN_CAMPUS_CLUB":
            if actor.get("current_location_id") != "club_room_pool":
                return TransactionOutcome(False, False, "club_wrong_location", "需要先到社团活动室申请入社。")
            if context.state.clock.phase == "late_night":
                return TransactionOutcome(False, False, "club_wrong_phase", "深夜不能办理普通入社手续。")
            admission = _admission_status(context.state, command.actor_id, club_id, policy)
            if not admission["eligible"]:
                return TransactionOutcome(False, False, str(admission["reason"]), "尚未满足该社团的入社条件。", payload=admission)
            actor.setdefault("club_ids", []).append(club_id)
            for skill_id in (club["surface_skill"], club["night_skill"]):
                if skill_id not in actor.setdefault("skill_ids", []):
                    actor["skill_ids"].append(skill_id)
            anchor = f"club:{club_id}"
            if anchor not in actor.setdefault("identity_anchor_ids", []):
                actor["identity_anchor_ids"].append(anchor)
            club["member_ids"].append(command.actor_id)
            club["member_ids"].sort()
            club["memberships"][command.actor_id] = {
                "actor_id": command.actor_id, "rank": "member", "contribution": 0,
                "attendance_count": 0, "absence_count": 0,
                "joined_day": context.state.clock.day, "last_attendance_marker": "",
                "promotion_history": [],
            }
            _append_history(club, context.state, "joined", actor_id=command.actor_id)
            context.emit(
                "CLUB_MEMBER_JOINED", f"{actor.get('display_name', command.actor_id)} 加入了 {club['name']}。",
                actor_ids=[command.actor_id], payload={"club_id": club_id, "club_name": club["name"], "rank": "member"},
                visibility="public", severity=2, knowledge_tags=["club", "organization", "membership"],
            )
            return TransactionOutcome(True, True, "success", "已加入社团。", commit=True, payload={"club_id": club_id, "membership": deepcopy(club["memberships"][command.actor_id])})
        if command.action_id == "LEAVE_CAMPUS_CLUB":
            membership = _membership(context.state, club_id, command.actor_id)
            if membership is None:
                return TransactionOutcome(False, False, "not_a_member", "当前不是该社团成员。")
            if membership["rank"] == "leader":
                return TransactionOutcome(False, False, "leader_must_transfer", "负责人必须先完成职务交接。")
            actor["club_ids"].remove(club_id)
            for skill_id in (club["surface_skill"], club["night_skill"]):
                if skill_id in actor.get("skill_ids", []):
                    actor["skill_ids"].remove(skill_id)
            club["member_ids"].remove(command.actor_id)
            del club["memberships"][command.actor_id]
            _append_history(club, context.state, "left", actor_id=command.actor_id)
            context.emit(
                "CLUB_MEMBER_LEFT", f"{actor.get('display_name', command.actor_id)} 离开了 {club['name']}。",
                actor_ids=[command.actor_id], payload={"club_id": club_id, "club_name": club["name"]},
                visibility="public", severity=2, knowledge_tags=["club", "organization", "membership"],
            )
            return TransactionOutcome(True, True, "success", "已退出社团。", commit=True, payload={"club_id": club_id})
        if command.action_id == "USE_CLUB_TEAM_TACTIC":
            participant_ids = tuple(dict.fromkeys(command.parameters.get("participant_ids", ())))
            if command.actor_id not in participant_ids:
                participant_ids = (command.actor_id, *participant_ids)
            members = [actor_id for actor_id in participant_ids if _membership(context.state, club_id, actor_id)]
            tactic = club["team_tactic"]
            if len(members) < int(tactic["minimum_participants"]):
                return TransactionOutcome(False, False, "insufficient_club_members", "团队战术至少需要两名同社团成员。")
            if not any(_membership(context.state, club_id, actor_id)["rank"] in {"core_member", "leader"} for actor_id in members):
                return TransactionOutcome(False, False, "tactic_rank_locked", "团队中需要至少一名社团骨干或负责人。")
            resources = club["resources"]
            cost = int(tactic["resource_cost"])
            if int(resources["current"]) < cost:
                return TransactionOutcome(False, False, "insufficient_club_resources", "社团公共资源不足。")
            resources["current"] = int(resources["current"]) - cost
            resources["spent_total"] = int(resources.get("spent_total", 0)) + cost
            _append_history(club, context.state, "team_tactic", actor_ids=list(members), resource_spent=cost)
            context.emit(
                "CLUB_TEAM_TACTIC_PREPARED", f"{club['name']} 成员协同发动了 {tactic['name']}。",
                actor_ids=members, payload={"club_id": club_id, "club_name": club["name"], "tactic_id": tactic["tactic_id"], "resource_cost": cost},
                visibility="observable", severity=3, knowledge_tags=["club", "organization", "team_tactic"],
            )
            return TransactionOutcome(True, True, "success", "团队战术已结算。", commit=True, payload={"club_id": club_id, "tactic": deepcopy(tactic), "participant_ids": list(members), "resource_remaining": resources["current"]})
        if command.action_id == "TRANSFER_CLUB_LEADERSHIP":
            current = _membership(context.state, club_id, command.actor_id)
            target_id = str(command.parameters.get("new_leader_id", ""))
            target = _membership(context.state, club_id, target_id)
            if current is None or current.get("rank") != "leader":
                return TransactionOutcome(False, False, "not_club_leader", "只有当前负责人可以交接职务。")
            if target is None or target.get("rank") != "core_member":
                return TransactionOutcome(False, False, "target_not_core_member", "只能把负责人职务交给本社团骨干。")
            current["rank"] = "core_member"
            target["rank"] = "leader"
            club["leader_id"] = target_id
            record = {
                "day": context.state.clock.day, "phase": context.state.clock.phase,
                "from_rank": "core_member", "to_rank": "leader",
            }
            target["promotion_history"].append(record)
            _append_history(club, context.state, "leadership_transfer", previous_leader_id=command.actor_id, leader_id=target_id)
            context.emit(
                "CLUB_LEADERSHIP_TRANSFERRED",
                f"{club['name']} 的负责人由 {actor.get('display_name', command.actor_id)} 交接给 {context.state.population[target_id].get('display_name', target_id)}。",
                actor_ids=[command.actor_id, target_id], payload={"club_id": club_id, "club_name": club["name"], "previous_leader_id": command.actor_id, "leader_id": target_id},
                visibility="public", severity=3, knowledge_tags=["club", "organization", "leadership"],
            )
            return TransactionOutcome(True, True, "success", "负责人职务已交接。", commit=True, payload={"club_id": club_id, "previous_leader_id": command.actor_id, "leader_id": target_id})
        return TransactionOutcome(False, False, "unknown_club_action", "未知社团行动。")
    return handle


def campus_club_invariant(state: WorldState) -> Iterable[str]:
    aggregate = state.metadata.get("campus_clubs")
    if not isinstance(aggregate, dict):
        return ("campus club runtime metadata is missing",)
    errors: list[str] = []
    for club_id, club in state.organizations.items():
        memberships = club.get("memberships")
        members = club.get("member_ids", [])
        if not isinstance(memberships, dict) or set(memberships) != set(members):
            errors.append(f"club {club_id} membership ledger mismatch")
            continue
        leader_ids = [actor_id for actor_id, value in memberships.items() if value.get("rank") == "leader"]
        if len(leader_ids) != 1 or club.get("leader_id") != leader_ids[0]:
            errors.append(f"club {club_id} must have exactly one matching leader")
        for actor_id, membership in memberships.items():
            if membership.get("rank") not in CLUB_RANKS:
                errors.append(f"club {club_id} member {actor_id} has invalid rank")
            for key in ("contribution", "attendance_count", "absence_count", "joined_day"):
                value = membership.get(key)
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    errors.append(f"club {club_id} member {actor_id} has invalid {key}")
        resources = club.get("resources", {})
        current = resources.get("current")
        capacity = resources.get("capacity")
        if any(isinstance(value, bool) or not isinstance(value, int) for value in (current, capacity)) or not 0 <= current <= capacity:
            errors.append(f"club {club_id} resources are invalid")
    return errors


__all__ = [
    "CLUB_ACTIVITY_IDS", "advance_club_upkeep", "campus_club_invariant",
    "club_has_activity",
    "club_catalog_view", "install_campus_clubs", "load_campus_club_policy",
    "make_campus_club_handler", "settle_club_activity", "validate_club_activity",
]
