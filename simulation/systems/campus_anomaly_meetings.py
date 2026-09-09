"""Private, consented appointments; promises are never attendance or recovery.

Autonomous proposals happen only at dawn. Travel uses the ordinary scheduler;
support is settled after both actors have actually arrived, by the shared action.
"""
from dataclasses import replace
from math import isfinite

from simulation.actions.commands import SimulationCommand
from simulation.systems.campus_anomalies import _available, _consents, make_anomaly_handler
from simulation.systems.campus_growth import mastery_by_topic
from simulation.systems.campus_messaging import are_phone_contacts, append_structured_phone_message
from simulation.systems.transactions import TransactionOutcome

ACTIONS = ("PROPOSE_ANOMALY_MEETING", "ACCEPT_ANOMALY_MEETING", "CANCEL_ANOMALY_MEETING")
PHASES = ("morning", "afternoon", "evening", "late_night")
LABELS = {"morning": "上午", "afternoon": "下午"}
PLACES = ("mirror_lake_square", "library_reading_hall")
LIVE = {"pending", "confirmed"}


def records(state):
    return state.situations.get("anomaly_meetings", {}).get("records", {})


def stamp(day, phase):
    return day * 4 + PHASES.index(phase)


def reserved_meeting(state, actor, *, upcoming=False):
    now = stamp(state.clock.day, state.clock.phase)
    return next((r for r in records(state).values() if r["status"] == "confirmed"
        and actor in (r["subject_id"], r["helper_id"])
        and (stamp(r["day"], r["phase"]) >= now if upcoming else stamp(r["day"], r["phase"]) == now)), None)


def slot_problem(state, case, helper, day, phase, location, graph, ignore=None):
    if (type(day) not in {int, float} or not isfinite(day) or day != int(day)
            or not state.clock.day <= day <= state.clock.day + 3 or not isinstance(phase, str) or phase not in LABELS
            or not isinstance(location, str)
            or stamp(day, phase) < stamp(state.clock.day, state.clock.phase) or location not in PLACES):
        return "请选择未来三天内的白天开放公共地点。"
    for actor in (case["actor_id"], helper):
        person = state.population[actor]
        slot = person.get("weekly_schedule", {}).get(str((int(day) - 1) % 7), {}).get(phase, {})
        if int(slot.get("priority", 0)) >= 90 or person.get("active_forum_task_id"):
            return "有人已有课程、工作或未完成委托，不能覆盖原有承诺。"
        if not _available(state, actor) or max(person.get("needs", {}).get(k, 0) for k in ("rest", "food", "safety")) >= 90:
            return "有人需要先处理当前安全或基本生活需求。"
        if any(r["status"] == "confirmed" and r["meeting_id"] != ignore and actor in (r["subject_id"], r["helper_id"])
                and (r["day"], r["phase"]) == (day, phase) for r in records(state).values()):
            return "这个时段已有支持预约。"
        social = state.cognition.get("social_coordination", {})
        if social.get("day") == day and any(r["status"] == "confirmed" and r["phase"] == phase
                and actor in (sender, r["target_id"]) for sender, r in social.get("actors", {}).items()):
            return "这个时段已经约好与其他人见面。"
        for party in state.parties.values():
            dep = party.get("members", {}).get(actor, {}).get("departure", {})
            if (dep.get("day"), dep.get("phase")) == (day, phase):
                return "这个时段已有出击预约。"
        if (day, phase) == (state.clock.day, state.clock.phase) and state.action_economy["actors"][actor]["major_remaining"] < 1:
            return "当前时段有人没有剩余主要行动，请约其他时段。"
        if (state.places[location].get("open_phases") and phase not in state.places[location]["open_phases"]):
            return "约定地点在该时段尚未开放。"
        if not graph.is_open(location, phase) or graph.shortest_route(person["current_location_id"], location,
                phase=phase, access_tags=person.get("access_tags", ())) is None:
            return "有人无法沿开放道路到达约定地点。"
    return None


def options(state, case, helper, graph):
    return [{"day": day, "phase": phase, "location_id": location,
        "label": f"第 {day} 天{LABELS[phase]} · {state.places[location]['name']}"}
        for day in range(state.clock.day, state.clock.day + 4) for phase in LABELS for location in PLACES
        if stamp(day, phase) > stamp(state.clock.day, state.clock.phase)
        and not slot_problem(state, case, helper, day, phase, location, graph)]


