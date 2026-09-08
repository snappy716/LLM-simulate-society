"""Aftermath of actual stranded actors, with voluntary, source-bound reports.

No public missing-person diagnosis, secret location disclosure, free healing,
invented contacts or automatic promise fulfillment.
"""
from simulation.actions.commands import SimulationCommand
from simulation.systems.transactions import TransactionOutcome
from simulation.systems.campus_vitals import actor_layer, battle_locked, needs_recovery
from simulation.systems.campus_messaging import are_phone_contacts, append_structured_phone_message
from simulation.systems.campus_social import DEFAULT_RELATIONSHIP
from simulation.systems.campus_intelligence import create_campus_claim


def _ledger(state):
    return state.situations.setdefault("campus_welfare", {"schema_version": 1, "cases": {}})


def sync_welfare_cases(state):
    ledger = _ledger(state)
    for site in state.situations.get("night_sites", {}).get("sites", {}).values():
        if not site.get("victim_id") or site["site_id"] in ledger["cases"]:
            continue
        # Earlier saves do not acquire a backlog of historical punishments.
        if site["status"] in {"resolved", "expired"} and site["expires_day"] < state.clock.day - 1:
            continue
        ledger["cases"][site["site_id"]] = {
            "case_id": site["site_id"], "actor_id": site["victim_id"], "started_day": site["created_day"],
            "status": "unconfirmed", "reports": {}, "last_auto_day": 0,
            "assistance_id": None, "history": [],
        }
    return ledger


def _willing(state, subject, listener):
    relation = {**DEFAULT_RELATIONSHIP, **state.relationships.get(subject, {}).get(listener, {})}
    return relation["trust"] >= 35 and relation["suspicion"] < 60 and relation["conflict"] < 50


def _available(state, actor):
    return actor_layer(state, actor) == "surface" and not battle_locked(state, actor)


def welfare_view(state, viewer="player"):
    rows = []
    for case in state.situations.get("campus_welfare", {}).get("cases", {}).values():
        report = case["reports"].get(viewer)
        if report:
            rows.append({"npc_id": case["actor_id"], "name": state.population[case["actor_id"]]["display_name"],
                **{k: report[k] for k in ("day", "phase", "status", "summary", "claim_id")}})
    return rows


def _report(context, case, listener, messaging_policy, *, initiated=False):
    state, subject = context.state, case["actor_id"]
    available = _available(state, subject)
    if available and not _willing(state, subject, listener):
        return TransactionOutcome(False, False, "report_withheld", "对方暂时不愿谈个人近况，请尊重其意愿。")
    status = "unconfirmed" if not available else "needs_care" if needs_recovery(state.population[subject]) else "recovered"
    old = case["reports"].get(listener, {})
    if old.get("day") == state.clock.day and old.get("phase") == state.clock.phase and old.get("status") == status:
        return TransactionOutcome(True, True, "already_checked", old["summary"], payload={"report": old})
    summary = {
        "unconfirmed": "这次联系尚未得到回应，暂时无法确认近况；这不证明对方失踪或遭遇异常。",
        "needs_care": "我已经能够正常联系，但身体或精力还没恢复，可能需要休息或物资支持。",
        "recovered": "我现在能够正常联系，身体和精力已经恢复；谢谢你关心。",
    }[status]
    if are_phone_contacts(state, subject, listener):
        if not initiated:
            append_structured_phone_message(context, listener, subject, "最近还好吗？方便时可以告诉我是否平安、是否需要帮助。", messaging_policy, source="welfare_check")
        if available:
            append_structured_phone_message(context, subject, listener, summary, messaging_policy, source="welfare_report")
    claim_id = None
    if available:
        claim = create_campus_claim(state, subject_id=subject, predicate="voluntary_welfare_report", object_id=subject,
            summary=summary, secrecy=50, known_by=[subject, listener], evidence_kind="firsthand_statement")
        claim["source_context"] = {"location_id": None, "layer": "surface", "source_kind": "voluntary_report",
            "source_id": claim["claim_id"], "day": state.clock.day, "phase": state.clock.phase}
        claim_id = claim["claim_id"]
        case["status"] = status
    report = {"day": state.clock.day, "phase": state.clock.phase, "status": status, "summary": summary, "claim_id": claim_id}
    case["reports"][listener] = report
    case["history"] = [*case["history"], {"listener_id": listener, **report}][-24:]
    context.emit("CAMPUS_WELFARE_REPORTED", summary, actor_ids=[subject], target_ids=[listener], visibility="private",
        knowledge_tags=["social", "welfare"], payload={"outcome": status, "claim_id": claim_id})
    return TransactionOutcome(True, True, status, summary, commit=True, payload={"report": report})


