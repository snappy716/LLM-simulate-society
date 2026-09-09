"""Contact-led inquiries: public rendezvous, physical checking, private reports."""
from copy import deepcopy

from simulation.systems.transactions import TransactionOutcome
from simulation.systems.time import consume_major_action
from simulation.systems.campus_tasks import phase_index, _history, complete_assigned_task
from simulation.systems.campus_messaging import are_phone_contacts, phone_available, append_structured_phone_message
from simulation.systems.campus_vitals import actor_layer
from simulation.systems.campus_intelligence import create_campus_claim


from simulation.systems.campus_contact_leads import CHECK_POINTS, contact_check_options, inquiry_basis
CONTACT_ACTIONS = {"REQUEST_CONTACT_CHECK", "CHECK_CONTACT_LOCATION"}


def is_contact_task(task):
    return task.get("resolution_kind") == "contact_inquiry"


def _ledger(state):
    return state.situations.setdefault("contact_inquiries", {"schema_version": 1, "sequence": 0, "cases": {}})


def _gap(state, sender, target):
    return state.cognition["messaging"].get("contact_gaps", {}).get(sender + ">" + target, {})


def contact_report_valid(state, actor_id, task):
    case = state.situations.get("contact_inquiries", {}).get("cases", {}).get(task.get("inquiry_id"), {})
    report = case.get("report") or {}
    claim = state.knowledge["claims"].get(report.get("claim_id"), {})
    return bool(case.get("task_id") == task.get("task_id") and report.get("actor_id") == actor_id
        and actor_id not in {case.get("issuer_id"), case.get("target_id")}
        and type(report.get("seen")) is bool and claim.get("subject_id") == case.get("target_id")
        and claim.get("object_id") == case.get("location_id") and claim.get("evidence_kind") == "contact_observation"
        and claim.get("predicate") == ("contact_seen_at" if report.get("seen") else "contact_not_seen_at")
        and claim.get("source_context", {}).get("day") == report.get("day")
        and claim.get("source_context", {}).get("phase") == report.get("phase")
        and report.get("location_id") == task.get("scene_id") and claim.get("source_context", {}).get("source_id") == case.get("case_id")
        and report.get("claim_id") in state.knowledge["beliefs_by_actor"].get(actor_id, {}))


