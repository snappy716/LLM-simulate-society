"""Persistent invitation, commitment, stability, and party cooperation runtime."""
from __future__ import annotations

from copy import deepcopy
from itertools import combinations
from typing import Any, Dict, Iterable, Mapping

from simulation.domain.parties import CampusPartyPolicy, parse_party_policy
from simulation.domain.world_state import WorldState
from simulation.systems.campus_social import DEFAULT_RELATIONSHIP, adjust_relationship
from simulation.systems.content_registry import ContentRegistry
from simulation.systems.transactions import TransactionOutcome


PARTY_ACTION_IDS = {
    "INVITE_PARTY_MEMBER", "DISMISS_PARTY_MEMBER", "LEAVE_PARTY", "DISBAND_PARTY",
}


def load_campus_party_policy(registry: ContentRegistry) -> CampusPartyPolicy:
    return parse_party_policy(registry.get("configuration", "party_policy"))


def party_policy_from_state(state: WorldState) -> CampusPartyPolicy:
    raw = state.metadata.get("campus_parties", {}).get("policy")
    if not isinstance(raw, dict):
        raise ValueError("campus party policy is not installed")
    return parse_party_policy(raw)


def create_party(
    state: WorldState,
    leader_id: str,
    policy: CampusPartyPolicy,
    *,
    purpose_id: str = "night_investigation",
) -> Dict[str, Any]:
    if leader_id not in state.population:
        raise ValueError(f"unknown party leader: {leader_id}")
    if party_for_actor(state, leader_id) is not None:
        raise ValueError(f"party leader already belongs to a party: {leader_id}")
    party_id = f"party:{leader_id}"
    party = {
        "party_id": party_id,
        "leader_id": leader_id,
        "purpose_id": purpose_id,
        "max_members": policy.max_members,
        "member_ids": [leader_id],
        "members": {
            leader_id: {
                "actor_id": leader_id,
                "status": "leader",
                "joined_day": state.clock.day,
                "joined_phase": state.clock.phase,
                "commitment_until_day": state.clock.day,
                "invitation_score": 100,
                "last_review_day": state.clock.day,
            },
        },
        "revision": 1,
        "history": [],
    }
    state.parties[party_id] = party
    return party


def install_campus_parties(state: WorldState, policy: CampusPartyPolicy) -> None:
    if state.parties:
        raise ValueError("campus parties are already initialized")
    if "player" not in state.population:
        raise ValueError("player must exist before party runtime installation")
    create_party(state, "player", policy)
    state.metadata["campus_parties"] = {
        "policy": policy.to_dict(),
        "last_review_marker": "",
    }


def party_for_actor(state: WorldState, actor_id: str) -> Dict[str, Any] | None:
    for party in state.parties.values():
        if isinstance(party, dict) and actor_id in party.get("member_ids", ()):
            return party
    return None


def _read_relationship(state: WorldState, owner_id: str, target_id: str) -> Dict[str, int]:
    relation = state.relationships.get(owner_id, {}).get(target_id)
    return relation if isinstance(relation, dict) else DEFAULT_RELATIONSHIP


def invitation_assessment(
    state: WorldState,
    leader_id: str,
    target_id: str,
    policy: CampusPartyPolicy,
) -> Dict[str, Any]:
    leader = state.population.get(leader_id)
    target = state.population.get(target_id)
    if not isinstance(leader, dict) or not isinstance(target, dict) or leader_id == target_id:
        return {"eligible": False, "accepted": False, "score": -1000, "reason": "invalid_target"}
    access = str(target.get("night_access", "unaware"))
    access_modifier = int(policy.night_access_modifiers.get(access, -1000))
    if access_modifier <= -1000:
        return {
            "eligible": False, "accepted": False, "score": -1000,
            "reason": "night_access_unavailable",
        }
    relation = _read_relationship(state, target_id, leader_id)
    personality = target.get("personality", {})
    needs = target.get("needs", {})
    shared_clubs = sorted(set(leader.get("club_ids", ())) & set(target.get("club_ids", ())))
    same_college = bool(
        leader.get("college_id") and leader.get("college_id") == target.get("college_id")
    )
    factors = {
        "base": 20,
        "night_readiness": access_modifier,
        "trust": (int(relation.get("trust", 50)) - 50) // 2,
        "closeness": int(relation.get("closeness", 0)) // 4,
        "respect": int(relation.get("respect", 0)) // 5,
        "obligation": int(relation.get("obligation", 0)) // 5,
        "suspicion": -int(relation.get("suspicion", 0)) // 3,
        "fear": -int(relation.get("fear", 0)) // 4,
        "conflict": -int(relation.get("conflict", 0)) // 3,
        "risk_tolerance": (int(personality.get("risk_tolerance", 50)) - 50) // 4,
        "altruism": (int(personality.get("altruism", 50)) - 50) // 6,
        "commitment_pressure": -int(needs.get("commitment_pressure", 0)) // 5,
        "safety_pressure": -int(needs.get("safety", 0)) // 8,
        "fatigue": -int(needs.get("rest", 0)) // 10,
        "same_college": policy.same_college_bonus if same_college else 0,
        "shared_clubs": policy.shared_club_bonus * min(2, len(shared_clubs)),
    }
    score = sum(factors.values())
    return {
        "eligible": True,
        "accepted": score >= policy.invitation_score_threshold,
        "score": score,
        "threshold": policy.invitation_score_threshold,
        "reason": "accepted" if score >= policy.invitation_score_threshold else "insufficient_willingness",
        "shared_club_ids": shared_clubs,
        "same_college": same_college,
        "factors": factors,
    }