def make_welfare_handler(messaging_policy):
    def handle(context, command):
        state, actor = context.state, command.actor_id
        def fail(code, text):
            return TransactionOutcome(False, False, code, text)
        if actor not in state.population or (command.source == "player" and actor != "player"):
            return fail("actor_not_authorized", "不能代替其他人联系。")
        if command.issued_day != state.clock.day or command.issued_phase != state.clock.phase:
            return fail("command_clock_mismatch", "本次询问时段已经过期。")
        target = command.parameters.get("npc_id")
        if not isinstance(target, str) or target not in state.population or target == actor:
            return fail("unknown_npc", "请选择其他人物。")
        if not _available(state, actor):
            return fail("not_available", "请在表世界且未参战时确认近况。")
        colocated = _available(state, target) and state.population[actor]["current_location_id"] == state.population[target]["current_location_id"]
        if not colocated and not are_phone_contacts(state, actor, target):
            return fail("contact_required", "需要当面或已有手机联系方式。")
        ledger = sync_welfare_cases(state)
        cases = [c for c in ledger["cases"].values() if c["actor_id"] == target]
        if not cases:
            return fail("no_follow_up", "目前没有需要回访的相关记录；可以继续普通聊天。")
        if cases[-1]["status"] == "recovered":
            old = cases[-1]["reports"].get(actor)
            if old:
                return TransactionOutcome(True, True, "follow_up_closed", "此前这次回访已确认恢复；新的情况请继续普通交谈。", payload={"report": old})
            return fail("no_follow_up", "目前没有需要回访的相关记录；可以继续普通聊天。")
        return _report(context, cases[-1], actor, messaging_policy)
    return handle


def advance_welfare(context, messaging_policy):
    """The affected person knows their own experience; outsiders are not omniscient."""
    state = context.state
    ledger = sync_welfare_cases(state)
    reported, requested = 0, 0
    for case in ledger["cases"].values():
        subject = case["actor_id"]
        site = state.situations["night_sites"]["sites"][case["case_id"]]
        if (case["status"] == "recovered" or case["last_auto_day"] == state.clock.day
                or site["status"] not in {"resolved", "expired"} or not _available(state, subject)):
            continue
        listeners = [n for n in state.population if n != subject and are_phone_contacts(state, subject, n)
            and _available(state, n) and _willing(state, subject, n)]
        listeners.sort(key=lambda n: (-state.relationships.get(subject, {}).get(n, {}).get("trust", 0), n))
        if not listeners:
            continue
        case["last_auto_day"] = state.clock.day
        # Update people already told, plus one existing trusted contact. No broadcast.
        listeners = list(dict.fromkeys([*(n for n in case["reports"] if n in listeners), listeners[0]]))[:4]
        for listener in listeners:
            _report(context, case, listener, messaging_policy, initiated=True)
            reported += 1
        from simulation.systems.campus_assistance import needs_item, make_assistance_handler
        if (not case["assistance_id"] and needs_item(state, subject, "bandage_roll")
                and state.population[subject]["wealth"] < state.inventories["catalog"]["bandage_roll"]["base_price"]):
            outcome = make_assistance_handler(messaging_policy)(context, SimulationCommand(
                f"welfare-help:{case['case_id']}:{state.clock.day}", subject, "REQUEST_MATERIAL_HELP", state.revision,
                parameters={"helper_id": listeners[0], "item_id": "bandage_roll"}, issued_day=state.clock.day,
                issued_phase=state.clock.phase, source="rule"))
            if outcome.success:
                case["assistance_id"] = outcome.payload["request"]["request_id"]
                requested += 1
    return {"welfare_reports": reported, "welfare_material_requests": requested}


def welfare_invariant(state):
    ledger = state.situations.get("campus_welfare")
    if ledger is None:
        return
    try:
        if ledger["schema_version"] != 1:
            yield "invalid welfare schema"
        for key, case in ledger["cases"].items():
            site = state.situations["night_sites"]["sites"][key]
            if (case["case_id"] != key or case["actor_id"] != site["victim_id"]
                    or case["actor_id"] not in state.population or case["status"] not in {"unconfirmed", "needs_care", "recovered"}
                    or not 0 <= case["last_auto_day"] <= state.clock.day or len(case["history"]) > 24):
                yield "invalid welfare case"
            for listener, report in case["reports"].items():
                if listener not in state.population or not 1 <= report["day"] <= state.clock.day or report["phase"] not in {"morning", "afternoon", "evening", "late_night"}:
                    yield "invalid welfare report"
                if report["claim_id"] and report["claim_id"] not in state.knowledge["claims"]:
                    yield "missing welfare claim"
    except (KeyError, TypeError, AttributeError, ValueError):
        yield "malformed welfare ledger"
