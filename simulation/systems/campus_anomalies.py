"""Fictional moon afterimages, grounded in actual incidents and voluntary reports.

Internal shell/core/coherence are not diagnoses or omniscient UI statistics.
Listening is free; a consented grounding activity costs both participants one
major action. Ordinary conversation, personality and unanswered calls never
create a case. Night interventions will consume this same persistent ledger.
"""
from dataclasses import replace

from simulation.actions.commands import SimulationCommand
from simulation.domain.action_economy import build_action_economy_policy
from simulation.systems.campus_departures import active_departure
from simulation.systems.campus_growth import mastery_by_topic
from simulation.systems.campus_intelligence import create_campus_claim
from simulation.systems.campus_messaging import are_phone_contacts
from simulation.systems.campus_night_sites import captive_site
from simulation.systems.campus_social import DEFAULT_RELATIONSHIP
from simulation.systems.campus_tasks import phase_index
from simulation.systems.campus_vitals import actor_layer, battle_locked
from simulation.systems.time import consume_major_action
from simulation.systems.transactions import TransactionOutcome

ANOMALY_ACTIONS = ("ASK_ANOMALY_EXPERIENCE", "SUPPORT_ANOMALY")
INITIAL = {"shell": 30, "core": 60, "coherence": 60}
SUPPORT_DELTA = {"shell": 10, "core": 20, "coherence": 20}


def sync_anomaly_cases(context):
    state = context.state
    ledger = state.situations.setdefault("campus_anomalies", {"schema_version": 1, "cases": {}})
    for site in state.situations.get("night_sites", {}).get("sites", {}).values():
        # One concrete episode per person, no old-save historical backlog.
        if (not site.get("victim_id") or site["status"] not in {"resolved", "expired"}
                or site["expires_day"] < state.clock.day - 1 or site["site_id"] in ledger["cases"]
                or any(c["actor_id"] == site["victim_id"] and c["status"] != "resolved" for c in ledger["cases"].values())):
            continue
        task = state.tasks[site["task_id"]]
        topic = task.get("enemy_archetype_id")
        if topic not in state.metadata.get("campus_combat", {}).get("enemy_archetypes", {}):
            continue
        case = {"case_id": site["site_id"], "actor_id": site["victim_id"], "source_task_id": site["task_id"],
            "topic_id": topic, "created_day": state.clock.day, "revision": 0, "status": "unsettled",
            **INITIAL, "reports": {}, "history": [], "last_support_day": 0}
        ledger["cases"][site["site_id"]] = case
        context.emit("CAMPUS_ANOMALY_LINKED", "脱离真实月相现场后，仍有待本人确认的月相残留体验。",
            actor_ids=[case["actor_id"]], visibility="private", knowledge_tags=["anomaly"],
            payload={"case_id": case["case_id"], "source_task_id": site["task_id"]})
    return ledger


def _available(state, actor):
    return (actor_layer(state, actor) == "surface" and not battle_locked(state, actor)
            and not captive_site(state, actor) and state.population[actor]["vitals"]["health"] > 0)


def _consents(state, subject, listener, threshold=35):
    relation = {**DEFAULT_RELATIONSHIP, **state.relationships.get(subject, {}).get(listener, {})}
    return relation["trust"] >= threshold and relation["suspicion"] < 60 and relation["conflict"] < 50


