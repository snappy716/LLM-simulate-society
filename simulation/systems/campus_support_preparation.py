"""A friend's real request can motivate learning, never grant instant mastery.

These are typed entries in the existing persistent goal ledger. Their source is
an actual incoming request AND a voluntarily heard statement, not an owned fight.
"""
from dataclasses import replace

from simulation.actions.commands import SimulationCommand
from simulation.systems.campus_anomalies import _consents, make_anomaly_handler
from simulation.systems.campus_growth import mastery_by_topic
from simulation.systems.campus_trade import tick

KIND = "support_preparation"


def source_valid(state, actor, goal):
    try:
        row = state.situations["anomaly_meetings"]["records"][goal["request_id"]]
        case = state.situations["campus_anomalies"]["cases"][goal["case_id"]]
        claim = state.knowledge["claims"][goal["source_ids"][0]]
        return (goal["kind"] == KIND and goal["goal_id"] == "support:" + case["case_id"]
            and goal["subject_id"] == case["actor_id"] == row["subject_id"] == row["proposer_id"]
            and row["helper_id"] == actor and row["case_id"] == case["case_id"]
            and row["status"] == "declined" and goal["topic_id"] == case["topic_id"]
            and len(goal["source_ids"]) == 1 and claim["predicate"] == "voluntary_moon_experience"
            and claim["subject_id"] == goal["subject_id"] and claim["source_context"]["source_id"] == case["case_id"]
            and (claim["source_context"]["day"], claim["source_context"]["phase"]) == (row["created_day"], row["created_phase"])
            and claim["claim_id"] in state.knowledge["beliefs_by_actor"][actor])
    except (KeyError, TypeError, ValueError, AttributeError, IndexError):
        return False


def preparation_step(state, actor, goal):
    case = state.situations["campus_anomalies"]["cases"][goal["case_id"]]
    # Own committed support is a fact. Other people's secret outcomes are not
    # treated as knowledge: closure below requires the helper's fresh report.
    if any(r["route"] == "day_support" and r["helper_id"] == actor for r in case["history"]):
        return "complete"
    report = case["reports"].get(actor, {})
    if case["status"] == "resolved" and report.get("revision") == case["revision"]:
        return "support_closed"
    if mastery_by_topic(state, actor).get(goal["topic_id"], 0) < 20:
        return "read"
    from simulation.systems.campus_anomaly_meetings import records
    if any(r["case_id"] == goal["case_id"] and r["helper_id"] == actor and r["status"] in {"pending", "confirmed"} for r in records(state).values()):
        return "await_support"
    return "arrange_support"


def start_preparation(context, row, policy):
    state, helper, subject = context.state, row["helper_id"], row["subject_id"]
    if helper == "player" or row["proposer_id"] != subject or row["status"] != "declined":
        return False
    case = state.situations["campus_anomalies"]["cases"][row["case_id"]]
    if mastery_by_topic(state, helper).get(case["topic_id"], 0) >= 20 or not _consents(state, helper, subject, 35):
        return False
    actor = state.population[helper]
    personality = actor.get("personality", {})
    relation = state.relationships.get(helper, {}).get(subject, {})
    willingness = (personality.get("altruism", 50) + personality.get("agreeableness", 50)
        + relation.get("closeness", 0) + relation.get("obligation", 0))
    if willingness < 105:
        return False  # An invitation does not recruit every contact unconditionally.
    from simulation.systems.campus_goals import _ledger
    goals = _ledger(state)["actors"].setdefault(helper, {})
    goal_id = "support:" + case["case_id"]
    if goal_id in goals or sum(g.get("kind") == KIND and g["status"] != "completed" for g in goals.values()) >= 2:
        return False
    command = SimulationCommand("support-preparation:" + row["meeting_id"], helper, "ASK_ANOMALY_EXPERIENCE", state.revision,
        parameters={"npc_id": subject}, issued_day=state.clock.day, issued_phase=state.clock.phase, source="rule")
    outcome = make_anomaly_handler()(context, command)
    if not outcome.success:
        return False
    claim_id = case["reports"][helper]["claim_id"]
    goals[goal_id] = {"goal_id": goal_id, "kind": KIND, "case_id": case["case_id"], "subject_id": subject,
        "request_id": row["meeting_id"], "topic_id": case["topic_id"], "source_ids": [claim_id],
        "created_tick": tick(state), "checked_tick": tick(state), "step": "read", "status": "active",
        "blocked_reason": "", "attempts": 0, "last_action": "", "last_result": "", "history": []}
    from simulation.systems.campus_anomaly_meetings import _notify
    _notify(context, row, helper, "我现在还没弄懂这类经历，不能先答应支持。但我愿意先读相关讲义，理解后再联系你确认；这不是新的预约。", policy)
    context.emit("NPC_SUPPORT_PREPARATION_STARTED", "听取朋友本人陈述后，决定先学习再考虑如何提供支持。",
        actor_ids=[helper], target_ids=[subject], visibility="private", knowledge_tags=["goal", "support", "evidence"],
        payload={"goal_id": goal_id, "request_id": row["meeting_id"], "claim_id": claim_id})
    return True