def _skill_is_active(state: WorldState, source_id: str, member_ids: Iterable[str]) -> bool:
    for other_id in member_ids:
        if other_id == source_id:
            continue
        relation = _read_relationship(state, source_id, other_id)
        if int(relation.get("trust", 50)) < 45 or int(relation.get("conflict", 0)) > 40:
            return False
    return True


def party_stability(
    state: WorldState,
    party: Mapping[str, Any],
    policy: CampusPartyPolicy,
) -> Dict[str, Any]:
    member_ids = [actor_id for actor_id in party.get("member_ids", ()) if actor_id in state.population]
    pair_scores: list[int] = []
    for left_id, right_id in combinations(member_ids, 2):
        directional = []
        for owner_id, target_id in ((left_id, right_id), (right_id, left_id)):
            relation = _read_relationship(state, owner_id, target_id)
            directional.append(
                50
                + (int(relation.get("trust", 50)) - 50) // 2
                + int(relation.get("closeness", 0)) // 5
                + int(relation.get("respect", 0)) // 6
                - int(relation.get("suspicion", 0)) // 3
                - int(relation.get("fear", 0)) // 5
                - int(relation.get("conflict", 0)) // 3
            )
        pair_scores.append(sum(directional) // len(directional))
    base = sum(pair_scores) // len(pair_scores) if pair_scores else 55
    pressures = [
        int(state.population[actor_id].get("needs", {}).get("commitment_pressure", 0))
        for actor_id in member_ids
    ]
    pressure_penalty = (sum(pressures) // len(pressures)) // 8 if pressures else 0
    skills: list[Dict[str, Any]] = []
    skill_bonus = 0
    for actor_id in member_ids:
        actor = state.population[actor_id]
        for skill_id in actor.get("relationship_skill_ids", ()):
            definition = policy.relationship_skills.get(skill_id)
            if not isinstance(definition, Mapping):
                continue
            active = _skill_is_active(state, actor_id, member_ids)
            bonus = int(definition.get("stability_bonus", 0)) if active else 0
            skill_bonus += bonus
            skills.append({
                "skill_id": skill_id,
                "name": str(definition.get("name", skill_id)),
                "description": str(definition.get("description", "")),
                "source_actor_id": actor_id,
                "source_name": actor.get("display_name", actor_id),
                "active": active,
                "stability_bonus": bonus,
                "battle_effect": deepcopy(definition.get("battle_effect", {})),
            })
    score = max(0, min(100, base - pressure_penalty + min(18, skill_bonus)))
    band = "fragile" if score < 35 else "uncertain" if score < 55 else "steady" if score < 75 else "cohesive"
    return {
        "score": score,
        "band": band,
        "pair_count": len(pair_scores),
        "pressure_penalty": pressure_penalty,
        "relationship_skill_bonus": min(18, skill_bonus),
        "active_collaboration_skills": skills,
    }


def _public_assessment(assessment: Mapping[str, Any]) -> Dict[str, Any]:
    if not assessment.get("eligible"):
        return {"can_invite": False, "expected_response": "unavailable", "reason": assessment.get("reason")}
    score = int(assessment.get("score", 0))
    threshold = int(assessment.get("threshold", 0))
    expected = "likely_accept" if score >= threshold else "uncertain" if score >= threshold - 10 else "likely_decline"
    return {
        "can_invite": True,
        "expected_response": expected,
        "reason": "available",
        "shared_club_ids": list(assessment.get("shared_club_ids", ())),
        "same_college": bool(assessment.get("same_college", False)),
    }


def party_view(state: WorldState, viewer_id: str, policy: CampusPartyPolicy) -> Dict[str, Any]:
    party = party_for_actor(state, viewer_id)
    if party is None:
        return {}
    leader_id = str(party["leader_id"])
    members = []
    for actor_id in party["member_ids"]:
        actor = state.population[actor_id]
        assessment = invitation_assessment(state, leader_id, actor_id, policy) if actor_id != leader_id else None
        members.append({
            **deepcopy(party["members"][actor_id]),
            "display_name": actor.get("display_name", actor_id),
            "college_id": actor.get("college_id"),
            "occupation_id": actor.get("occupation_id", ""),
            "relationship_skill_ids": list(actor.get("relationship_skill_ids", ())),
            "current_willingness": 100 if assessment is None else int(assessment["score"]),
            "battle_ready": actor_id == leader_id or bool(
                assessment
                and assessment.get("eligible")
                and int(assessment.get("score", -1000)) >= policy.withdrawal_score_threshold
            ),
        })
    full = len(party["member_ids"]) >= int(party["max_members"])
    candidates = []
    for actor_id, actor in sorted(state.population.items()):
        if actor_id == viewer_id or not isinstance(actor, dict) or party_for_actor(state, actor_id) is not None:
            continue
        assessment = invitation_assessment(state, leader_id, actor_id, policy)
        public = _public_assessment(assessment)
        candidates.append({
            "actor_id": actor_id,
            "display_name": actor.get("display_name", actor_id),
            "college_id": actor.get("college_id"),
            "occupation_id": actor.get("occupation_id", ""),
            **public,
            "can_invite": bool(public["can_invite"] and not full and viewer_id == leader_id),
        })
    candidates.sort(key=lambda item: (
        {"likely_accept": 0, "uncertain": 1, "likely_decline": 2, "unavailable": 3}.get(item["expected_response"], 4),
        item["display_name"], item["actor_id"],
    ))
    return {
        "party_id": party["party_id"],
        "leader_id": leader_id,
        "purpose_id": party["purpose_id"],
        "revision": party["revision"],
        "member_count": len(party["member_ids"]),
        "max_members": party["max_members"],
        "is_full": full,
        "members": members,
        "stability": party_stability(state, party, policy),
        "candidates": candidates,
        "recent_history": deepcopy(party.get("history", [])[-12:]),
    }


def _append_history(party: Dict[str, Any], state: WorldState, event: str, **payload: Any) -> None:
    party.setdefault("history", []).append({
        "day": state.clock.day,
        "phase": state.clock.phase,
        "event": event,
        **payload,
    })


def _invited_today(party: Mapping[str, Any], state: WorldState, target_id: str) -> bool:
    return any(
        entry.get("event") == "invitation"
        and entry.get("target_id") == target_id
        and entry.get("day") == state.clock.day
        for entry in party.get("history", ())
        if isinstance(entry, dict)
    )


def make_campus_party_handler(policy: CampusPartyPolicy):
    def handle(context, command) -> TransactionOutcome:
        party = party_for_actor(context.state, command.actor_id)
        if party is None:
            return TransactionOutcome(False, False, "not_in_party", "当前不属于任何队伍。")
        if command.action_id == "INVITE_PARTY_MEMBER":
            if party["leader_id"] != command.actor_id:
                return TransactionOutcome(False, False, "not_party_leader", "只有队长可以邀请成员。")
            target_id = str(command.parameters.get("target_id", ""))
            if target_id not in context.state.population or target_id == command.actor_id:
                return TransactionOutcome(False, False, "invalid_party_target", "邀请对象不存在。")
            if target_id in party["member_ids"]:
                return TransactionOutcome(False, False, "already_party_member", "对方已经在队伍中。")
            if party_for_actor(context.state, target_id) is not None:
                return TransactionOutcome(False, False, "target_in_other_party", "对方已经承诺加入其他队伍。")
            if len(party["member_ids"]) >= int(party["max_members"]):
                return TransactionOutcome(False, False, "party_full", "三人行动小队已经满员。")
            if _invited_today(party, context.state, target_id):
                return TransactionOutcome(False, False, "invitation_cooldown", "今天已经邀请过对方，请给彼此一些时间。")
            assessment = invitation_assessment(context.state, command.actor_id, target_id, policy)
            target = context.state.population[target_id]
            _append_history(
                party, context.state, "invitation", target_id=target_id,
                accepted=bool(assessment["accepted"]), reason=assessment["reason"],
            )
            if not assessment["accepted"]:
                context.emit(
                    "PARTY_INVITATION_DECLINED",
                    f"{target.get('display_name', target_id)} 暂时拒绝了组队邀请。",
                    actor_ids=[command.actor_id], target_ids=[target_id],
                    payload={"party_id": party["party_id"], "reason": assessment["reason"]},
                    visibility="private", severity=2,
                    knowledge_tags=["party", "social", "relationship", "commitment"],
                )
                return TransactionOutcome(
                    True, False, "invitation_declined", "对方暂时不愿作出同行承诺。",
                    commit=True, payload={"target_id": target_id, "assessment": assessment},
                )
            party["member_ids"].append(target_id)
            party["members"][target_id] = {
                "actor_id": target_id,
                "status": "committed",
                "joined_day": context.state.clock.day,
                "joined_phase": context.state.clock.phase,
                "commitment_until_day": context.state.clock.day + policy.minimum_commitment_days,
                "invitation_score": int(assessment["score"]),
                "last_review_day": context.state.clock.day,
            }
            party["revision"] = int(party["revision"]) + 1
            relationship_changes = {
                "target_to_leader": adjust_relationship(
                    context.state, target_id, command.actor_id,
                    {"familiarity": 2, "trust": 1, "obligation": 2},
                ),
                "leader_to_target": adjust_relationship(
                    context.state, command.actor_id, target_id,
                    {"familiarity": 2, "trust": 1},
                ),
            }
            context.emit(
                "PARTY_MEMBER_COMMITTED",
                f"{target.get('display_name', target_id)} 接受邀请并承诺加入行动小队。",
                actor_ids=[command.actor_id], target_ids=[target_id],
                payload={
                    "party_id": party["party_id"], "purpose_id": party["purpose_id"],
                    "commitment_until_day": party["members"][target_id]["commitment_until_day"],
                    "relationship_changes": relationship_changes,
                },
                visibility="private", severity=3,
                knowledge_tags=["party", "social", "relationship", "commitment"],
            )
            return TransactionOutcome(
                True, True, "success", "对方接受邀请并作出了同行承诺。", commit=True,
                payload={
                    "target_id": target_id,
                    "membership": deepcopy(party["members"][target_id]),
                    "assessment": assessment,
                    "relationship_changes": relationship_changes,
                    "stability": party_stability(context.state, party, policy),
                },
            )
        if command.action_id == "DISMISS_PARTY_MEMBER":
            if party["leader_id"] != command.actor_id:
                return TransactionOutcome(False, False, "not_party_leader", "只有队长可以解除成员承诺。")
            target_id = str(command.parameters.get("target_id", ""))
            if target_id == command.actor_id:
                return TransactionOutcome(False, False, "cannot_dismiss_leader", "队长不能把自己移出队伍。")
            if target_id not in party["members"]:
                return TransactionOutcome(False, False, "not_party_member", "对方不在当前队伍中。")
            del party["members"][target_id]
            party["member_ids"].remove(target_id)
            party["revision"] = int(party["revision"]) + 1
            _append_history(party, context.state, "dismissed", target_id=target_id)
            context.emit(
                "PARTY_MEMBER_DISMISSED", "行动小队解除了成员承诺。",
                actor_ids=[command.actor_id], target_ids=[target_id],
                payload={"party_id": party["party_id"]}, visibility="private", severity=2,
                knowledge_tags=["party", "social", "relationship", "commitment"],
            )
            return TransactionOutcome(True, True, "success", "已解除该成员的同行承诺。", commit=True, payload={"target_id": target_id})
        if command.action_id == "LEAVE_PARTY":
            if party["leader_id"] == command.actor_id:
                return TransactionOutcome(False, False, "leader_must_disband", "队长需要解散队伍，不能直接离队。")
            record = party["members"][command.actor_id]
            if context.state.clock.day <= int(record["commitment_until_day"]):
                return TransactionOutcome(False, False, "commitment_active", "当前同行承诺尚未履行完毕。")
            del party["members"][command.actor_id]
            party["member_ids"].remove(command.actor_id)
            party["revision"] = int(party["revision"]) + 1
            _append_history(party, context.state, "left", target_id=command.actor_id)
            context.emit(
                "PARTY_MEMBER_LEFT", "一名成员结束承诺并离开了行动小队。",
                actor_ids=[command.actor_id], target_ids=[party["leader_id"]],
                payload={"party_id": party["party_id"]}, visibility="private", severity=2,
                knowledge_tags=["party", "social", "relationship", "commitment"],
            )
            return TransactionOutcome(True, True, "success", "已离开行动小队。", commit=True)
        if command.action_id == "DISBAND_PARTY":
            if party["leader_id"] != command.actor_id:
                return TransactionOutcome(False, False, "not_party_leader", "只有队长可以解散队伍。")
            former_ids = list(party["member_ids"])
            if command.actor_id == "player":
                party["member_ids"] = ["player"]
                party["members"] = {"player": party["members"]["player"]}
                party["revision"] = int(party["revision"]) + 1
                _append_history(party, context.state, "disbanded", target_ids=former_ids[1:])
            else:
                del context.state.parties[party["party_id"]]
            context.emit(
                "PARTY_DISBANDED", "行动小队已经解散。", actor_ids=former_ids,
                payload={"party_id": party["party_id"]}, visibility="private", severity=2,
                knowledge_tags=["party", "social", "relationship", "commitment"],
            )
            return TransactionOutcome(True, True, "success", "行动小队已经解散。", commit=True)
        return TransactionOutcome(False, False, "unknown_party_action", "未知队伍行动。")
    return handle


def advance_party_commitments(context, policy: CampusPartyPolicy) -> Dict[str, int]:
    summary = {"party_commitment_reviews": 0, "party_withdrawals": 0}
    if context.state.clock.phase != "morning":
        return summary
    metadata = context.state.metadata["campus_parties"]
    marker = str(context.state.clock.day)
    if metadata.get("last_review_marker") == marker:
        return summary
    metadata["last_review_marker"] = marker
    for party in list(context.state.parties.values()):
        leader_id = str(party["leader_id"])
        for actor_id in list(party["member_ids"]):
            if actor_id == leader_id:
                continue
            record = party["members"][actor_id]
            if context.state.clock.day <= int(record["commitment_until_day"]):
                continue
            record["last_review_day"] = context.state.clock.day
            summary["party_commitment_reviews"] += 1
            assessment = invitation_assessment(context.state, leader_id, actor_id, policy)
            if bool(assessment.get("eligible")) and int(assessment.get("score", -1000)) >= policy.withdrawal_score_threshold:
                continue
            party["member_ids"].remove(actor_id)
            del party["members"][actor_id]
            party["revision"] = int(party["revision"]) + 1
            _append_history(party, context.state, "withdrew", target_id=actor_id, reason=assessment.get("reason"))
            actor = context.state.population[actor_id]
            context.emit(
                "PARTY_MEMBER_WITHDREW",
                f"{actor.get('display_name', actor_id)} 重新评估后退出了行动小队。",
                actor_ids=[actor_id], target_ids=[leader_id],
                payload={"party_id": party["party_id"], "reason": assessment.get("reason")},
                visibility="private", severity=3,
                knowledge_tags=["party", "social", "relationship", "commitment"],
            )
            summary["party_withdrawals"] += 1
    return summary


def campus_party_invariant(state: WorldState) -> Iterable[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for party_id, party in state.parties.items():
        if not isinstance(party, dict) or party.get("party_id") != party_id:
            errors.append(f"party {party_id} has an invalid record")
            continue
        member_ids = party.get("member_ids")
        members = party.get("members")
        leader_id = party.get("leader_id")
        if not isinstance(member_ids, list) or not isinstance(members, dict) or set(member_ids) != set(members):
            errors.append(f"party {party_id} member ledger mismatch")
            continue
        if not member_ids or member_ids[0] != leader_id or members.get(leader_id, {}).get("status") != "leader":
            errors.append(f"party {party_id} must begin with its leader")
        if len(member_ids) > int(party.get("max_members", 0)):
            errors.append(f"party {party_id} exceeds its member limit")
        if len(member_ids) != len(set(member_ids)):
            errors.append(f"party {party_id} contains duplicate members")
        for actor_id in member_ids:
            if actor_id not in state.population:
                errors.append(f"party {party_id} references unknown actor {actor_id}")
            if actor_id in seen:
                errors.append(f"actor {actor_id} belongs to multiple parties")
            seen.add(actor_id)
            record = members.get(actor_id, {})
            if record.get("actor_id") != actor_id or record.get("status") not in {"leader", "committed"}:
                errors.append(f"party {party_id} has an invalid membership for {actor_id}")
            for field_name in ("joined_day", "commitment_until_day", "invitation_score", "last_review_day"):
                value = record.get(field_name)
                if isinstance(value, bool) or not isinstance(value, int):
                    errors.append(f"party {party_id} member {actor_id} has invalid {field_name}")
        revision = party.get("revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            errors.append(f"party {party_id} revision is invalid")
    return errors


__all__ = [
    "PARTY_ACTION_IDS", "advance_party_commitments", "campus_party_invariant",
    "create_party", "install_campus_parties", "invitation_assessment",
    "load_campus_party_policy", "make_campus_party_handler", "party_for_actor",
    "party_policy_from_state", "party_stability", "party_view",
]