def _support_problem(state, case, listener):
    subject = case["actor_id"]
    if case["status"] == "resolved":
        return "already_resolved", "这次月相残留已稳定，不需要重复处理。"
    if state.clock.phase not in {"morning", "afternoon"}:
        return "daytime_required", "现实锚定活动安排在上午或下午；普通交谈不受此限制。"
    if not all(_available(state, who) for who in (listener, subject)):
        return "not_available", "双方需要在表世界、能够活动且不在战斗或受困中。"
    location = state.population[listener]["current_location_id"]
    if location != state.population[subject]["current_location_id"]:
        return "same_location_required", "需要当面共同完成活动；电话了解情况不等于已经陪伴。"
    place = state.places[location]
    if place.get("open_phases") and state.clock.phase not in place["open_phases"]:
        return "location_closed", "此处尚未开放，请选择双方可以到达的开放地点。"
    if not _consents(state, subject, listener, 50):
        return "support_declined", "对方暂时不愿一起做这项活动，请尊重其决定。"
    if case["last_support_day"] == state.clock.day:
        return "support_today_complete", "今天已进行过一次现实锚定，需要时间消化；可以继续普通交谈。"
    if mastery_by_topic(state, listener).get(case["topic_id"], 0) < 20:
        return "knowledge_required", "需要先将对应现象的理解提升至 20；可通过阅读和实际案例学习。"
    for who in (listener, subject):
        from simulation.systems.campus_anomaly_meetings import reserved_meeting
        meeting = reserved_meeting(state, who)
        if meeting and (meeting["case_id"] != case["case_id"] or meeting["helper_id"] != listener
                or location != meeting["location_id"]):
            return "major_action_reserved", "有人已为其他支持预约预留行动，请按约赴会或先取消。"
        if active_departure(state, who) or state.population[who].get("active_forum_task_id"):
            return "participant_committed", "有人已有委托或出击承诺，请先处理原有安排。"
        if state.action_economy["actors"][who]["major_remaining"] <= 0:
            return "major_action_exhausted", "双方各需要一次剩余主要行动。"
    report = case["reports"].get(listener, {})
    if (report.get("day"), report.get("phase"), report.get("revision")) != (state.clock.day, state.clock.phase, case["revision"]):
        return "fresh_report_required", "请先重新听取本人此刻的体验，再决定是否一起活动。"
    claim_id = report.get("claim_id")
    belief = state.knowledge.get("beliefs_by_actor", {}).get(listener, {}).get(claim_id, {})
    if belief.get("confidence", 0) < .5 or belief.get("distortion", 1) > .35:
        return "reliable_report_required", "目前掌握的本人陈述已不足以作为可靠依据。"
    return None


def anomaly_view(state, viewer="player"):
    rows = []
    for case in state.situations.get("campus_anomalies", {}).get("cases", {}).values():
        report = case["reports"].get(viewer)
        if not report:
            continue
        stale = (report["day"], report["phase"], report["revision"]) != (state.clock.day, state.clock.phase, case["revision"])
        problem = ("fresh_report_required", "这是过去的本人陈述；请重新确认近况，不据此推断当前状态。") if stale else _support_problem(state, case, viewer)
        rows.append({"npc_id": case["actor_id"], "case_id": case["case_id"], "topic_id": case["topic_id"],
            "report": dict(report), "can_support": problem is None,
            "support_hint": problem[1] if problem else "本人同意后，共同做现实锚定活动；双方各消耗一次主要行动，不推进时段。"})
    return rows


