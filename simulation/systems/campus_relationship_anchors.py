"""Consented, source-bound shared memories, not gifts converted into diagnoses."""
from simulation.actions.commands import SimulationCommand
from simulation.systems.campus_intelligence import create_campus_claim
from simulation.systems.campus_growth import mastery_by_topic
from simulation.systems.campus_trade import tick
from simulation.systems.campus_tasks import phase_index
from simulation.systems.transactions import TransactionOutcome

ANCHOR_DELTA = {"shell": 10, "core": 40, "coherence": 30}


def sources(state, case, helper):
    """Only both participants' actual experiences, never another NPC's diary."""
    result = []
    for row in case["history"]:
        if row["route"] == "day_support" and row["helper_id"] == helper and row["day"] < state.clock.day:
            result.append({"source_id": "support:" + str(row["revision"]),
                "label": f"第 {row['day']} 天我们实际一起完成的现实锚定活动"})
    for request in state.cognition.get("material_assistance", {}).get("requests", {}).values():
        if (request["status"] == "fulfilled" and {request["helper_id"], request["requester_id"]} == {helper, case["actor_id"]}
                and request.get("receipt")):
            item = state.inventories["catalog"][request["item_id"]]["name"]
            result.append({"source_id": "material:" + request["request_id"],
                "label": f"我们因实际需要约定、并已当面交付的{item}"})
    return result


def source_valid(state, case, anchor):
    source = anchor["source_id"]
    if source.startswith("support:"):
        return any(row["route"] == "day_support" and "support:" + str(row["revision"]) == source
            and row["helper_id"] == anchor["helper_id"] and row["day"] < anchor["day"]
            and row["revision"] <= anchor["case_revision"] for row in case["history"])
    if source.startswith("material:"):
        request = state.cognition.get("material_assistance", {}).get("requests", {}).get(source.removeprefix("material:"), {})
        receipt = request.get("receipt", {})
        return (request.get("status") == "fulfilled" and {request.get("helper_id"), request.get("requester_id")} == {anchor["helper_id"], case["actor_id"]}
            and bool(receipt.get("command_id")) and type(receipt.get("quantity")) is int and receipt["quantity"] >= 1
            and receipt.get("helper_before", 0) - receipt.get("helper_after", 0) == receipt["quantity"]
            and receipt.get("requester_after", 0) - receipt.get("requester_before", 0) == receipt["quantity"]
            and request.get("updated_tick", -1) <= phase_index(anchor["day"], anchor["phase"]))
    return False


def confirm_anchor(context, command, case):
    from simulation.systems.campus_anomalies import _consents
    state, helper = context.state, command.actor_id
    def fail(code, message): return TransactionOutcome(False, False, code, message)
    if case["status"] == "resolved":
        return fail("already_resolved", "这次经历已稳定，可以继续普通交流，不重复建立干预依据。")
    report = case["reports"].get(helper, {})
    if (report.get("day"), report.get("phase"), report.get("revision")) != (state.clock.day, state.clock.phase, case["revision"]):
        return fail("fresh_report_required", "先听取本人当前陈述，再询问这段共同经历是否仍有意义。")
    if not _consents(state, case["actor_id"], helper, 65):
        return fail("anchor_withheld", "对方暂不愿把这段共同经历作为锚点；发生过不等于必须认同。")
    source_id = command.parameters.get("source_id")
    choice = next((row for row in sources(state, case, helper) if row["source_id"] == source_id), None)
    if not choice:
        return fail("shared_source_required", "需要双方真实参与并已完成的共同经历；承诺、普通送礼或他人故事不能代替。")
    existing = case.get("anchors", {}).get(helper)
    if existing:
        return TransactionOutcome(True, True, "anchor_already_confirmed", "已经确认过本次经历的共同锚点，不重复生成证据。", payload={"anchor": dict(existing)})
    anchor_id = "anchor:" + case["case_id"] + ":" + helper
    summary = choice["label"] + "。本人愿意把这段确实发生的共同经历作为联系眼前生活的依据；它不证明全部记忆，也不保证恢复。"
    claim = create_campus_claim(state, subject_id=case["actor_id"], predicate="voluntary_relationship_anchor", object_id=helper,
        summary=summary, secrecy=75, known_by=[case["actor_id"], helper], evidence_kind="firsthand_statement")
    claim["source_context"] = {"source_kind": "confirmed_shared_experience", "source_id": anchor_id,
        "day": state.clock.day, "phase": state.clock.phase, "layer": "surface", "location_id": None}
    anchor = {"anchor_id": anchor_id, "helper_id": helper, "source_id": source_id, "claim_id": claim["claim_id"],
        "report_claim_id": report["claim_id"], "day": state.clock.day, "phase": state.clock.phase, "case_revision": case["revision"], "summary": summary}
    case.setdefault("anchors", {})[helper] = anchor
    context.emit("CAMPUS_RELATIONSHIP_ANCHOR_CONFIRMED", summary, actor_ids=[helper, case["actor_id"]],
        visibility="private", knowledge_tags=["evidence", "relationship"], payload={"anchor_id": anchor_id, "claim_id": claim["claim_id"]})
    return TransactionOutcome(True, True, "anchor_confirmed", summary, commit=True, payload={"anchor": dict(anchor)})