def make_contact_inquiry_handler(economy_policy, messaging_policy):
    def handle(context, command):
        state, actor_id = context.state, command.actor_id
        if actor_id not in state.population or (command.source == "player" and actor_id != "player"):
            return TransactionOutcome(False, False, "actor_not_authorized", "不能代替其他角色进行寻访。")
        if command.issued_day != state.clock.day or command.issued_phase != state.clock.phase:
            return TransactionOutcome(False, False, "command_clock_mismatch", "寻访请求所属时段已过期。")
        if not phone_available(state, actor_id) or actor_layer(state, actor_id) != "surface":
            return TransactionOutcome(False, False, "actor_unavailable", "请在表世界可以正常行动时处理寻访。")
        if command.action_id == "REQUEST_CONTACT_CHECK":
            target, location = command.parameters.get("target_id"), command.parameters.get("location_id", "south_gate")
            if not isinstance(target, str) or target not in state.population or actor_id == target:
                return TransactionOutcome(False, False, "invalid_contact", "联系人不存在。")
            if location not in CHECK_POINTS:
                return TransactionOutcome(False, False, "invalid_check_point", "只能选择公开会面点，不能查询宿舍或隐藏位置。")
            gap = _gap(state, actor_id, target)
            if not are_phone_contacts(state, actor_id, target) or gap.get("status") != "awaiting":
                return TransactionOutcome(False, False, "contact_attempt_required", "需要本人真实的尚未回应记录；已恢复联系不再发起寻访。")
            existing = state.situations.get("contact_inquiries", {}).get("cases", {}).values()
            previous = None
            for case in existing:
                if (case["issuer_id"], case["target_id"], case["episode_tick"]) != (actor_id, target, gap["first_tick"]):
                    continue
                if case["status"] in {"open", "observed"} or case["location_id"] == location:
                    return TransactionOutcome(False, True, "already_requested", "已有待处理寻访，或本次联系经历已经核对过该点。", payload={"task_id": case["task_id"]})
                if case["status"] == "not_observed":
                    previous = case
            ledger = _ledger(state)
            ledger["sequence"] += 1
            case_id = f"inquiry:{ledger['sequence']:06d}"
            task_id = "surface:" + case_id
            case = {"case_id": case_id, "task_id": task_id, "issuer_id": actor_id, "target_id": target,
                "episode_tick": gap["first_tick"], "source_message_id": gap["message_id"], "location_id": location,
                "status": "open", "report": None, "created_day": state.clock.day,
                "previous_case_id": previous["case_id"] if previous else None,
                "decision_basis": inquiry_basis(state, actor_id, target, location),
                "source_claim_id": previous["report"]["claim_id"] if previous else None}
            task = {"task_id": task_id, "template_id": "contact_check", "forum": "surface", "world_layer": "surface",
                "issuer_id": actor_id, "title": "公共会面点寻访", "description": "发布者尚未联系上一位联系人，请在指定公共地点留意；不是已确认失踪。具体对象仅向承接者提供。",
                "objective": "实际到达指定地点，核对是否见到联系人并提交带时地的观察。", "action_id": "CHECK_CONTACT_LOCATION",
                "activity_id": "PERSONAL_ACTIVITY", "allowed_phases": list(state.places[location]["open_phases"]),
                "scene_id": location, "execution_region_id": state.places[location].get("region_id") or location,
                "created_day": state.clock.day, "expires_day": state.clock.day + 1, "state": "open", "assignee_id": None,
                "lock_revision": 0, "viewer_ids": [], "considering_ids": [], "helper_ids": [], "required_skill_ids": [],
                "required_item_ids": [], "reward": {}, "tags": ["social", "investigation", "volunteer"],
                "preferred_college_ids": [], "preferred_club_ids": [], "preferred_assignee_id": None, "organization_id": None,
                "social_consequences": {}, "follow_up_template_ids": [], "chain_parent_template_id": None,
                "npc_claim_phase_index": phase_index(state.clock.day, state.clock.phase), "npc_execute_after_phase_index": None,
                "origin_kind": "contact_attempt", "origin_summary": "由发布者本人实际的未回应联系产生，位置是预选公共会面点。",
                "resolution_kind": "contact_inquiry", "inquiry_id": case_id,
                "history": [_history(state.clock.day, state.clock.phase, "published", "发布者请求公共地点寻访，尚未确认失踪。") ]}
            ledger["cases"][case_id] = case
            if previous:
                task["origin_summary"] = "上一份实地报告未见到联系人，发布者请求核对另一个公共会面点；仍未确认失踪。"
            if case["decision_basis"]["kind"] == "known_evidence":
                task["origin_summary"] += " 发布者参考了本人掌握的地点记录，具体线索不公开。"
            state.tasks[task_id] = task
            state.forums["surface"]["published_total"] += 1
            context.emit("CONTACT_INQUIRY_PUBLISHED", "发布者因真实未回应联系发布了一项公共地点寻访。", actor_ids=[actor_id],
                scene_id=location, visibility="public", knowledge_tags=["forum", "inquiry"], payload={"task_id": task_id})
            return TransactionOutcome(True, True, "success", "寻访已发布；没有确认失踪，也没有公开对方身份或位置。", commit=True,
                payload={"task_id": task_id, "action_class": "free"})
        if command.action_id != "CHECK_CONTACT_LOCATION":
            return TransactionOutcome(False, False, "unsupported_action", "不支持的寻访操作。")
        task_id = command.parameters.get("task_id")
        task = state.tasks.get(task_id, {}) if isinstance(task_id, str) else {}
        if not is_contact_task(task) or task.get("state") != "locked" or task.get("assignee_id") != actor_id:
            return TransactionOutcome(False, False, "task_not_owned", "需要本人持有的寻访委托。")
        if type(command.parameters.get("expected_task_revision")) is not int or command.parameters["expected_task_revision"] != task["lock_revision"]:
            return TransactionOutcome(False, False, "task_revision_conflict", "寻访委托状态已变化。")
        case = _ledger(state)["cases"][task["inquiry_id"]]
        gap = _gap(state, case["issuer_id"], case["target_id"])
        if gap.get("status") == "contact_resumed" or gap.get("first_tick") != case["episode_tick"]:
            return TransactionOutcome(False, False, "contact_already_resumed", "发布者已恢复联系，不再消耗行动核对。")
        if actor_id in {case["issuer_id"], case["target_id"]}:
            return TransactionOutcome(False, False, "independent_checker_required", "需要独立的承接者核对，不能替自己出具寻访报告。")
        if state.population[actor_id]["current_location_id"] != case["location_id"]:
            return TransactionOutcome(False, False, "task_location_required", "必须实际进入指定公共会面点，不能在区域入口远程完成。")
        if state.clock.phase not in task["allowed_phases"] or state.clock.day > task["expires_day"]:
            return TransactionOutcome(False, False, "task_time_unavailable", "当前不在寻访执行时段内。")
        spent = consume_major_action(state, economy_policy, command)
        if not spent.success:
            return TransactionOutcome(False, False, spent.code, spent.message)
        from simulation.systems.campus_night_sites import captive_site
        target = case["target_id"]
        seen = (state.population[target]["current_location_id"] == case["location_id"]
                and actor_layer(state, target) == "surface" and not captive_site(state, target))
        summary = f"第 {state.clock.day} 天 {state.clock.phase}，在{state.places[case['location_id']]['name']}" + (
            "见到了要找的联系人；这不证明其身体状况或此前经历。" if seen else "这次没有见到要找的联系人；不能据此断定失踪或其所在位置。")
        claim = create_campus_claim(state, subject_id=target, predicate="contact_seen_at" if seen else "contact_not_seen_at",
            object_id=case["location_id"], summary=summary, secrecy=75, known_by=[actor_id], evidence_kind="contact_observation")
        claim["source_context"] = {"source_id": case["case_id"], "source_kind": "contact_observation", "location_id": case["location_id"],
            "layer": "surface", "day": state.clock.day, "phase": state.clock.phase}
        # Direct dated report to the issuer, preserving the actual observer identity.
        belief = deepcopy(state.knowledge["beliefs_by_actor"][actor_id][claim["claim_id"]])
        belief.update(source_actor_id=actor_id, source_kind="contact_report", transmission_count=1)
        state.knowledge["beliefs_by_actor"][case["issuer_id"]][claim["claim_id"]] = belief
        case["report"] = {"actor_id": actor_id, "location_id": case["location_id"], "day": state.clock.day, "phase": state.clock.phase,
            "claim_id": claim["claim_id"], "seen": seen, "summary": summary}
        case["status"] = "observed" if seen else "not_observed"
        if not complete_assigned_task(context, actor_id, {"task_id": task_id, "contact_report": True}):
            raise RuntimeError("verified contact report could not complete its task")
        if are_phone_contacts(state, actor_id, case["issuer_id"]):
            append_structured_phone_message(context, actor_id, case["issuer_id"], summary, messaging_policy, source="rule")
        context.emit("CONTACT_INQUIRY_REPORTED", summary, actor_ids=[actor_id], target_ids=[case["issuer_id"]], visibility="private",
            scene_id=case["location_id"], knowledge_tags=["inquiry", "evidence"], payload={"claim_id": claim["claim_id"], "task_id": task_id})
        return TransactionOutcome(True, True, "success", summary, commit=True,
            payload={"contact_report": deepcopy(case["report"]), "task_completed": True, "action_class": "major"})
    return handle