def _notify(context, row, sender, text, policy):
    target = row["helper_id"] if sender == row["subject_id"] else row["subject_id"]
    message = append_structured_phone_message(context, sender, target, text, policy, source="anomaly_appointment")
    row["message_ids"].append(message["message_id"])
    context.emit("CAMPUS_ANOMALY_MEETING_UPDATED", text, actor_ids=[sender], target_ids=[target],
        visibility="private", knowledge_tags=["anomaly", "schedule"],
        payload={"meeting_id": row["meeting_id"], "status": row["status"]})


def _close(context, row, status, reason, policy, sender=None):
    row.update(status=status, reason=reason, revision=row["revision"] + 1)
    _notify(context, row, sender or row["subject_id"], reason, policy)


def make_meeting_handler(graph, policy):
    def handle(context, command):
        state, actor, p = context.state, command.actor_id, command.parameters
        def fail(code, message):
            return TransactionOutcome(False, False, code, message)
        if actor not in state.population or (command.source == "player" and actor != "player"):
            return fail("actor_not_authorized", "不能代替别人确认预约。")
        if (command.issued_day, command.issued_phase) != (state.clock.day, state.clock.phase):
            return fail("command_clock_mismatch", "时段已变化。")
        if command.action_id != "PROPOSE_ANOMALY_MEETING":
            rid = p.get("meeting_id")
            row = records(state).get(rid) if isinstance(rid, str) else None
            if not row or actor not in (row["subject_id"], row["helper_id"]):
                return fail("meeting_not_visible", "无法操作他人的私人预约。")
            revision = p.get("expected_revision")
            if type(revision) not in {int, float} or revision != row["revision"] or row["status"] not in LIVE:
                return fail("meeting_revision_conflict", "预约已变化，请刷新。")
            if command.action_id == "CANCEL_ANOMALY_MEETING":
                _close(context, row, "cancelled", "已婉拒或取消支持预约；不会返还已用行动。", policy, actor)
            elif command.action_id == "ACCEPT_ANOMALY_MEETING":
                if row["status"] != "pending" or actor == row["proposer_id"]:
                    return fail("recipient_required", "需要由受邀者确认，不能替对方同意。")
                case = state.situations["campus_anomalies"]["cases"][row["case_id"]]
                problem = slot_problem(state, case, row["helper_id"], row["day"], row["phase"], row["location_id"], graph, row["meeting_id"])
                if case["status"] == "resolved" or not _consents(state, row["subject_id"], row["helper_id"], 50):
                    problem = "当前已不需要活动，或本人不愿继续。"
                if mastery_by_topic(state, row["helper_id"]).get(case["topic_id"], 0) < 20:
                    problem = "帮助者需要先将对应现象的理解提升至 20。"
                if problem:
                    return fail("meeting_unavailable", problem)
                row.update(status="confirmed", revision=row["revision"] + 1)
                _notify(context, row, actor, "同意预约；届时各预留一次主要行动，到场后仍可拒绝。", policy)
            else:
                return fail("unsupported_meeting_action", "未知预约行动。")
            return TransactionOutcome(True, True, "meeting_updated", row["reason"] or "预约已确认。", commit=True)
        cid, helper = p.get("case_id"), p.get("helper_id", actor)
        case = state.situations.get("campus_anomalies", {}).get("cases", {}).get(cid) if isinstance(cid, str) else None
        if not case or not isinstance(helper, str) or helper not in state.population or helper == case["actor_id"]:
            return fail("unknown_case", "没有可约见的本人经历。")
        subject = case["actor_id"]
        if actor not in (subject, helper) or (actor == helper and helper not in case["reports"]):
            return fail("experience_required", "只能根据自己听过的本人陈述发起支持邀请。")
        if case["status"] == "resolved" or not are_phone_contacts(state, subject, helper) or not _consents(state, subject, helper, 50):
            return fail("meeting_declined", "需要已有联系方式、本人意愿及尚待支持的经历。")
        if any(r["case_id"] == cid and (r["status"] in LIVE or
                (r["helper_id"] == helper and r["created_day"] == state.clock.day)) for r in records(state).values()):
            return fail("meeting_already_requested", "这次经历已有预约，或今天已向此人提出过；请勿反复催促。")
        day, phase, location = p.get("day"), p.get("phase"), p.get("location_id")
        # New invitations always leave time for the other participant to respond.
        problem = slot_problem(state, case, helper, day, phase, location, graph)
        if problem or stamp(day, phase) <= stamp(state.clock.day, state.clock.phase):
            return fail("meeting_unavailable", problem or "请选择后续时段。")
        if actor == helper and mastery_by_topic(state, helper).get(case["topic_id"], 0) < 20:
            return fail("knowledge_required", "需要先将对应现象的理解提升至 20。")
        ledger = state.situations.setdefault("anomaly_meetings", {"schema_version": 1, "records": {}, "planned_day": 0})
        rid = f"anomaly-meeting:{len(ledger['records']) + 1}"
        recipient = helper if actor == subject else subject
        row = {"meeting_id": rid, "case_id": cid, "subject_id": subject, "helper_id": helper,
            "proposer_id": actor, "created_day": state.clock.day, "created_phase": state.clock.phase,
            "day": int(day), "phase": phase, "location_id": location, "status": "pending", "revision": 0,
            "reason": "", "message_ids": [], "attended": [], "support_revision": None}
        ledger["records"][rid] = row
        _notify(context, row, actor,
            f"愿意第 {int(day)} 天{LABELS[phase]}在{state.places[location]['name']}一起核对月相经历、做现实锚定吗？需要各留一次主要行动。", policy)
        # The helper checks their own understanding, not the subject reading a
        # stranger's private mastery. Players never accept automatically.
        if recipient != "player":
            if mastery_by_topic(state, helper).get(case["topic_id"], 0) < 20 or (recipient == helper and not _consents(state, helper, subject, 35)):
                _close(context, row, "declined", "我目前的理解或意愿不足以承担这次支持，先不约了。", policy, recipient)
                from simulation.systems.campus_support_preparation import start_preparation
                start_preparation(context, row, policy)
            else:
                row.update(status="confirmed", revision=1)
                _notify(context, row, recipient, "好，按这个时间地点见面；到场再确认近况与意愿。", policy)
        return TransactionOutcome(True, True, "meeting_proposed", "邀请已发送，回复与约定已记录在手机。", commit=True)
    return handle


