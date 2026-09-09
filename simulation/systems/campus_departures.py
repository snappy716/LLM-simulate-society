"""Explicit, finite departure appointments; never refund an executed activity."""
from __future__ import annotations

from typing import Any

from simulation.systems.transactions import TransactionOutcome

PHASE_ORDER = ("morning", "afternoon", "evening", "late_night")


def active_departure(state, actor_id: str) -> dict:
    for party in state.parties.values():
        record = party.get("members", {}).get(actor_id, {}).get("departure", {})
        if record.get("day") == state.clock.day and record.get("phase") == state.clock.phase:
            return record
    return {}


def has_upcoming_departure(state, actor_id: str) -> bool:
    """Do not add a new exclusive task commitment across a promised departure."""
    now = (state.clock.day, PHASE_ORDER.index(state.clock.phase))
    for party in state.parties.values():
        record = party.get("members", {}).get(actor_id, {}).get("departure", {})
        if record and (record["day"], PHASE_ORDER.index(record["phase"])) >= now:
            return True
    return False


def assess_departure(state, party, day: Any, phase: Any, policy) -> dict:
    from simulation.systems.campus_parties import invitation_assessment

    if type(day) is not int or day < 1 or phase not in ("evening", "late_night"):
        return {"allowed": False, "code": "invalid_departure_slot", "blocked": []}
    if (day, PHASE_ORDER.index(phase)) < (state.clock.day, PHASE_ORDER.index(state.clock.phase)):
        return {"allowed": False, "code": "departure_in_past", "blocked": []}
    blocked = []
    for actor_id in party["member_ids"]:
        actor = state.population[actor_id]
        reason = ""
        current = day == state.clock.day and phase == state.clock.phase
        budget = state.action_economy.get("actors", {}).get(actor_id, {})
        from simulation.systems.campus_commitments import commitments_at
        own_party_id = party.get("party_id")
        if commitments_at(state, actor_id, day, phase, ignore=("departure", own_party_id)):
            reason = "appointment_commitment"
        if current and not budget.get("night_combat_paid", False) and int(budget.get("major_remaining", 0)) < 1:
            reason = "major_action_exhausted"
        if actor_id != party["leader_id"]:
            slot = actor.get("weekly_schedule", {}).get(str((day - 1) % 7), {}).get(phase, {})
            if int(slot.get("priority", 0)) >= 90:
                reason = "protected_schedule"
            if actor.get("active_forum_task_id"):
                reason = "task_commitment"
            if not invitation_assessment(state, party["leader_id"], actor_id, policy).get("accepted"):
                reason = "insufficient_willingness"
        if reason:
            blocked.append({"actor_id": actor_id, "reason": reason})
    return {"allowed": not blocked, "code": "departure_conflict" if blocked else "success",
            "day": day, "phase": phase, "blocked": blocked}


def handle_departure(context, command, party, policy):
    if command.actor_id != party["leader_id"]:
        return TransactionOutcome(False, False, "not_party_leader", "只有队长可以安排出击。")
    cancel = command.action_id == "CANCEL_PARTY_DEPARTURE"
    assessment = {} if cancel else assess_departure(
        context.state, party, command.parameters.get("day"), command.parameters.get("phase"), policy
    )
    if not cancel and not assessment["allowed"]:
        names = "、".join(context.state.population[item["actor_id"]].get("display_name", item["actor_id"])
                         for item in assessment["blocked"])
        return TransactionOutcome(False, False, assessment["code"],
                                  "无法预约：" + (names + "存在已确认约定、日程、任务、行动余额或意愿冲突。" if names else "请选当前或未来的晚间/深夜。"),
                                  payload=assessment)
    for member in party["members"].values():
        if cancel:
            member.pop("departure", None)
        else:
            member["departure"] = {"day": assessment["day"], "phase": assessment["phase"]}
    party["revision"] += 1
    event = "PARTY_DEPARTURE_CANCELLED" if cancel else "PARTY_DEPARTURE_RESERVED"
    message = "已取消预约；不会返还已消耗的行动。" if cancel else "全队同意预约，届时预留行动，首次开战才扣除。"
    context.emit(event, message, actor_ids=list(party["member_ids"]), payload=assessment,
                 visibility="private", severity=2, knowledge_tags=["party", "schedule", "commitment"])
    return TransactionOutcome(True, True, "success", message, commit=True, payload=assessment)
