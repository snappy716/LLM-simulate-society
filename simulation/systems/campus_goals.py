"""Persistent, evidence-bound NPC intentions; executable steps remain shared actions.

First slice: digest a personally experienced anomaly. No invented case, shop stock,
money or LLM-written executable program. Cooperation expands this same ledger later.
"""
from copy import deepcopy

from simulation.systems.campus_growth import CHAPTER_NAMES
from simulation.systems.campus_trade import tick
from simulation.systems.campus_vitals import actor_layer, battle_locked
from simulation.systems.campus_departures import active_departure
from simulation.systems.transactions import TransactionOutcome

STEPS = {"read", "prepare_notebook", "earn_money", "reflect", "complete"}
STATES = {"active", "blocked", "completed"}
STEP_TEXT = {"read": "阅读相关讲义", "prepare_notebook": "准备随身笔记本",
             "earn_money": "通过校内服务筹备费用", "reflect": "整理亲历案例", "complete": "完成本轮研习"}
EXPECTED_STEP_FAILURES = {"study_unavailable", "component_complete", "notebook_required",
                          "reflection_requires_case", "activity_wrong_phase", "activity_location_closed"}


def _ledger(state):
    return state.cognition.setdefault("long_term_plans", {"schema_version": 1, "actors": {}, "disclosures": {}})


def _progress(state, actor_id, topic):
    return state.knowledge.get("growth", {}).get("actors", {}).get(actor_id, {}).get("topics", {}).get(topic, {})


def _actual_step(state, actor_id, topic):
    progress = _progress(state, actor_id, topic)
    if progress.get("theory", 0) < 40:
        return "read"
    if progress.get("reflection", 0) >= 10:
        return "complete"
    if state.inventories.get("actors", {}).get(actor_id, {}).get("quantities", {}).get("blank_notebook", 0) < 1:
        price = state.inventories.get("catalog", {}).get("blank_notebook", {}).get("base_price", 0)
        return "earn_money" if state.population[actor_id].get("wealth", 0) < price else "prepare_notebook"
    return "reflect"


def _update(state, goal, step, status, reason=""):
    changed = (goal["step"], goal["status"], goal["blocked_reason"]) != (step, status, reason)
    goal.update(step=step, status=status, blocked_reason=reason, checked_tick=tick(state))
    if changed:
        goal["history"].append({"day": state.clock.day, "phase": state.clock.phase,
                                "step": step, "status": status, "reason": reason})
        goal["history"] = goal["history"][-24:]
    return changed


def advance_personal_goals(context):
    state, created = context.state, 0
    # Only actors with actual recorded cases acquire these goals. No omniscient seeding.
    for actor_id, growth in sorted(state.knowledge.get("growth", {}).get("actors", {}).items()):
        if actor_id == "player" or actor_id not in state.population:
            continue
        for topic in sorted({case["topic_id"] for case in growth.get("case_records", {}).values()}):
            if topic not in CHAPTER_NAMES or _progress(state, actor_id, topic).get("cases", 0) < 10:
                continue
            goals = _ledger(state)["actors"].setdefault(actor_id, {})
            goal_id = "understand:" + topic
            if goal_id not in goals:
                source_ids = sorted(key for key, case in growth["case_records"].items() if case["topic_id"] == topic)
                goals[goal_id] = {"goal_id": goal_id, "topic_id": topic, "source_ids": source_ids,
                    "created_tick": tick(state), "checked_tick": tick(state), "step": "read", "status": "active",
                    "blocked_reason": "", "attempts": 0, "last_action": "", "last_result": "", "history": []}
                created += 1
                context.emit("NPC_PERSONAL_GOAL_CREATED", "决定把亲历的异常整理成可以理解的案例。",
                             actor_ids=[actor_id], visibility="private", knowledge_tags=["goal", "discovery"],
                             payload={"goal_id": goal_id, "topic_id": topic, "source_ids": source_ids})
            goal = goals[goal_id]
            step = _actual_step(state, actor_id, topic)
            if step == "complete":
                _update(state, goal, step, "completed")
            elif goal["step"] != step:
                _update(state, goal, step, "active")
    return {"personal_goals_created": created}


