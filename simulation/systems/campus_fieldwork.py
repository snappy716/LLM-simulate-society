"""Physical night observations and source-bound reports, shared by all actors.

A posted request is not evidence. Measurements are generated once in the world,
remain private until inspected, and survive saves independently of who claims it.
"""
from dataclasses import replace
from simulation.systems.transactions import TransactionOutcome
from simulation.systems.campus_vitals import actor_layer, battle_locked
from simulation.systems.campus_departures import has_upcoming_departure


def is_field_task(task):
    return task.get("resolution_kind") == "field_recon"


def validate_field_profile(profile):
    if (not isinstance(profile, dict) or profile.get("kind") not in {"echo", "index", "moonlight"}
            or any(not isinstance(profile.get(key), str) or not profile[key] for key in ("label", "baseline_label", "anomaly_label"))
            or any(type(profile.get(key)) is not int for key in ("baseline_min", "baseline_max", "offset_min", "offset_max"))
            or not 0 <= profile["baseline_min"] <= profile["baseline_max"]
            or not 1 <= profile["offset_min"] <= profile["offset_max"]):
        raise ValueError("invalid physical field profile")


def create_field_site(context, task, profile):
    validate_field_profile(profile)
    state = context.state
    ledger = state.situations.setdefault("field_sites", {"schema_version": 1, "sites": {}})
    site_id = "field:" + task["task_id"]
    rng = context.rng.stream("campus_field_sites")
    baseline = rng.randint(profile["baseline_min"], profile["baseline_max"])
    anomaly = baseline + rng.randint(profile["offset_min"], profile["offset_max"])
    ledger["sites"][site_id] = {"site_id": site_id, "task_id": task["task_id"], "location_id": task["scene_id"],
        "layer": "night", "day": state.clock.day, "expires_day": task["expires_day"], "phase": state.clock.phase,
        "label": profile["label"], "kind": profile["kind"], "revision": 1,
        "measurements": [{"key": "baseline", "label": profile["baseline_label"], "value": baseline},
                         {"key": "anomaly", "label": profile["anomaly_label"], "value": anomaly}]}
    task.update(resolution_kind="field_recon", field_site_id=site_id)


def field_sources(state, actor_id):
    actor = state.population[actor_id]
    beliefs = state.knowledge["beliefs_by_actor"][actor_id]
    observed = state.knowledge.get("investigation", {}).get("observations", {})
    result = []
    for site in state.situations.get("field_sites", {}).get("sites", {}).values():
        if (site["location_id"] != actor["current_location_id"] or site["layer"] != actor_layer(state, actor_id)
                or state.clock.day > site["expires_day"] or state.clock.phase not in {"evening", "late_night"}):
            continue
        for reading in site["measurements"]:
            key = f"{site['site_id']}:{site['revision']}:{reading['key']}"
            claim_id = observed.get(key)
            belief = beliefs.get(claim_id, {})
            if belief.get("source_kind") == "field_measurement" and belief.get("source_actor_id") == actor_id:
                continue
            result.append({"source_id": key, "claim_id": claim_id, "kind": "field_measurement",
                "label": site["label"] + "（待实地核对）", "subject_id": site["location_id"],
                "object_id": site["site_id"], "predicate": "field_" + reading["key"],
                "summary": f"第 {site['day']} 天，{site['label']}：{reading['label']}为 {reading['value']}。这是现场读数，不证明异常的成因或任何人的动机。",
                "location_id": site["location_id"], "layer": site["layer"]})
    return result


def report_claim_ids(state, actor_id, task):
    site = state.situations.get("field_sites", {}).get("sites", {}).get(task.get("field_site_id"), {})
    if not site:
        return []
    observations = state.knowledge.get("investigation", {}).get("observations", {})
    beliefs = state.knowledge["beliefs_by_actor"].get(actor_id, {})
    ids = []
    for reading in site["measurements"]:
        source = f"{site['site_id']}:{site['revision']}:{reading['key']}"
        key = observations.get(source)
        claim = state.knowledge["claims"].get(key, {})
        belief = beliefs.get(key, {})
        if (claim.get("source_context", {}).get("source_id") != source or claim.get("object_id") != site["site_id"]
                or belief.get("source_kind") != "field_measurement" or belief.get("source_actor_id") != actor_id
                or belief.get("transmission_count") != 0):
            return []
        ids.append(key)
    return ids