def advance_contact_inquiries(context, handler):
    state = context.state
    published, withdrawn = 0, 0
    for case in state.situations.get("contact_inquiries", {}).get("cases", {}).values():
        if case["status"] != "open":
            continue
        task = state.tasks[case["task_id"]]
        gap = _gap(state, case["issuer_id"], case["target_id"])
        if task["state"] == "expired":
            case["status"] = "expired"
        elif gap.get("status") == "contact_resumed" or gap.get("first_tick") != case["episode_tick"]:
            # Administrative withdrawal, not fabricated completion, blame or reward.
            assignee = task.get("assignee_id")
            if assignee:
                state.population[assignee].pop("active_forum_task_id", None)
            task.update(state="expired", assignee_id=None, lock_revision=task["lock_revision"] + 1)
            task["history"].append(_history(state.clock.day, state.clock.phase, "withdrawn", "发布者已恢复联系，寻访撤回；未处罚承接者。"))
            case["status"] = "withdrawn"
            context.emit("CONTACT_INQUIRY_WITHDRAWN", "联系已恢复，寻访委托撤回，不计完成或失约。", actor_ids=[case["issuer_id"]],
                visibility="public", knowledge_tags=["forum", "inquiry"], payload={"task_id": task["task_id"]})
            withdrawn += 1
    from simulation.actions.commands import SimulationCommand
    for gap in state.cognition["messaging"].get("contact_gaps", {}).values():
        sender = gap["sender_id"]
        if sender == "player" or gap["status"] != "awaiting" or gap["distinct_phases"] < 2:
            continue
        # A repeated real contact concern, never the secret list of captives.
        for option in contact_check_options(state, sender, gap["receiver_id"]):
            if not option["available"]:
                continue
            location = option["location_id"]
            outcome = handler(context, SimulationCommand(f"inquiry-auto:{sender}:{location}:{state.revision}", sender, "REQUEST_CONTACT_CHECK", state.revision,
                parameters={"target_id": gap["receiver_id"], "location_id": location}, issued_day=state.clock.day,
                issued_phase=state.clock.phase, source="rule"))
            if outcome.code == "success":
                published += 1
                break
    return {"contact_inquiries_published": published, "contact_inquiries_withdrawn": withdrawn}