def own_goal_context(state, actor_id):
    """Internal cognition context; never serialize the full ledger to the world view."""
    goals = state.cognition.get("long_term_plans", {}).get("actors", {}).get(actor_id, {})
    return [{key: deepcopy(goal[key]) for key in ("goal_id", "topic_id", "step", "status", "blocked_reason")}
            for goal in goals.values() if goal["status"] != "completed"][:2]


def goal_candidates(context, actor_id, schedule_plan, graph, occupancy, policy, definitions, base_score):
    from simulation.systems.campus_decisions import _destination_is_open_and_accessible, _has_capacity
    from simulation.systems.campus_inventory import _catalog, _inventory
    state, result = context.state, []
    actor = state.population[actor_id]
    goals = state.cognition.get("long_term_plans", {}).get("actors", {}).get(actor_id, {})
    if not goals:
        return []
    reason = ""
    if battle_locked(state, actor_id) or active_departure(state, actor_id):
        reason = "已有出击承诺"
    elif actor_layer(state, actor_id) != "surface":
        reason = "返回表世界后再整理"
    elif actor.get("active_forum_task_id"):
        reason = "优先履行已接任务"
    elif int(schedule_plan.get("priority", 0)) >= policy.protected_schedule_priority:
        reason = "优先完成课程或值班"
    elif max(actor.get("needs", {}).get(key, 0) for key in ("rest", "food", "safety")) >= policy.emergency_need_threshold:
        reason = "先处理迫切的生活需要"
    active = sorted((g for g in goals.values() if g["status"] != "completed"),
                    key=lambda g: (g["created_tick"], g["goal_id"]))[:2]
    for index, goal in enumerate(active):
        step = _actual_step(state, actor_id, goal["topic_id"])
        if step == "complete":
            _update(state, goal, step, "completed")
            continue
        if reason:
            _update(state, goal, step, "blocked", reason)
            continue
        from simulation.systems.campus_assistance import waiting_for_material_help
        if step in {"earn_money", "prepare_notebook"} and waiting_for_material_help(state, actor_id, "blank_notebook"):
            _update(state, goal, step, "blocked", "等待已经答应的物资互助；到期未交付则另作安排")
            continue
        action, params, destinations, action_class = "", {}, [], "major"
        if step in {"read", "reflect"}:
            action = "READ_KNOWLEDGE" if step == "read" else "REFLECT_ON_CASE"
            params = {"topic_id": goal["topic_id"]}
            destinations = [actor.get("home_location_id", ""), "library_reading_hall"]
        elif step == "earn_money":
            action = "CAMPUS_SERVICE_SHIFT"
            definition = definitions.get(action)
            if definition and state.clock.phase in definition.allowed_phases:
                destinations = ["canteen_dining_hall"]
        else:
            action, action_class = "BUY_ITEM", "free"
            catalog = _catalog(state)
            inventory = _inventory(state.inventories["actors"][actor_id])
            if "blank_notebook" in catalog and inventory.can_add(catalog["blank_notebook"], 1, catalog):
                for shop in state.inventories["shops"].values():
                    if shop["quantities"].get("blank_notebook", 0) > 0:
                        destinations.append(shop["location_id"])
        if action_class == "major" and state.action_economy["actors"][actor_id]["major_remaining"] <= 0:
            _update(state, goal, step, "blocked", "本时段主要行动已用完")
            continue
        routes = []
        for destination in destinations:
            if not _destination_is_open_and_accessible(graph, actor, destination, state.clock.phase) or not _has_capacity(graph, occupancy, destination):
                continue
            route = graph.shortest_route(actor["current_location_id"], destination, phase=state.clock.phase,
                                         access_tags=actor.get("access_tags", ()))
            if route is not None:
                routes.append(route)
        if not routes:
            blocked = "暂时没有可到达且有货的商店或背包空间不足" if step == "prepare_notebook" else "可用地点尚未开放或无法到达"
            _update(state, goal, step, "blocked", blocked)
            continue
        route = min(routes, key=lambda r: (r.total_minutes, r.destination_id))
        if action == "BUY_ITEM":
            shop = next(shop for shop in state.inventories["shops"].values()
                        if shop["location_id"] == route.destination_id and shop["quantities"].get("blank_notebook", 0) > 0)
            params = {"shop_id": shop["id"], "item_id": "blank_notebook", "quantity": 1}
        _update(state, goal, step, "active")
        # Finite continuity bonus; urgent needs/protected commitments were excluded above.
        curiosity = int(actor.get("personality", {}).get("openness", 50))
        score = base_score + 5 + curiosity * 0.05 - index * 4 - min(4, route.total_minutes * 0.02)
        result.append({"candidate_id": "goal:" + goal["goal_id"] + ":" + step,
            "activity_id": action, "action_class": action_class, "location_id": route.destination_id,
            "parameters": params, "personal_goal_id": goal["goal_id"], "priority": 70,
            "decision_source": "rule", "decision_reason": "persistent_personal_goal",
            "reason_codes": ["personal_case", "continuity", "legal_next_step"],
            "scheduled_activity_id": schedule_plan.get("activity_id", ""),
            "scheduled_location_id": schedule_plan.get("location_id", ""),
            "candidate_count": 1, "score": round(score, 3), "score_jitter": 0.0,
            "score_contributions": {"goal_continuity": round(score, 3)}, "route_minutes": route.total_minutes,
            "day": state.clock.day, "phase": state.clock.phase})
    return result


