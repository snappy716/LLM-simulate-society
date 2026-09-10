"""Public campus opportunities; shared enrollment and actual attendance ledger.

Enrollment reserves an existing phase budget, never pays rewards or teleports.
Only the ordinary validated activity handler produces growth/resource effects.
"""
from copy import deepcopy
from dataclasses import replace

from simulation.domain.entities import PHASES
from simulation.systems.transactions import TransactionOutcome

PHASE_IDS = tuple(p.value for p in PHASES)
ACTIONS = ("ENROLL_CAMPUS_OPPORTUNITY", "CANCEL_CAMPUS_OPPORTUNITY", "ATTEND_CAMPUS_OPPORTUNITY")
STATUS_TEXT = {"enrolled": "已报名，待到场", "completed": "已实际参加", "cancelled": "已退出", "missed": "已错过"}


def ledger(state):
    return state.situations.get("campus_life", {})


def install_life(state, definitions):
    state.situations.setdefault("campus_life", {"version": 1, "definitions": deepcopy(definitions), "records": {}})
    errors = list(life_invariant(state))
    if errors:
        raise ValueError("; ".join(errors))


def stamp(day, phase):
    return day * 4 + PHASE_IDS.index(phase)


def session(state, session_id):
    if not isinstance(session_id, str):
        return None
    parts = session_id.split(":")
    if len(parts) != 3 or parts[0] != "life" or not parts[1].isdigit():
        return None
    day = int(parts[1])
    definition = ledger(state).get("definitions", {}).get(parts[2])
    if not isinstance(definition, dict) or day < 1 or (day - 1) % 7 not in definition.get("weekdays", ()):
        return None
    if session_id != f"life:{day}:{parts[2]}":
        return None
    return {**deepcopy(definition), "session_id": session_id, "day": day}


def participant(state, actor_id, session_id):
    return ledger(state).get("records", {}).get(session_id, {}).get(actor_id)


def active_booking(state, actor_id):
    for sid, records in ledger(state).get("records", {}).items():
        record = records.get(actor_id, {})
        row = session(state, sid)
        if record.get("status") == "enrolled" and row and (row["day"], row["phase"]) == (state.clock.day, state.clock.phase):
            return row
    return None


def assessment(state, actor_id, row, *, attending=False):
    from simulation.systems.campus_commitments import commitments_at
    from simulation.systems.campus_vitals import actor_layer, battle_locked
    from simulation.systems.campus_night_sites import captive_site
    if not row or actor_id not in state.population:
        return "unknown_opportunity", "活动或参与者不存在。"
    actor = state.population[actor_id]
    record = participant(state, actor_id, row["session_id"])
    if record and record["status"] in {"completed", "missed"}:
        return "opportunity_closed", "此场活动已参加或错过，不能再次结算。"
    now, when = stamp(state.clock.day, state.clock.phase), stamp(row["day"], row["phase"])
    if when < now or row["day"] > state.clock.day + 2:
        return "opportunity_wrong_time", "只可报名当前及随后两天尚未结束的活动。"
    if attending and when != now:
        return "opportunity_wrong_time", "还未到活动时段。"
    if actor.get("role_kind") not in row["roles"]:
        return "opportunity_ineligible", "不符合这场活动的参与身份。"
    if battle_locked(state, actor_id) or captive_site(state, actor_id) or actor_layer(state, actor_id) != "surface":
        return "opportunity_unavailable", "请先处理战斗、被困或里世界行动。"
    if commitments_at(state, actor_id, row["day"], row["phase"], ignore=("life", row["session_id"])):
        return "opportunity_conflict", "该时段已有不能兼顾的确认约定。"
    # NPC work/class duties remain protected, including future weekly slots.
    if actor_id != "player":
        # Use the stored weekly schedule without advancing the real world.
        plan = actor.get("weekly_schedule", {}).get(str((row["day"] - 1) % 7), {}).get(row["phase"], {})
        if int(plan.get("priority", 0)) >= 90 or (actor.get("active_forum_task_id") and (not record or record["status"] != "enrolled")):
            return "opportunity_duty", "已有课程、工作或接取中的委托，不能同时报名。"
    place = state.places.get(row["location_id"], {})
    if not place or (place.get("open_phases") and row["phase"] not in place["open_phases"]):
        return "opportunity_closed_place", "活动地点未开放。"
    if not set(place.get("access_tags", ())).issubset(actor.get("access_tags", ())):
        return "opportunity_access", "没有活动地点的通行权限。"
    if attending and actor.get("current_location_id") != row["location_id"]:
        return "activity_wrong_location", "请沿校园道路先到活动地点，手机报名不会传送。"
    quantities = state.inventories.get("actors", {}).get(actor_id, {}).get("quantities", {})
    if any(quantities.get(item, 0) < count for item, count in row["required_items"].items()):
        return "opportunity_materials", "缺少活动要求的随身工具。"
    if when == now and state.action_economy.get("actors", {}).get(actor_id, {}).get("major_remaining", 0) < 1:
        return "major_action_exhausted", "本时段没有剩余主要行动。"
    from simulation.systems.campus_study_work import study_work_assessment
    outcome = study_work_assessment(state, actor_id, row)
    if outcome:
        return outcome
    if record and record["status"] == "enrolled":
        from simulation.systems.campus_events import options_problem
        outcome = options_problem(state, actor_id, row, record.get("event_options", {}))
        if outcome:
            return outcome
    return "", "报名/退出免费；实际参加消耗一次主要行动，工具不消耗，不自动推进时间。"