def advance_support_preparations(context, graph, policy):
    """One dawn reconsideration; no intraday model call or instant appointment."""
    state = context.state
    if state.clock.phase != "morning":
        return {}
    from simulation.systems.campus_goals import _ledger
    ledger = _ledger(state)
    if ledger.get("support_review_day") == state.clock.day:
        return {}
    ledger["support_review_day"] = state.clock.day
    from simulation.systems.campus_goals import _update, goal_step
    from simulation.systems.campus_support_followup import seed_followups
    created = seed_followups(context, policy)
    from simulation.systems.campus_anomaly_meetings import records, options, make_meeting_handler
    handler = make_meeting_handler(graph, policy)
    for helper, goals in ledger.get("actors", {}).items():
        for goal in goals.values():
            if goal.get("kind") not in {KIND, "support_followup"} or goal["status"] == "completed":
                continue
            followup = goal.get("kind") == "support_followup"
            step = goal_step(state, helper, goal)
            if step in {"complete", "support_closed"}:
                _update(state, goal, step, "completed", "已实际支持过一次。" if step == "complete" else "已确认本次经历稳定，不再重复准备。")
                continue
            if not _consents(state, helper, goal["subject_id"], 35):
                _update(state, goal, step, "blocked", "目前不愿继续提供支持，保留已经学到的知识。")
                continue
            if step != "arrange_support" and not followup:
                _update(state, goal, step, "active")
                continue
            case = state.situations["campus_anomalies"]["cases"][goal["case_id"]]
            # Reconfirm privately; no inference from unseen case changes.
            cmd = SimulationCommand(f"support-review:{helper}:{goal['goal_id']}:{state.clock.day}", helper, "ASK_ANOMALY_EXPERIENCE", state.revision,
                parameters={"npc_id": goal["subject_id"], "case_id": goal["case_id"]}, issued_day=state.clock.day, issued_phase=state.clock.phase, source="rule")
            heard = make_anomaly_handler()(context, cmd)
            if not heard.success:
                if followup:
                    goal["review_failed_day"] = state.clock.day
                _update(state, goal, "check_in" if followup else step, "blocked", heard.message)
                continue
            goal.pop("review_failed_day", None)
            step = goal_step(state, helper, goal)
            if step == "support_closed":
                _update(state, goal, "support_closed", "completed", "本人已告知稳定，不再重复准备。")
                continue
            if step != "arrange_support":
                _update(state, goal, step, "active")
                continue
            if any(r["case_id"] == case["case_id"] and r["status"] in {"pending", "confirmed"} for r in records(state).values()):
                _update(state, goal, step, "blocked", "本人已有支持安排，等待下次确认，不抢占约定。")
                continue
            choices = options(state, case, helper, graph)
            if not choices:
                _update(state, goal, step, "blocked", "尚无兼容时段，保留已学知识，不覆盖职责。")
                continue
            outcome = handler(context, replace(cmd, action_id="PROPOSE_ANOMALY_MEETING", parameters={"case_id": case["case_id"],
                "helper_id": helper, **{key: choices[0][key] for key in ("day", "phase", "location_id")}}))
            _update(state, goal, goal_step(state, helper, goal), "active" if outcome.success else "blocked", "" if outcome.success else outcome.message)
    return {"support_followups_created": created}