def record_goal_outcome(context, actor_id, plan, outcome):
    goal = context.state.cognition.get("long_term_plans", {}).get("actors", {}).get(actor_id, {}).get(plan.get("personal_goal_id"))
    if goal is None:
        return
    goal.update(attempts=goal["attempts"] + 1, last_action=plan["activity_id"], last_result=outcome.code)
    step = _actual_step(context.state, actor_id, goal["topic_id"])
    status = "completed" if step == "complete" else ("active" if outcome.success else "blocked")
    _update(context.state, goal, step, status, "" if outcome.success else outcome.message)
    context.emit("NPC_PERSONAL_GOAL_PROGRESS", "研习计划取得实际进展。" if outcome.success else "研习计划受阻，下一时段重新核对条件。",
                 actor_ids=[actor_id], visibility="private", knowledge_tags=["goal", "discovery"],
                 payload={"goal_id": goal["goal_id"], "action_id": plan["activity_id"], "result": outcome.code, "step": step})


def disclosed_plans(state, viewer_id="player"):
    return deepcopy(state.cognition.get("long_term_plans", {}).get("disclosures", {}).get(viewer_id, {}))


def make_ask_plan_handler():
    def handle(context, command):
        state, actor_id = context.state, command.actor_id
        target = command.parameters.get("npc_id")
        def fail(code, message):
            return TransactionOutcome(False, False, code, message)
        if actor_id not in state.population or (command.source == "player" and actor_id != "player"):
            return fail("actor_not_authorized", "不能代替他人询问。")
        if command.issued_day != state.clock.day or command.issued_phase != state.clock.phase:
            return fail("command_clock_mismatch", "询问所属时段已过期。")
        if not isinstance(target, str) or target == "player" or target == actor_id or target not in state.population:
            return fail("unknown_npc", "请选择可以交谈的 NPC。")
        if (battle_locked(state, actor_id) or battle_locked(state, target)
                or state.population[actor_id]["current_location_id"] != state.population[target]["current_location_id"]
                or actor_layer(state, actor_id) != actor_layer(state, target)):
            return fail("not_available", "需要在同一地点、同一世界且没有参战，才能当面询问。")
        npc = state.population[target]
        relation = state.relationships.get(target, {}).get(actor_id, {})
        # This is a volunteered, non-secret sketch, not the private plan or future schedule.
        guarded = (npc.get("personality", {}).get("risk_tolerance", 50) < 25
                   and relation.get("closeness", 0) < 20) or relation.get("suspicion", 0) >= 60
        goals = own_goal_context(state, target)
        if guarded:
            message = "最近有些自己的安排，暂时不太想细说。"
        elif goals:
            stage = goals[0]["step"]
            message = "最近想把一些亲身经历整理清楚。下一步打算%s。" % STEP_TEXT[stage]
        else:
            message = "暂时没有另外的研习安排，先处理手头的课程和生活。"
        agenda = state.cognition.get("daily_plans", {})
        receipt = state.cognition.get("social_agenda_receipts", {})
        from simulation.systems.campus_social_coordination import coordination_for, describe_confirmed_arrangement
        confirmed = describe_confirmed_arrangement(state, target,
            relation.get("closeness", 0) >= 45 and relation.get("trust", 0) >= 45) if not guarded else ""
        message += confirmed
        if (not guarded and not confirmed and agenda.get("day") == state.clock.day
                and coordination_for(state, target).get("status") != "declined"
                and not (receipt.get("day") == state.clock.day and target in receipt.get("actors", {}))):
            for slot in agenda.get("actors", {}).get(target, {}).values():
                social = slot.get("social_intent")
                if social:
                    phase_name = {"morning": "上午", "afternoon": "下午", "evening": "晚上", "late_night": "凌晨"}[social["phase"]]
                    partner = social["target_name"] if relation.get("closeness", 0) >= 45 and relation.get("trust", 0) >= 45 else "一位认识的人"
                    message += f" 今天{phase_name}还想找{partner}{social['reason']}，不过还得看能不能碰面、对方是否方便。"
                    break
        report = {"npc_id": target, "day": state.clock.day, "phase": state.clock.phase, "summary": message,
                  "source": "本人告知", "withheld": guarded}
        _ledger(state)["disclosures"].setdefault(actor_id, {})[target] = report
        context.emit("NPC_PLAN_DISCLOSED", message, actor_ids=[target], target_ids=[actor_id],
                     scene_id=npc["current_location_id"], payload={"withheld": guarded},
                     visibility="private", knowledge_tags=["goal", "discovery"])
        return TransactionOutcome(True, True, "success", message, commit=True, payload={"report": deepcopy(report)})
    return handle