def make_anomaly_handler():
    def handle(context, command):
        state, actor, params = context.state, command.actor_id, command.parameters
        def fail(code, message):
            return TransactionOutcome(False, False, code, message)
        if actor not in state.population or (command.source == "player" and actor != "player"):
            return fail("actor_not_authorized", "不能代替其他人物行动。")
        if (command.issued_day, command.issued_phase) != (state.clock.day, state.clock.phase):
            return fail("command_clock_mismatch", "本次行动的时段已经过期。")
        target = params.get("npc_id")
        if not isinstance(target, str) or target not in state.population or target == actor:
            return fail("unknown_npc", "请选择其他人物。")
        if not all(_available(state, who) for who in (actor, target)):
            return fail("not_available", "当前无法进行本人体验确认；暂未回应不能作为异常证据。")
        colocated = state.population[actor]["current_location_id"] == state.population[target]["current_location_id"]
        if not colocated and not are_phone_contacts(state, actor, target):
            return fail("contact_required", "需要当面交流或已有手机联系方式。")
        if not _consents(state, target, actor):
            return fail("report_withheld", "对方不愿谈这段私人体验。")
        cases = [c for c in state.situations.get("campus_anomalies", {}).get("cases", {}).values() if c["actor_id"] == target]
        if not cases:
            return fail("no_reported_episode", "目前没有可以确认的月相经历；普通压力和沉默不代表异常。")
        case = cases[-1]
        if command.action_id == "ASK_ANOMALY_EXPERIENCE":
            report = case["reports"].get(actor)
            if report and (report["day"], report["phase"], report["revision"]) == (state.clock.day, state.clock.phase, case["revision"]):
                return TransactionOutcome(True, True, "already_heard", report["summary"], payload={"report": report})
            summary = ("那次月相经历已经能够与眼前生活区分开，我愿意继续正常生活。" if case["status"] == "resolved"
                else "旧现场的残像已经被切断，但那段经历仍困扰着我；外壳消失不等于我的心结已解开。" if case["history"] and case["history"][-1]["route"] == "night_containment"
                else "一起核对日常经历让我更能区分月相残留与眼前生活，但还需要时间巩固。" if case["status"] == "easing"
                else "脱离那次月相现场后，有些影像仍会重复出现。我愿意先讲自己的体验，不希望被贴上诊断标签。")
            claim = create_campus_claim(state, subject_id=target, predicate="voluntary_moon_experience", object_id=target,
                summary=summary, secrecy=75, known_by=[target, actor], evidence_kind="firsthand_statement")
            claim["source_context"] = {"source_kind": "voluntary_moon_report", "source_id": case["case_id"],
                "location_id": None, "layer": "surface", "day": state.clock.day, "phase": state.clock.phase}
            state.knowledge["beliefs_by_actor"][actor][claim["claim_id"]].update(
                source_actor_id=target, upstream_source_actor_id=target, transmission_count=1)
            report = {"day": state.clock.day, "phase": state.clock.phase, "revision": case["revision"],
                "summary": summary, "claim_id": claim["claim_id"]}
            case["reports"][actor] = report
            context.emit("CAMPUS_ANOMALY_HEARD", summary, actor_ids=[target], target_ids=[actor], visibility="private",
                knowledge_tags=["anomaly", "evidence"], payload={"claim_id": claim["claim_id"]})
            return TransactionOutcome(True, True, "experience_heard", summary, commit=True, payload={"report": report})
        if command.action_id != "SUPPORT_ANOMALY":
            return fail("unsupported_anomaly_action", "不支持这项行动。")
        if (params.get("case_id") != case["case_id"] or type(params.get("expected_case_revision")) not in {int, float}
                or params["expected_case_revision"] != case["revision"]):
            return fail("case_revision_conflict", "这段经历已有新的进展，请重新了解本人情况。")
        problem = _support_problem(state, case, actor)
        if problem:
            return fail(*problem)
        policy = build_action_economy_policy([{"id": key, **value} for key, value in state.action_economy["policy"]["phases"].items()])
        for who in (actor, target):
            cost = consume_major_action(state, policy, replace(command, actor_id=who))
            assert cost.success, cost.code  # Every rejection was checked before either cost.
        before = {key: case[key] for key in INITIAL}
        for key, amount in SUPPORT_DELTA.items():
            case[key] = max(0, case[key] - amount)
        case["revision"] += 1
        case["last_support_day"] = state.clock.day
        case["status"] = "resolved" if all(case[key] == 0 for key in INITIAL) else "easing"
        receipt = {"day": state.clock.day, "phase": state.clock.phase, "helper_id": actor,
            "location_id": state.population[actor]["current_location_id"],
            "claim_id": case["reports"][actor]["claim_id"], "before": before,
            "after": {key: case[key] for key in INITIAL}, "route": "day_support", "revision": case["revision"]}
        case["history"].append(receipt)
        from simulation.systems.campus_anomaly_meetings import complete_meeting
        complete_meeting(context, case, actor)
        # This addresses fictional afterimages, not hit points or clinical illness.
        message = "双方完成了一次现实锚定：核对本人愿意提供的经历并共同联系眼前生活。月相残留有所缓和；不是临床治疗，也未恢复生命或专注。"
        if case["status"] == "resolved":
            message = "经过持续的现实锚定，这次月相残留已稳定。没有强行战斗，也没有将普通情绪诊断为疾病。"
        context.emit("CAMPUS_ANOMALY_SUPPORTED", message, actor_ids=[actor, target], visibility="private",
            knowledge_tags=["anomaly", "support"], payload={"case_id": case["case_id"], "route": "day_support", "major_action_cost_each": 1})
        return TransactionOutcome(True, True, "anomaly_supported", message, commit=True)
    return handle


def advance_anomaly_support(context):
    """Rule execution at phase boundaries, never a new intraday model call."""
    state = context.state
    cases = sync_anomaly_cases(context)["cases"].values()
    if state.clock.phase not in {"morning", "afternoon"}:
        return {"anomaly_supports": 0}
    handler, count = make_anomaly_handler(), 0
    for case in cases:
        target = case["actor_id"]
        if case["status"] == "resolved" or case["last_support_day"] == state.clock.day or not _available(state, target):
            continue
        # Subject chooses an existing trusted, knowledgeable contact actually
        # present. No teleportation, invented contacts, or automatic player action.
        from simulation.systems.campus_anomaly_meetings import reserved_meeting
        if reserved_meeting(state, target):
            continue  # Reserved partners travel before the shared action settles.
        helpers = [who for who in state.population if who not in {"player", target} and _available(state, who) and not reserved_meeting(state, who)
            and are_phone_contacts(state, target, who) and _consents(state, target, who, 50)
            and state.population[who]["current_location_id"] == state.population[target]["current_location_id"]
            and mastery_by_topic(state, who).get(case["topic_id"], 0) >= 20]
        helpers.sort(key=lambda who: (-state.relationships.get(target, {}).get(who, {}).get("trust", 0), who))
        for helper in helpers:
            command = SimulationCommand(f"anomaly:{case['case_id']}:{state.clock.day}:{state.clock.phase}:{helper}",
                helper, "ASK_ANOMALY_EXPERIENCE", state.revision, parameters={"npc_id": target},
                issued_day=state.clock.day, issued_phase=state.clock.phase, source="rule")
            if not handler(context, command).success:
                continue
            result = handler(context, replace(command, action_id="SUPPORT_ANOMALY", parameters={"npc_id": target,
                "case_id": case["case_id"], "expected_case_revision": case["revision"]}))
            if result.success:
                count += 1
                break
    return {"anomaly_supports": count}