def advance_meetings(context, graph, policy, *, ending=False):
    state = context.state
    now = stamp(state.clock.day, state.clock.phase)
    for row in list(records(state).values()):
        if row["status"] not in LIVE:
            continue
        due = stamp(row["day"], row["phase"])
        if due < now or (ending and due == now):
            _close(context, row, "missed", "预约时段已结束，未完成支持；不推断对方异常，也不扣除或返还行动。", policy)
        elif row["status"] == "confirmed" and due == now:
            case = state.situations["campus_anomalies"]["cases"][row["case_id"]]
            problem = slot_problem(state, case, row["helper_id"], row["day"], row["phase"], row["location_id"], graph, row["meeting_id"])
            if case["status"] == "resolved" or not _consents(state, row["subject_id"], row["helper_id"], 50):
                problem = "当前已不需要活动，或本人不愿继续。"
            if row["helper_id"] != "player" and not _consents(state, row["helper_id"], row["subject_id"], 35):
                problem = "帮助者目前不愿继续参与，需要重新沟通。"
            if problem:
                _close(context, row, "cancelled", "预约条件变化，取消本次见面：" + problem, policy)
    if ending or state.clock.phase != "morning":
        return {}
    ledger = state.situations.setdefault("anomaly_meetings", {"schema_version": 1, "records": {}, "planned_day": 0})
    if ledger["planned_day"] == state.clock.day:
        return {}
    ledger["planned_day"] = state.clock.day
    handler = make_meeting_handler(graph, policy)
    for case in state.situations.get("campus_anomalies", {}).get("cases", {}).values():
        subject = case["actor_id"]
        if subject == "player" or case["status"] == "resolved" or any(r["case_id"] == case["case_id"] and r["status"] in LIVE for r in records(state).values()):
            continue
        helpers = [who for who in state.population if who != subject and are_phone_contacts(state, subject, who) and _consents(state, subject, who, 50)]
        helpers.sort(key=lambda who: (-state.relationships.get(subject, {}).get(who, {}).get("trust", 0), who))
        # Try one trusted contact per dawn; rotate after declining, no daily spam
        # at every contact and no hidden knowledge-based selection.
        helpers = [who for who in helpers if not any(r["case_id"] == case["case_id"] and r["helper_id"] == who
            and r["created_day"] >= state.clock.day - 2 for r in records(state).values())]
        for helper in helpers:
            choices = options(state, case, helper, graph)
            if not choices:
                continue
            cmd = SimulationCommand(f"meeting:{case['case_id']}:{state.clock.day}", subject, "PROPOSE_ANOMALY_MEETING", state.revision,
                parameters={"case_id": case["case_id"], "helper_id": helper, **choices[0]},
                issued_day=state.clock.day, issued_phase=state.clock.phase, source="rule")
            handler(context, cmd)
            break
    return {}