def enroll(context, actor_id, row, event_options=None):
    code, message = assessment(context.state, actor_id, row)
    if code:
        return TransactionOutcome(False, False, code, message)
    old = participant(context.state, actor_id, row["session_id"])
    if old and old["status"] == "enrolled":
        return TransactionOutcome(False, True, "already_enrolled", "已经报名，未重复预留。")
    from simulation.systems.campus_events import options_problem
    options = {} if event_options is None else event_options
    problem = options_problem(context.state, actor_id, row, options)
    if problem:
        return TransactionOutcome(False, False, *problem)
    record = {"status": "enrolled", "enrolled_day": context.state.clock.day,
              "enrolled_phase": context.state.clock.phase, "history": deepcopy(old.get("history", [])) if old else []}
    if row.get("event"):
        record["event_options"] = deepcopy(options)
    record["history"].append({"status": "enrolled", "day": context.state.clock.day, "phase": context.state.clock.phase})
    ledger(context.state)["records"].setdefault(row["session_id"], {})[actor_id] = record
    context.emit("CAMPUS_LIFE_ENROLLED", f"已报名 {row['name']}，尚未到场。", actor_ids=[actor_id],
                 payload={"session_id": row["session_id"]}, visibility="private", knowledge_tags=["campus_life"])
    return TransactionOutcome(True, True, "enrolled", "报名成功，实际参加时再结算行动。", commit=True)


def validate_attendance(context, command, definition):
    sid = command.parameters.get("life_session_id")
    if sid is None:
        return None
    row = session(context.state, sid)
    record = participant(context.state, command.actor_id, sid) if isinstance(sid, str) else None
    if not row or definition.activity_id != row["activity_id"]:
        return TransactionOutcome(False, False, "unknown_opportunity", "活动编号与实际行动不匹配。")
    if not record or record["status"] != "enrolled":
        return TransactionOutcome(False, False, "opportunity_not_enrolled", "请先报名，已完成的场次不能再次结算。")
    code, message = assessment(context.state, command.actor_id, row, attending=True)
    return TransactionOutcome(False, False, code, message) if code else None


def settle_attendance(context, command, effects, event_performance=None):
    sid = command.parameters.get("life_session_id")
    if not sid:
        return
    row = session(context.state, sid)
    record = participant(context.state, command.actor_id, sid)
    from simulation.systems.campus_study_work import settle_study_work, visible_result
    result = settle_study_work(context, command.actor_id, row, effects)
    if row.get("event"):
        from simulation.systems.campus_events import settle_performance
        result["event"] = settle_performance(context, command.actor_id, row, record, event_performance)
    if result:
        record["result"] = result
        effects["life"] = visible_result(result)
    record.update(status="completed", completed_day=context.state.clock.day, completed_phase=context.state.clock.phase)
    record["history"].append({"status": "completed", "day": context.state.clock.day, "phase": context.state.clock.phase})
    context.emit("CAMPUS_LIFE_ATTENDED", f"实际参加了 {row['name']}。", actor_ids=[command.actor_id],
        scene_id=row["location_id"], payload={"session_id": sid, "name": row["name"], "activity_id": row["activity_id"], "major_action_cost": 1, "result": visible_result(result)},
        visibility="private", knowledge_tags=["campus_life", "activity"])