def make_field_report_handler():
    def handle(context, command):
        state, actor_id = context.state, command.actor_id
        def fail(code, message):
            return TransactionOutcome(False, False, code, message)
        if actor_id not in state.population or (actor_id != "player" and command.source != "rule"):
            return fail("actor_not_authorized", "不能替其他人提交现场报告。")
        if command.issued_day != state.clock.day or command.issued_phase != state.clock.phase:
            return fail("command_clock_mismatch", "现场报告请求已过期。")
        if set(command.parameters) - {"task_id", "expected_task_revision"}:
            return fail("invalid_field_report", "报告内容必须来自本人实地调查，不接受自填事实。")
        task_id = command.parameters.get("task_id")
        task = state.tasks.get(task_id, {}) if isinstance(task_id, str) else {}
        if not is_field_task(task) or task.get("assignee_id") != actor_id or task.get("state") != "locked":
            return fail("task_not_owned", "没有持有可提交的调查任务。")
        if type(command.parameters.get("expected_task_revision")) is not int or command.parameters["expected_task_revision"] != task["lock_revision"]:
            return fail("task_revision_conflict", "任务状态已改变，请刷新。")
        if state.clock.day > task["expires_day"] or state.clock.phase not in {"evening", "late_night"}:
            return fail("invalid_phase", "现场调查已超过当夜执行窗口。")
        if actor_layer(state, actor_id) != "night":
            return fail("night_layer_required", "需要在夜相现场核对并提交。")
        if state.population[actor_id]["current_location_id"] != task["scene_id"]:
            return fail("task_location_required", "请到指定现场，不能从相邻区域远程代查。")
        if battle_locked(state, actor_id):
            return fail("battle_already_active", "请先结束战斗。")
        if state.population[actor_id].get("vitals", {}).get("health", 1) <= 0:
            return fail("incapacitated", "当前无法进行现场调查。")
        claims = report_claim_ids(state, actor_id, task)
        if len(claims) != 2:
            return fail("field_evidence_required", "请深入搜查取得两项亲自核对的现场读数；公告或他人转述不能代替。")
        from simulation.systems.campus_tasks import complete_assigned_task
        site = state.situations["field_sites"]["sites"][task["field_site_id"]]
        task["field_report"] = {"actor_id": actor_id, "site_id": site["site_id"], "site_revision": site["revision"],
            "claim_ids": claims, "day": state.clock.day, "phase": state.clock.phase}
        if not complete_assigned_task(context, actor_id, {"task_id": task_id, "field_report": True}):
            raise RuntimeError("validated field report could not settle its task")
        task["history"].append({"day": state.clock.day, "phase": state.clock.phase, "kind": "field_report",
            "message": f"{state.population[actor_id]['display_name']}提交了两项实地核对记录，调查完成；未推定幕后原因。"})
        context.emit("FIELD_REPORT_SUBMITTED", "完成实地对照调查，报告已结算。", actor_ids=[actor_id],
            target_ids=[task["issuer_id"]], scene_id=site["location_id"], visibility="secret", knowledge_tags=["night", "investigation", "task"],
            payload={"task_id": task_id, "site_id": site["site_id"], "claim_ids": claims})
        return TransactionOutcome(True, True, "success", "两项亲自核对的现场记录已提交，报酬已结算；提交本身不额外消耗行动。",
            commit=True, payload={"field_report": task["field_report"], "task_completed": True, "effects": {}})
    return handle