def meeting_plan(state, actor):
    row = reserved_meeting(state, actor)
    if not row:
        return None
    return {"activity_id": "WAIT_ANOMALY_MEETING", "action_class": "free", "location_id": row["location_id"],
        "day": state.clock.day, "phase": state.clock.phase, "decision_source": "rule", "candidate_count": 1, "decision_reason": "consented_support_appointment",
        "parameters": {"meeting_id": row["meeting_id"]}}


def settle_meetings(context, policy):
    state, handler = context.state, make_anomaly_handler()
    count = 0
    for row in list(records(state).values()):
        if row["status"] != "confirmed" or (row["day"], row["phase"]) != (state.clock.day, state.clock.phase):
            continue
        row["attended"] = [who for who in (row["subject_id"], row["helper_id"])
            if _available(state, who) and state.population[who]["current_location_id"] == row["location_id"]]
        if "player" in (row["subject_id"], row["helper_id"]) or len(row["attended"]) != 2:
            continue
        case = state.situations["campus_anomalies"]["cases"][row["case_id"]]
        cmd = SimulationCommand(f"meeting-support:{row['meeting_id']}", row["helper_id"], "ASK_ANOMALY_EXPERIENCE", state.revision,
            parameters={"npc_id": row["subject_id"]}, issued_day=state.clock.day, issued_phase=state.clock.phase, source="rule")
        heard = handler(context, cmd)
        from simulation.systems.campus_relationship_anchors import automatic_support_parameters
        result = handler(context, replace(cmd, action_id="SUPPORT_ANOMALY",
            parameters=automatic_support_parameters(context, case, row["helper_id"]))) if heard.success else heard
        if not result.success:
            _close(context, row, "cancelled", "到场后未能开展支持：" + result.message, policy)
        else:
            count += 1
    return {"appointment_supports": count}


def complete_meeting(context, case, helper):
    row = reserved_meeting(context.state, helper)
    if row and row["case_id"] == case["case_id"] and row["helper_id"] == helper:
        row.update(status="completed", revision=row["revision"] + 1, reason="双方实际完成现实锚定。",
            attended=[row["subject_id"], helper], support_revision=case["revision"])


def meetings_view(state, viewer="player"):
    return [{k: r[k] for k in ("meeting_id", "case_id", "subject_id", "helper_id", "proposer_id", "day", "phase", "location_id", "status", "revision", "reason")}
        for r in records(state).values() if viewer in (r["subject_id"], r["helper_id"])]


def meetings_invariant(state):
    ledger = state.situations.get("anomaly_meetings")
    if ledger is None:
        return []
    try:
        if ledger["schema_version"] != 1 or type(ledger["planned_day"]) is not int or not 0 <= ledger["planned_day"] <= state.clock.day:
            return ["invalid support appointment ledger"]
        occupied, active = set(), set()
        for key, row in ledger["records"].items():
            case = state.situations["campus_anomalies"]["cases"][row["case_id"]]
            pair = {row["subject_id"], row["helper_id"]}
            if (key != row["meeting_id"] or row["subject_id"] != case["actor_id"] or len(pair) != 2
                    or not pair <= state.population.keys() or row["proposer_id"] not in pair
                    or type(row["day"]) is not int or not case["created_day"] <= row["created_day"] <= state.clock.day
                    or not row["created_day"] <= row["day"] <= row["created_day"] + 3 or row["phase"] not in LABELS
                    or stamp(row["day"], row["phase"]) <= stamp(row["created_day"], row["created_phase"])
                    or row["location_id"] not in PLACES or type(row["revision"]) is not int or row["revision"] < 0
                    or row["status"] not in LIVE | {"completed", "declined", "cancelled", "missed"}
                    or not set(row["attended"]) <= pair or not row["message_ids"]):
                return ["invalid support appointment record"]
            if row["status"] in LIVE:
                if row["case_id"] in active:
                    return ["duplicate active support appointment"]
                active.add(row["case_id"])
            if row["status"] == "confirmed":
                keys = {(who, row["day"], row["phase"]) for who in pair}
                if keys & occupied:
                    return ["overlapping support appointments"]
                occupied.update(keys)
            if row["status"] == "completed":
                receipt = next((r for r in case["history"] if r["revision"] == row["support_revision"]), {})
                if (set(row["attended"]) != pair or receipt.get("route") != "day_support"
                        or receipt.get("helper_id") != row["helper_id"] or receipt.get("location_id") != row["location_id"]
                        or (receipt.get("day"), receipt.get("phase")) != (row["day"], row["phase"])):
                    return ["appointment has no actual support receipt"]
            elif row["support_revision"] is not None:
                return ["unfinished appointment claims support"]
    except (KeyError, TypeError, ValueError, AttributeError):
        return ["malformed support appointment ledger"]
    return []
