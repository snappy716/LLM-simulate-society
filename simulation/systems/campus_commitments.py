"""Read-only calendar over existing authoritative ledgers; no duplicate budget."""
from simulation.domain.entities import PHASES

PHASE_IDS = tuple(p.value for p in PHASES)
LABELS = {"support": "已确认的支持约定", "departure": "全队出击预约", "social": "已确认的见面"}


def commitments_for(state, actor_id):
    """Only this actor's current/future confirmed commitments, detached values."""
    if actor_id not in state.population:
        return []
    now = (state.clock.day, PHASE_IDS.index(state.clock.phase))
    result = []

    def add(kind, source_id, day, phase, location_id=""):
        if type(day) is not int or phase not in PHASE_IDS or (day, PHASE_IDS.index(phase)) < now:
            return
        result.append({"kind": kind, "source_id": source_id, "day": day, "phase": phase,
            "location_id": location_id, "label": LABELS[kind],
            "major_action_cost": 0 if kind == "social" else 1,
            "status": "confirmed"})

    for key, row in state.situations.get("anomaly_meetings", {}).get("records", {}).items():
        if row.get("status") == "confirmed" and actor_id in (row.get("subject_id"), row.get("helper_id")):
            add("support", key, row.get("day"), row.get("phase"), row.get("location_id", ""))
    for key, party in state.parties.items():
        row = party.get("members", {}).get(actor_id, {}).get("departure", {})
        if row:
            add("departure", key, row.get("day"), row.get("phase"))
    social = state.cognition.get("social_coordination", {})
    receipts = state.cognition.get("social_agenda_receipts", {})
    for sender, row in social.get("actors", {}).items():
        settled = receipts.get("day") == social.get("day") and sender in receipts.get("actors", {})
        if not settled and row.get("status") == "confirmed" and actor_id in (sender, row.get("target_id")):
            add("social", sender, social.get("day"), row.get("phase"), row.get("location_id", ""))
    return sorted(result, key=lambda r: (r["day"], PHASE_IDS.index(r["phase"]), r["kind"], r["source_id"]))


def commitments_at(state, actor_id, day, phase, *, ignore=None):
    return [r for r in commitments_for(state, actor_id)
        if (r["day"], r["phase"]) == (day, phase) and (r["kind"], r["source_id"]) != ignore]


def agenda_view(state, actor_id="player"):
    rows = commitments_for(state, actor_id)
    for row in rows:
        row["location_name"] = state.places.get(row["location_id"], {}).get("name", "出发前在行动小队确认集合地点")
        row["management_app"] = "party" if row["kind"] == "departure" else "messages"
    return {"commitments": rows,
        "note": "这里只显示本人已经确认的约定，不显示其他人的私密日程。预约不是已完成；实际到场后仍核对条件并结算。短暂见面不扣主要行动，但不能同时答应无法兼顾的出击。取消不会返还已用行动。"}