def make_autonomous_fieldwork_handler(investigate, submit):
    def handle(context, command):
        state, actor_id = context.state, command.actor_id
        task_id = command.parameters.get("forum_task_id", command.parameters.get("task_id", ""))
        task = state.tasks.get(task_id, {}) if isinstance(task_id, str) else {}
        if (actor_id == "player" or actor_id not in state.population or command.source != "rule"
                or task.get("assignee_id") != actor_id or task.get("state") != "locked" or not is_field_task(task)):
            return TransactionOutcome(False, False, "task_not_owned", "没有可自主调查的本人任务。")
        if state.population[actor_id].get("vitals", {}).get("health", 1) <= 0:
            return TransactionOutcome(False, False, "incapacitated", "无法执行现场调查。")
        if has_upcoming_departure(state, actor_id):
            return TransactionOutcome(False, False, "departure_reserved", "已承诺参加出击。")
        if state.population[actor_id]["current_location_id"] != task["scene_id"]:
            return TransactionOutcome(False, False, "task_location_required", "需要实际到达调查现场。")
        if len(report_claim_ids(state, actor_id, task)) != 2:
            result = investigate(context, replace(command, action_id="SEARCH_SCENE", parameters={}))
            if not result.success:
                return result
        return submit(context, replace(command, action_id="SUBMIT_FIELD_REPORT", parameters={"task_id": task["task_id"],
            "expected_task_revision": task["lock_revision"]}))
    return handle


def fieldwork_view(state, actor_id, task):
    if not is_field_task(task):
        return {}
    return {"ready_to_report": len(report_claim_ids(state, actor_id, task)) == 2,
            "rule_note": "在指定现场深入搜查（1 次主要行动），核对两项读数后提交报告（免费）；战斗或公告不能代替调查。"}


def fieldwork_invariant(state):
    ledger = state.situations.get("field_sites")
    if ledger is None:
        return [] if not any(is_field_task(t) for t in state.tasks.values()) else ["field task without physical sites"]
    try:
        if ledger["schema_version"] != 1:
            return ["invalid field site schema"]
        for site_id, site in ledger["sites"].items():
            task = state.tasks[site["task_id"]]
            if (site_id != site["site_id"] or task.get("field_site_id") != site_id or not is_field_task(task)
                    or site["location_id"] != task["scene_id"] or site["layer"] != "night"
                    or type(site["day"]) is not int or site["day"] < 1 or site["expires_day"] != task["expires_day"]
                    or site["revision"] != 1 or site["phase"] != "evening"
                    or [r["key"] for r in site["measurements"]] != ["baseline", "anomaly"]
                    or any(type(r["value"]) is not int or r["value"] < 0 for r in site["measurements"])):
                return ["invalid physical field site"]
        for task in state.tasks.values():
            if not is_field_task(task):
                continue
            site = ledger["sites"][task["field_site_id"]]
            if site["task_id"] != task["task_id"]:
                return ["field task bound to another site"]
            if task.get("state") == "completed":
                report = task["field_report"]
                if (report["actor_id"] != task["assignee_id"] or report["site_id"] != site["site_id"]
                        or report["site_revision"] != site["revision"] or len(report["claim_ids"]) != 2
                        or len(set(report["claim_ids"])) != 2 or report["actor_id"] not in state.population
                        or type(report["day"]) is not int or not site["day"] <= report["day"] <= site["expires_day"]
                        or report["phase"] not in {"evening", "late_night"}
                        or task.get("completion_evidence") != {"kind": "field_report", "site_id": site["site_id"]}
                        or any(state.knowledge["claims"][key].get("object_id") != site["site_id"]
                            or state.knowledge["claims"][key].get("source_context", {}).get("source_id")
                                != f"{site['site_id']}:{site['revision']}:{reading['key']}"
                            for key, reading in zip(report["claim_ids"], site["measurements"]))):
                    return ["invalid field report evidence"]
    except (KeyError, TypeError, AttributeError):
        return ["invalid nested field site state"]
    return []