def anomalies_invariant(state):
    ledger = state.situations.get("campus_anomalies")
    if ledger is None:
        return []
    try:
        if ledger["schema_version"] != 1:
            return ["invalid anomaly schema"]
        active = set()
        for key, case in ledger["cases"].items():
            site = state.situations["night_sites"]["sites"][key]
            if (case["case_id"] != key or case["actor_id"] != site["victim_id"] or case["source_task_id"] != site["task_id"]
                    or site["status"] not in {"resolved", "expired"} or not 1 <= case["created_day"] <= state.clock.day
                    or case["topic_id"] != state.tasks[site["task_id"]]["enemy_archetype_id"]):
                return ["invalid anomaly source"]
            if case["status"] not in {"unsettled", "easing", "resolved"}:
                return ["invalid anomaly status"]
            if case["status"] != "resolved":
                if case["actor_id"] in active:
                    return ["duplicate active anomaly"]
                active.add(case["actor_id"])
            expected, last_day = dict(INITIAL), 0
            for revision, receipt in enumerate(case["history"], 1):
                if receipt.get("route") == "night_containment":
                    from simulation.systems.campus_anomaly_combat import night_receipt_valid
                    if (receipt["revision"] != revision or receipt["before"] != expected or expected["shell"] <= 0
                            or not case["created_day"] <= receipt["day"] <= state.clock.day
                            or receipt["phase"] not in {"evening", "late_night"} or not night_receipt_valid(state, case, receipt)):
                        return ["invalid anomaly containment receipt"]
                    expected = {**expected, "shell": 0, "coherence": max(0, expected["coherence"] - 20)}
                    if receipt["after"] != expected:
                        return ["invalid anomaly containment effect"]
                    continue
                claim = state.knowledge["claims"][receipt["claim_id"]]
                if (receipt["revision"] != revision or receipt["before"] != expected or receipt["route"] != "day_support"
                        or not last_day < receipt["day"] <= state.clock.day or receipt["phase"] not in {"morning", "afternoon"}
                        or claim["subject_id"] != case["actor_id"] or claim["predicate"] != "voluntary_moon_experience"
                        or claim["source_context"]["source_id"] != key or receipt["helper_id"] == case["actor_id"]
                        or (claim["source_context"]["day"], claim["source_context"]["phase"]) != (receipt["day"], receipt["phase"])
                        or receipt["claim_id"] not in state.knowledge["beliefs_by_actor"][receipt["helper_id"]]):
                    return ["invalid anomaly support receipt"]
                expected = {name: max(0, value - SUPPORT_DELTA[name]) for name, value in expected.items()}
                if receipt["after"] != expected:
                    return ["invalid anomaly support effect"]
                last_day = receipt["day"]
            if (case["revision"] != len(case["history"]) or case["last_support_day"] != last_day
                    or any(type(case[name]) is not int or case[name] != value for name, value in expected.items())
                    or case["status"] != ("resolved" if not any(expected.values()) else "easing" if case["history"] else "unsettled")):
                return ["invalid anomaly state"]
            for listener, report in case["reports"].items():
                claim = state.knowledge["claims"][report["claim_id"]]
                source = claim["source_context"]
                if (listener not in state.population or listener == case["actor_id"] or claim["subject_id"] != case["actor_id"]
                        or claim["predicate"] != "voluntary_moon_experience" or source["source_id"] != key
                        or (source["day"], source["phase"]) != (report["day"], report["phase"])
                        or phase_index(report["day"], report["phase"]) > phase_index(state.clock.day, state.clock.phase)
                        or not 0 <= report["revision"] <= case["revision"] or report["summary"] != claim["summary"]
                        or report["claim_id"] not in state.knowledge["beliefs_by_actor"][listener]):
                    return ["invalid anomaly report"]
        return []
    except (KeyError, TypeError, AttributeError, ValueError):
        return ["malformed anomaly ledger"]