def make_life_handler(activity_handler):
    def handle(context, command):
        if (command.issued_day, command.issued_phase) != (context.state.clock.day, context.state.clock.phase):
            return TransactionOutcome(False, False, "command_clock_mismatch", "活动指令所属时段已经过期，请刷新后重试。")
        row = session(context.state, command.parameters.get("session_id"))
        if not row:
            return TransactionOutcome(False, False, "unknown_opportunity", "活动不存在。")
        if command.action_id == ACTIONS[0]:
            return enroll(context, command.actor_id, row, command.parameters.get("event_options"))
        if command.action_id == ACTIONS[1]:
            record = participant(context.state, command.actor_id, row["session_id"])
            if not record or record["status"] != "enrolled":
                return TransactionOutcome(False, False, "opportunity_not_enrolled", "没有可退出的报名。")
            record["status"] = "cancelled"
            record["history"].append({"status": "cancelled", "day": context.state.clock.day, "phase": context.state.clock.phase})
            context.emit("CAMPUS_LIFE_CANCELLED", f"退出了 {row['name']}，不返还已用行动。", actor_ids=[command.actor_id],
                         payload={"session_id": row["session_id"]}, visibility="private", knowledge_tags=["campus_life"])
            return TransactionOutcome(True, True, "cancelled", "已退出，解除本次预留。", commit=True)
        return activity_handler(context, replace(command, action_id=row["activity_id"],
            parameters={"life_session_id": row["session_id"], "location_id": row["location_id"]}))
    return handle


def expire_life(context):
    count = 0
    now = stamp(context.state.clock.day, context.state.clock.phase)
    for sid, records in ledger(context.state).get("records", {}).items():
        row = session(context.state, sid)
        if stamp(row["day"], row["phase"]) >= now:
            continue
        for actor_id, record in records.items():
            if record["status"] != "enrolled":
                continue
            record["status"] = "missed"
            record["history"].append({"status": "missed", "day": context.state.clock.day, "phase": context.state.clock.phase})
            context.emit("CAMPUS_LIFE_MISSED", f"未实际参加 {row['name']}，未给予出勤或收益。", actor_ids=[actor_id],
                         payload={"session_id": sid}, visibility="private", knowledge_tags=["campus_life"])
            count += 1
    from simulation.systems.campus_events import finalize_events
    return {"life_missed": count, **finalize_events(context)}


def booking_plan(state, actor_id):
    row = active_booking(state, actor_id)
    if not row:
        return None
    original = state.cognition.get("daily_plans", {}).get("actors", {}).get(actor_id, {}).get(state.clock.phase, {})
    if original.get("parameters", {}).get("life_session_id") != row["session_id"]:
        original = {}
    source = "llm" if original.get("planned_source") == "llm" else "rule"
    return {**deepcopy(original), "activity_id": row["activity_id"], "action_class": "major", "location_id": row["location_id"],
            "parameters": {"life_session_id": row["session_id"]}, "priority": 90, "decision_source": source,
            "decision_reason": "赴本人已确认的公开活动", "candidate_count": 1, "day": row["day"], "phase": row["phase"]}


def life_candidates(context, actor_id, schedule, graph, occupancy, policy, top_score):
    from simulation.systems.campus_decisions import _has_capacity
    state = context.state
    if int(schedule.get("priority", 0)) >= policy.protected_schedule_priority:
        return []
    result = []
    for key in ledger(state).get("definitions", {}):
        row = session(state, f"life:{state.clock.day}:{key}")
        if not row or row["phase"] != state.clock.phase or assessment(state, actor_id, row)[0]:
            continue
        actor = state.population[actor_id]
        route = graph.shortest_route(actor["current_location_id"], row["location_id"], phase=row["phase"], access_tags=actor.get("access_tags", ()))
        if not route or not _has_capacity(graph, occupancy, row["location_id"]):
            continue
        score = top_score - 12 + (actor.get("personality", {}).get(row["trait"], 50) - 50) * 0.4
        from simulation.systems.campus_study_work import study_work_view
        details = study_work_view(state, actor_id, row)
        from simulation.systems.campus_events import event_options, event_view, event_motivation
        details.update(event_view(state, actor_id, row))
        parameters = {"life_session_id": row["session_id"]}
        if row.get("event"):
            parameters["event_options"] = event_options(state, actor_id, row)
            motivation, motive = event_motivation(state, actor_id, row)
            score += motivation
            details["summary"] += "；" + motive
        if row.get("job"):
            score += max(0, actor.get("needs", {}).get("money", 0) - 40) * 0.3
        result.append({"candidate_id": row["session_id"], "activity_id": row["activity_id"], "action_class": "major",
                       "location_id": row["location_id"], "parameters": parameters,
                       "priority": 45, "decision_source": "rule", "decision_reason": row["name"] + "；报名后须实际到场；" + details["summary"],
                       "reason_codes": ["personal_interest", "public_opportunity"], "score": round(score, 3),
                       "day": row["day"], "phase": row["phase"], "route_minutes": route.total_minutes})
    return result