def personal_goals_invariant(state):
    ledger = state.cognition.get("long_term_plans")
    if ledger is None:
        return []
    errors = []
    try:
        if ledger["schema_version"] != 1 or not isinstance(ledger["actors"], dict) or not isinstance(ledger["disclosures"], dict):
            return ["invalid personal goals ledger"]
        for actor_id, goals in ledger["actors"].items():
            if actor_id == "player" or actor_id not in state.population or not isinstance(goals, dict) or len(goals) > len(CHAPTER_NAMES):
                errors.append("invalid personal goal owner/count")
                continue
            cases = state.knowledge.get("growth", {}).get("actors", {}).get(actor_id, {}).get("case_records", {})
            for goal_id, goal in goals.items():
                if (goal_id != goal["goal_id"] or goal_id != "understand:" + goal["topic_id"]
                        or goal["topic_id"] not in CHAPTER_NAMES or goal["step"] not in STEPS or goal["status"] not in STATES):
                    errors.append("invalid personal goal identity/state")
                if (not isinstance(goal["source_ids"], list) or not goal["source_ids"]
                        or any(not isinstance(key, str) or cases.get(key, {}).get("topic_id") != goal["topic_id"] for key in goal["source_ids"])):
                    errors.append("personal goal lacks owned case source")
                if any(type(goal[key]) is not int or goal[key] < 0 for key in ("created_tick", "checked_tick", "attempts")):
                    errors.append("invalid personal goal counters")
                elif goal["checked_tick"] < goal["created_tick"]:
                    errors.append("personal goal checked before creation")
                if not isinstance(goal["history"], list) or len(goal["history"]) > 24:
                    errors.append("invalid personal goal history")
                else:
                    for entry in goal["history"]:
                        if (entry["step"] not in STEPS or entry["status"] not in STATES
                                or type(entry["day"]) is not int or entry["day"] < 1
                                or entry["phase"] not in {"morning", "afternoon", "evening", "late_night"}
                                or not isinstance(entry["reason"], str)):
                            errors.append("invalid personal goal history entry")
                if any(not isinstance(goal[key], str) for key in ("blocked_reason", "last_action", "last_result")):
                    errors.append("invalid personal goal text")
                if goal["status"] == "completed" and _actual_step(state, actor_id, goal["topic_id"]) != "complete":
                    errors.append("personal goal falsely completed")
        for viewer_id, reports in ledger["disclosures"].items():
            if viewer_id not in state.population or not isinstance(reports, dict):
                errors.append("invalid personal goal disclosure owner")
                continue
            for target, report in reports.items():
                if (target not in state.population or report["npc_id"] != target or not isinstance(report["summary"], str)
                        or type(report["day"]) is not int or report["day"] < 1
                        or report["phase"] not in {"morning", "afternoon", "evening", "late_night"} or type(report["withheld"]) is not bool):
                    errors.append("invalid personal goal disclosure")
    except (KeyError, TypeError, ValueError, AttributeError):
        errors.append("invalid nested personal goal structure")
    return errors
