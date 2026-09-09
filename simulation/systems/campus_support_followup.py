"""Real mutual support changes relationships and may motivate later care.

No retrospective rewards, instant knowledge, hidden diagnosis or player orders.
"""
from simulation.systems.campus_social import adjust_relationship, relationship_between
from simulation.systems.campus_growth import mastery_by_topic
from simulation.systems.campus_trade import tick
from simulation.systems.campus_tasks import phase_index

KIND = "support_followup"
RELATION_DELTAS = {"subject": {"trust": 8, "closeness": 4, "respect": 3},
                  "helper": {"trust": 2, "closeness": 3, "respect": 1}}


def apply_relationships(state, subject, helper):
    changes = {}
    for role, owner, target in (("subject", subject, helper), ("helper", helper, subject)):
        before = {key: relationship_between(state, owner, target)[key] for key in RELATION_DELTAS[role]}
        applied = adjust_relationship(state, owner, target, RELATION_DELTAS[role])
        changes[role] = {"owner_id": owner, "target_id": target, "before": before,
            "applied": applied, "after": {key: before[key] + applied[key] for key in before}}
    return changes


def relationship_receipt_valid(case, receipt):
    changes = receipt.get("relationship_changes")
    if changes is None:
        return True  # Earlier saves keep their actual history; no backfill.
    try:
        if set(changes) != set(RELATION_DELTAS):
            return False
        for role, owner, target in (("subject", case["actor_id"], receipt["helper_id"]), ("helper", receipt["helper_id"], case["actor_id"])):
            row = changes[role]
            if row["owner_id"] != owner or row["target_id"] != target:
                return False
            for field in ("before", "after", "applied"):
                if set(row[field]) != set(RELATION_DELTAS[role]) or any(type(value) is not int for value in row[field].values()):
                    return False
            for key, delta in RELATION_DELTAS[role].items():
                if (not 0 <= row["before"][key] <= 100 or row["after"][key] != min(100, row["before"][key] + delta)
                        or row["applied"][key] != row["after"][key] - row["before"][key]):
                    return False
        return True
    except (TypeError, KeyError, AttributeError):
        return False


def source_valid(state, helper, goal):
    try:
        case = state.situations["campus_anomalies"]["cases"][goal["case_id"]]
        revision = goal["source_revision"]
        if type(revision) is not int or not 1 <= revision <= len(case["history"]):
            return False
        receipt = case["history"][revision - 1]
        return (goal["kind"] == KIND and goal["goal_id"] == "followup:" + case["case_id"]
            and goal["subject_id"] == case["actor_id"] and goal["topic_id"] == case["topic_id"]
            and receipt["route"] == "day_support" and receipt["helper_id"] == helper
            and "relationship_changes" in receipt and relationship_receipt_valid(case, receipt)
            and goal["source_ids"] == [receipt["claim_id"]]
            and receipt["claim_id"] in state.knowledge["beliefs_by_actor"][helper]
            and goal["created_tick"] > phase_index(receipt["day"], "late_night"))
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def followup_step(state, helper, goal):
    case = state.situations["campus_anomalies"]["cases"][goal["case_id"]]
    # The helper personally witnessed this resolution, or the subject told them.
    if any(row["route"] == "day_support" and row["helper_id"] == helper and not any(row["after"].values()) for row in case["history"]):
        return "support_closed"
    report = case["reports"].get(helper, {})
    if case["status"] == "resolved" and report.get("revision") == case["revision"]:
        return "support_closed"
    if report.get("day") != state.clock.day or goal.get("review_failed_day") == state.clock.day:
        return "check_in"
    if mastery_by_topic(state, helper).get(goal["topic_id"], 0) < 40:
        return "read"
    from simulation.systems.campus_anomaly_meetings import records
    if any(row["case_id"] == case["case_id"] and row["helper_id"] == helper and row["status"] in {"pending", "confirmed"} for row in records(state).values()):
        return "await_support"
    return "arrange_support"


def seed_followups(context, policy):
    state, created = context.state, 0
    if state.clock.phase != "morning":
        return 0
    from simulation.systems.campus_goals import _ledger
    from simulation.systems.campus_anomalies import _consents
    from simulation.systems.campus_messaging import are_phone_contacts, append_structured_phone_message
    for case in state.situations.get("campus_anomalies", {}).get("cases", {}).values():
        subject = case["actor_id"]
        if subject == "player":
            continue
        for receipt in case["history"]:
            helper = receipt["helper_id"]
            if (helper == "player" or receipt["route"] != "day_support" or "relationship_changes" not in receipt
                    or receipt["day"] != state.clock.day - 1 or not any(receipt["after"].values())
                    or not _consents(state, helper, subject, 35)):
                continue
            actor = state.population[helper]
            relation = state.relationships.get(helper, {}).get(subject, {})
            willingness = sum(actor.get("personality", {}).get(key, 50) for key in ("altruism", "agreeableness")) + relation.get("closeness", 0) + relation.get("obligation", 0)
            if willingness < 105:
                continue
            goals = _ledger(state)["actors"].setdefault(helper, {})
            goal_id = "followup:" + case["case_id"]
            if goal_id in goals or sum(g.get("kind") == KIND and g["status"] != "completed" for g in goals.values()) >= 2:
                continue
            goals[goal_id] = {"goal_id": goal_id, "kind": KIND, "case_id": case["case_id"], "subject_id": subject,
                "source_revision": receipt["revision"], "topic_id": case["topic_id"], "source_ids": [receipt["claim_id"]],
                "created_tick": tick(state), "checked_tick": tick(state), "step": "check_in", "status": "active",
                "blocked_reason": "", "attempts": 0, "last_action": "", "last_result": "", "history": []}
            message = "昨天一起核对过的经历，我还想继续弄懂。有空时想先问问你的近况，再考虑研读和以后是否约见；这不是新的预约，你可以拒绝。"
            if are_phone_contacts(state, helper, subject):
                append_structured_phone_message(context, helper, subject, message, policy, source="rule")
            context.emit("NPC_SUPPORT_FOLLOWUP_STARTED", message, actor_ids=[helper], target_ids=[subject],
                visibility="private", knowledge_tags=["goal", "evidence"], payload={"goal_id": goal_id, "source_revision": receipt["revision"]})
            created += 1
    return created