def enroll_chosen_plans(context, plans):
    for actor_id, slots in plans.items():
        for plan in slots.values():
            sid = plan.get("parameters", {}).get("life_session_id")
            if sid:
                enroll(context, actor_id, session(context.state, sid), plan.get("parameters", {}).get("event_options"))


def life_view(state, actor_id="player"):
    from simulation.systems.campus_study_work import study_work_view, course_progress, visible_result
    from simulation.systems.campus_events import event_view, event_board
    offers, history = [], []
    for day in range(state.clock.day, state.clock.day + 3):
        for key in ledger(state).get("definitions", {}):
            row = session(state, f"life:{day}:{key}")
            if not row or stamp(day, row["phase"]) < stamp(state.clock.day, state.clock.phase):
                continue
            record = participant(state, actor_id, row["session_id"])
            status = record["status"] if record else "available"
            code, reason = assessment(state, actor_id, row)
            attend_code, attend_reason = assessment(state, actor_id, row, attending=True)
            records = ledger(state)["records"].get(row["session_id"], {})
            offers.append({**row, **study_work_view(state, actor_id, row), **event_view(state, actor_id, row), "location_name": state.places[row["location_id"]]["name"],
                "status": status, "status_text": STATUS_TEXT.get(status, "可选择"),
                "enrolled_count": sum(r["status"] == "enrolled" for r in records.values()),
                "completed_count": sum(r["status"] == "completed" for r in records.values()),
                "can_enroll": not code and status != "enrolled", "can_cancel": status == "enrolled",
                "can_attend": not attend_code and status == "enrolled", "reason": reason, "attend_reason": attend_reason})
    for sid, records in ledger(state).get("records", {}).items():
        if actor_id in records:
            row = session(state, sid)
            history.append({"session_id": sid, "name": row["name"], "day": row["day"], "phase": row["phase"],
                            "status": records[actor_id]["status"], "status_text": STATUS_TEXT[records[actor_id]["status"]],
                            "result": visible_result(records[actor_id].get("result", {}))})
    courses = [course_progress(state, actor_id, key) for key, row in ledger(state).get("definitions", {}).items() if row.get("course")]
    return {"offers": offers, "history": sorted(history, key=lambda r: (r["day"], PHASE_IDS.index(r["phase"])), reverse=True)[:30], "courses": courses, "event_board": event_board(state)}


def life_invariant(state):
    data = ledger(state)
    if not data:
        return
    if data.get("version") != 1 or not isinstance(data.get("definitions"), dict) or not isinstance(data.get("records"), dict):
        yield "invalid campus life ledger"
        return
    from simulation.domain.campus import PERSONALITY_NAMES
    for key, row in data["definitions"].items():
        if (not isinstance(row, dict) or row.get("id") != key or not isinstance(row.get("name"), str)
                or row.get("location_id") not in state.places or row.get("phase") not in PHASE_IDS
                or row.get("trait") not in PERSONALITY_NAMES
                or not isinstance(row.get("weekdays"), list) or not row["weekdays"]
                or any(type(d) is not int or not 0 <= d <= 6 for d in row["weekdays"])
                or not isinstance(row.get("roles"), list) or not row["roles"] or not set(row["roles"]) <= {"student", "staff"}
                or not isinstance(row.get("required_items"), dict)
                or any(item not in state.inventories.get("catalog", {}) or type(count) is not int or count <= 0
                       for item, count in row.get("required_items", {}).items())):
            yield "invalid campus life definition"
            return
    reserved_slots = set()
    for sid, records in data["records"].items():
        row = session(state, sid)
        if not row or not isinstance(records, dict):
            yield "invalid campus life session"
            continue
        for actor_id, record in records.items():
            if actor_id not in state.population or not isinstance(record, dict) or record.get("status") not in STATUS_TEXT:
                yield "invalid campus life participant"
            elif not isinstance(record.get("history"), list) or type(record.get("enrolled_day")) is not int or record.get("enrolled_phase") not in PHASE_IDS:
                yield "invalid campus life participation history"
            elif record["status"] == "completed" and (record.get("completed_day"), record.get("completed_phase")) != (row["day"], row["phase"]):
                yield "invalid campus life completion clock"
            elif record["status"] == "enrolled":
                slot = (actor_id, row["day"], row["phase"])
                if slot in reserved_slots:
                    yield "duplicate campus life reservation"
                reserved_slots.add(slot)
    from simulation.systems.campus_study_work import study_work_invariant
    yield from study_work_invariant(state)
    from simulation.systems.campus_events import events_invariant
    yield from events_invariant(state)