def contact_inquiry_view(state, viewer, task):
    if not is_contact_task(task):
        return {}
    case = state.situations["contact_inquiries"]["cases"][task["inquiry_id"]]
    view = {"status": case["status"], "rule_note": "公共地点实地核对消耗 1 次主要行动，无金钱奖励；未见不等于失踪。"}
    if viewer in {case["issuer_id"], task.get("assignee_id")}:
        view.update(target_name=state.population[case["target_id"]]["display_name"], report=deepcopy(case["report"]))
    if viewer == case["issuer_id"]:
        view["decision_basis"] = deepcopy(case.get("decision_basis"))
    return view


def contact_inquiries_invariant(state):
    ledger = state.situations.get("contact_inquiries")
    if ledger is None:
        return [] if not any(is_contact_task(t) for t in state.tasks.values()) else ["contact tasks missing ledger"]
    try:
        if ledger["schema_version"] != 1 or type(ledger["sequence"]) is not int:
            return ["invalid contact inquiry schema"]
        for key, case in ledger["cases"].items():
            task = state.tasks[case["task_id"]]
            if (key != case["case_id"] or task.get("inquiry_id") != key or not is_contact_task(task)
                    or case["issuer_id"] not in state.population or case["target_id"] not in state.population
                    or case["issuer_id"] == case["target_id"] or task["issuer_id"] != case["issuer_id"]
                    or case["location_id"] not in CHECK_POINTS or task["scene_id"] != case["location_id"]
                    or case["status"] not in {"open", "observed", "not_observed", "expired", "withdrawn"}):
                return ["invalid contact inquiry"]
            if task["state"] == "completed" and not contact_report_valid(state, task["assignee_id"], task):
                return ["contact inquiry completed without actual report"]
            if (case["status"] in {"observed", "not_observed"}) != (task["state"] == "completed"):
                return ["contact inquiry report status differs from task"]
            if case["report"] and case["status"] != ("observed" if case["report"]["seen"] else "not_observed"):
                return ["contact inquiry observation outcome mismatch"]
            if case.get("previous_case_id"):
                previous = ledger["cases"][case["previous_case_id"]]
                if (previous["status"] != "not_observed" or previous["issuer_id"] != case["issuer_id"]
                        or previous["target_id"] != case["target_id"] or previous["episode_tick"] != case["episode_tick"]
                        or previous["report"]["claim_id"] != case["source_claim_id"]):
                    return ["contact inquiry follow-up has invalid source"]
        for task in state.tasks.values():
            if is_contact_task(task) and ledger["cases"][task["inquiry_id"]]["task_id"] != task["task_id"]:
                return ["contact inquiry task references another case"]
        return []
    except (KeyError, TypeError, AttributeError):
        return ["malformed contact inquiry ledger"]
