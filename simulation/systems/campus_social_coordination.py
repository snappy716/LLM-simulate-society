"""Contact-bound, bilateral confirmation of overnight social intentions.

Confirmation is not consent to the eventual request, nor permission to move a
character or cancel duties. The first slice confirms compatible existing plans.
"""
from simulation.systems.campus_messaging import are_phone_contacts, append_structured_phone_message
from simulation.systems.campus_social import DEFAULT_RELATIONSHIP

PHASE_LABELS = {"morning": "上午", "afternoon": "下午", "evening": "晚上", "late_night": "凌晨"}
REASONS = {
    "compatible": "好，可以到时见面聊聊；具体事情见面再说。",
    "schedule_conflict": "那个时段我另有安排，这次先不约了。",
    "reserved": "那个时段已有见面安排，不再重复约了。",
    "unwilling": "最近不太想约见面，这次先不了。",
    "urgent": "我得先处理手头的要紧事，这次先不约了。",
}


def coordinate_daily_social(context, plans, messaging_policy):
    state = context.state
    previous = state.cognition.get("social_coordination", {})
    if previous.get("day") == state.clock.day:
        return
    records, reserved = {}, set()
    invitations = [(actor_id, social) for actor_id, slots in plans.items()
                   for slot in slots.values() if (social := slot.get("social_intent"))]
    # Rotate deterministic tie-breaking by day, not permanent actor-ID priority.
    invitations.sort(key=lambda pair: pair[0])
    if invitations:
        offset = state.clock.day % len(invitations)
        invitations = invitations[offset:] + invitations[:offset]
    for actor_id, social in invitations:
        target_id, phase = social["target_id"], social["phase"]
        if not are_phone_contacts(state, actor_id, target_id):
            continue  # No invented phone contact; a tentative chance encounter remains.
        target = state.population[target_id]
        relation = {**DEFAULT_RELATIONSHIP, **state.relationships.get(target_id, {}).get(actor_id, {})}
        target_plan = plans[target_id][phase]
        target_social = target_plan.get("social_intent", {})
        if (actor_id, phase) in reserved or (target_id, phase) in reserved:
            reason = "reserved"
        elif target_plan["location_id"] != social["location_id"] or (target_social and target_social["target_id"] != actor_id):
            reason = "schedule_conflict"
        elif target.get("active_forum_task_id") or max(target.get("needs", {}).get(k, 0) for k in ("rest", "food", "safety")) >= 90:
            reason = "urgent"
        elif (relation["trust"] < 35 or relation["conflict"] >= 50 or relation["suspicion"] >= 60
              or (target.get("personality", {}).get("extraversion", 50) < 25
                  and relation["closeness"] < 20 and target.get("needs", {}).get("social", 0) < 50)):
            reason = "unwilling"
        else:
            reason = "compatible"
        status = "confirmed" if reason == "compatible" else "declined"
        if status == "confirmed":
            reserved.update(((actor_id, phase), (target_id, phase)))
        place_name = state.places[social["location_id"]].get("name", "约定地点")
        request = append_structured_phone_message(context, actor_id, target_id,
            f"今天{PHASE_LABELS[phase]}能在{place_name}碰面{social['reason']}吗？",
            messaging_policy, source="social_appointment_request")
        reply = append_structured_phone_message(context, target_id, actor_id, REASONS[reason],
            messaging_policy, source="social_appointment_reply", reply_to_message_id=request["message_id"])
        records[actor_id] = {"target_id": target_id, "phase": phase, "location_id": social["location_id"],
            "status": status, "reason": reason, "request_message_id": request["message_id"],
            "reply_message_id": reply["message_id"]}
        context.emit("NPC_SOCIAL_APPOINTMENT_REPLIED", "见面邀请已确认。" if status == "confirmed" else "见面邀请未达成。",
            actor_ids=[actor_id], target_ids=[target_id], visibility="private", severity=2,
            knowledge_tags=["social", "planning", status], payload={"phase": phase, "status": status,
                "location_id": social["location_id"]})
    if records:
        state.cognition["social_coordination"] = {"day": state.clock.day, "actors": records}


def coordination_for(state, actor_id):
    ledger = state.cognition.get("social_coordination", {})
    return ledger.get("actors", {}).get(actor_id, {}) if ledger.get("day") == state.clock.day else {}


def describe_confirmed_arrangement(state, actor_id, reveal_partner=False):
    ledger = state.cognition.get("social_coordination", {})
    receipts = state.cognition.get("social_agenda_receipts", {})
    if ledger.get("day") != state.clock.day:
        return ""
    for sender, row in ledger["actors"].items():
        if row["status"] != "confirmed" or actor_id not in (sender, row["target_id"]):
            continue
        if receipts.get("day") == state.clock.day and sender in receipts.get("actors", {}):
            continue
        partner_id = row["target_id"] if sender == actor_id else sender
        partner = state.population[partner_id].get("display_name", "一位认识的人") if reveal_partner else "一位认识的人"
        return f" 今天{PHASE_LABELS[row['phase']]}已经和{partner}约好碰面，不过具体事情还要当面商量。"
    return ""


def coordination_invariant(state):
    ledger = state.cognition.get("social_coordination")
    if ledger is None:
        return
    if (not isinstance(ledger, dict) or type(ledger.get("day")) is not int
            or not 1 <= ledger["day"] <= state.clock.day or not isinstance(ledger.get("actors"), dict)):
        yield "invalid social coordination ledger"
        return
    reservations = set()
    for actor_id, row in ledger["actors"].items():
        if (actor_id not in state.population or actor_id == "player" or not isinstance(row, dict)
                or row.get("target_id") not in state.population or row.get("target_id") in (actor_id, "player")
                or row.get("phase") not in PHASE_LABELS or row.get("location_id") not in state.places
                or row.get("status") not in {"confirmed", "declined"} or row.get("reason") not in REASONS
                or (row.get("status") == "confirmed") != (row.get("reason") == "compatible")
                or not all(isinstance(row.get(k), str) and row[k] for k in ("request_message_id", "reply_message_id"))):
            yield "invalid social coordination record"
            continue
        if row["status"] == "confirmed":
            keys = {(actor_id, row["phase"]), (row["target_id"], row["phase"])}
            if keys & reservations:
                yield "overlapping social appointments"
            reservations.update(keys)