def use_problem(state, case, helper, anchor_id):
    from simulation.systems.campus_anomalies import _consents
    anchor = case.get("anchors", {}).get(helper)
    if not isinstance(anchor_id, str) or not anchor or anchor["anchor_id"] != anchor_id:
        return "owned_anchor_required", "需要本人已向你确认的共同经历，不能借用其他人的锚点。"
    if any(row.get("anchor_id") for row in case["history"]):
        return "anchor_already_applied", "这次残留已使用过证据洞察；更换帮助者或锚点不能重复叠加。"
    if mastery_by_topic(state, helper).get(case["topic_id"], 0) < 40:
        return "anchor_knowledge_required", "对应现象理解达到 40 后，才能把共同经历和本人陈述联系起来。"
    if not _consents(state, case["actor_id"], helper, 65):
        return "anchor_withheld", "本人此刻不愿使用这段经历；旧同意不能覆盖现在的选择。"
    belief = state.knowledge.get("beliefs_by_actor", {}).get(helper, {}).get(anchor["claim_id"], {})
    if belief.get("confidence", 0) < .5 or belief.get("distortion", 1) > .35:
        return "reliable_anchor_required", "这份共同经历记录已不够可靠，不能据此进行证据洞察。"
    return None


def anchor_view(state, case, helper):
    anchor = case.get("anchors", {}).get(helper)
    problem = use_problem(state, case, helper, anchor["anchor_id"]) if anchor else ("owned_anchor_required", "先选取真实共同经历，询问本人是否愿意确认。")
    return {"anchor_options": sources(state, case, helper) if not anchor else [],
        "confirmed_anchor": dict(anchor) if anchor else {}, "can_use_anchor": problem is None, "anchor_hint": problem[1] if problem else "可结合共同经历进行证据洞察；仍须当面、当前同意、双方各一次主要行动。"}


def automatic_support_parameters(context, case, helper):
    """Shared rule executor, no new model request or automatic player operation."""
    params = {"npc_id": case["actor_id"], "case_id": case["case_id"], "expected_case_revision": case["revision"]}
    if helper == "player" or case["actor_id"] == "player" or any(row.get("anchor_id") for row in case["history"]) or mastery_by_topic(context.state, helper).get(case["topic_id"], 0) < 40:
        return params
    anchor = case.get("anchors", {}).get(helper)
    if not anchor:
        choices = sources(context.state, case, helper)
        if choices:
            from simulation.systems.campus_anomalies import make_anomaly_handler
            command = SimulationCommand(f"confirm-anchor:{case['case_id']}:{helper}:{tick(context.state)}", helper,
                "CONFIRM_RELATIONSHIP_ANCHOR", context.state.revision, parameters={**params, "source_id": choices[0]["source_id"]},
                issued_day=context.state.clock.day, issued_phase=context.state.clock.phase, source="rule")
            make_anomaly_handler()(context, command)
            anchor = case.get("anchors", {}).get(helper)
    if anchor and use_problem(context.state, case, helper, anchor["anchor_id"]) is None:
        params["anchor_id"] = anchor["anchor_id"]
    return params


def anchors_valid(state, case):
    try:
        for helper, anchor in case.get("anchors", {}).items():
            claim = state.knowledge["claims"][anchor["claim_id"]]
            report = state.knowledge["claims"][anchor["report_claim_id"]]
            if (helper not in state.population or helper == case["actor_id"] or anchor["helper_id"] != helper
                or anchor["anchor_id"] != "anchor:" + case["case_id"] + ":" + helper or not source_valid(state, case, anchor)
                or type(anchor["case_revision"]) is not int or not 0 <= anchor["case_revision"] <= case["revision"]
                or type(anchor["day"]) is not int or not case["created_day"] <= anchor["day"] <= state.clock.day
                or phase_index(anchor["day"], anchor["phase"]) > tick(state)
                or claim["subject_id"] != case["actor_id"] or claim["object_id"] != helper
                or claim["predicate"] != "voluntary_relationship_anchor" or claim["summary"] != anchor["summary"]
                or claim["source_context"]["source_id"] != anchor["anchor_id"]
                or claim["source_context"]["source_kind"] != "confirmed_shared_experience"
                or (claim["source_context"]["day"], claim["source_context"]["phase"]) != (anchor["day"], anchor["phase"])
                or report["subject_id"] != case["actor_id"] or report["predicate"] != "voluntary_moon_experience"
                or report["source_context"]["source_id"] != case["case_id"]
                or (report["source_context"]["day"], report["source_context"]["phase"]) != (anchor["day"], anchor["phase"])
                or anchor["report_claim_id"] not in state.knowledge["beliefs_by_actor"][helper]
                or anchor["claim_id"] not in state.knowledge["beliefs_by_actor"][helper]):
                return False
        return True
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def receipt_anchor_valid(case, receipt):
    anchor = case.get("anchors", {}).get(receipt["helper_id"], {})
    return (anchor.get("anchor_id") == receipt["anchor_id"] and anchor["case_revision"] < receipt["revision"]
        and phase_index(anchor["day"], anchor["phase"]) <= phase_index(receipt["day"], receipt["phase"]))
