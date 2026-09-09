"""Anonymous physical afterimages share the person's persistent anomaly state."""
from copy import deepcopy

from simulation.systems.campus_anomalies import INITIAL
from simulation.systems.campus_tasks import TERMINAL_STATES

MAX_NIGHT_EPISODES = 2


def pending_afterimages(state):
    tasks = [t for t in state.tasks.values() if t.get("anomaly_case_id")]
    pending = {t["anomaly_case_id"] for t in tasks if t["state"] not in TERMINAL_STATES}
    latest = {}
    for task in tasks:
        latest[task["anomaly_case_id"]] = max(latest.get(task["anomaly_case_id"], 0), task["created_day"])
    cases = [case for case in state.situations.get("campus_anomalies", {}).get("cases", {}).values()
        if case["shell"] > 0 and case["status"] != "resolved" and case["case_id"] not in pending]
    return sorted(cases, key=lambda c: (latest.get(c["case_id"], 0), c["created_day"], c["case_id"]))[:MAX_NIGHT_EPISODES]


def afterimage_template(state, case, templates):
    # Reuse the established containment objective and execution pipeline. No
    # new content hash, displaced victim or free standalone completion command.
    base = next(t for key, t in sorted(templates.items()) if t.get("site_profile", {}).get("kind") == "containment")
    template = deepcopy(base)
    source = state.situations["night_sites"]["sites"][case["case_id"]]
    template.update(title="切断旧现场的月相残像", description="曾发生月相事件的地点再次出现残留外壳。此公告不公开相关人物身份或私人经历。",
        objective="击败残像并切断现场载体；只处理外壳，不代表相关人物已经完全恢复。",
        scene_id=source["location_id"], enemy_archetype_id=case["topic_id"], reward={},
        required_skill_ids=[], required_item_ids=[], preferred_college_ids=[], preferred_club_ids=[],
        tags=["night", "containment", "afterimage"],
        site_profile={"kind": "containment", "label": "月相残像载体", "initial_state": "残留外壳活跃",
            "resolved_state": "外壳已切断，人物近况需本人确认", "operation": "切断残像载体"})
    return template


def case_for_task(state, task):
    return state.situations.get("campus_anomalies", {}).get("cases", {}).get(task.get("anomaly_case_id"))


def prepare_afterimage_enemy(state, task, enemy):
    case = case_for_task(state, task)
    if case is None:
        return None
    if case["shell"] <= 0:
        raise ValueError("cannot regenerate a cleared afterimage")
    maximum = max(1, (enemy["max_health"] * case["shell"] + INITIAL["shell"] - 1) // INITIAL["shell"])
    enemy.update(display_name="月相残像 · " + enemy["display_name"], max_health=maximum)
    return {"case_id": case["case_id"], "case_revision": case["revision"], "shell": case["shell"], "max_health": maximum}


def night_receipt_valid(state, case, receipt):
    task = state.tasks.get(receipt.get("task_id"), {})
    site = state.situations.get("night_sites", {}).get("sites", {}).get(task.get("night_site_id"), {})
    battle = state.battles.get(receipt.get("battle_id"), {})
    origin = battle.get("anomaly_origin", {})
    return (task.get("anomaly_case_id") == case["case_id"] and task.get("assignee_id") == receipt.get("helper_id")
        and site.get("status") == "resolved" and site.get("battle_id") == receipt.get("battle_id")
        and site.get("receipt", {}).get("actor_id") == receipt.get("helper_id")
        and (site.get("receipt", {}).get("day"), site.get("receipt", {}).get("phase")) == (receipt.get("day"), receipt.get("phase"))
        and battle.get("result") == "victory" and battle.get("phase") == "resolved"
        and battle.get("situation_id") == task.get("task_id") and bool(battle.get("enemy_health"))
        and all(value == 0 for value in battle["enemy_health"].values())
        and origin.get("case_id") == case["case_id"] and origin.get("shell") == receipt.get("before", {}).get("shell")
        and origin.get("case_revision") == receipt.get("revision", 0) - 1)


def finish_afterimage(context, task, battle):
    state, case = context.state, case_for_task(context.state, task)
    if case is None:
        return
    if any(row.get("battle_id") == battle["battle_id"] for row in case["history"]):
        return
    before = {key: case[key] for key in INITIAL}
    receipt = {"day": state.clock.day, "phase": state.clock.phase, "helper_id": task["assignee_id"],
        "claim_id": None, "before": before, "after": {**before, "shell": 0, "coherence": max(0, before["coherence"] - 20)},
        "route": "night_containment", "revision": case["revision"] + 1,
        "task_id": task["task_id"], "battle_id": battle["battle_id"]}
    if not night_receipt_valid(state, case, receipt):
        raise ValueError("afterimage resolution lacks actual source-bound victory")
    case.update(receipt["after"], revision=receipt["revision"], status="easing")
    case["history"].append(receipt)
    context.emit("CAMPUS_ANOMALY_CONTAINED", "旧现场的残留外壳已实际切断；相关人物的心结仍需其本人参与解决。",
        actor_ids=[task["assignee_id"]], target_ids=[case["actor_id"]], visibility="private",
        knowledge_tags=["night", "anomaly"], payload={"case_id": case["case_id"], "task_id": task["task_id"], "battle_id": battle["battle_id"]})


def afterimage_view(state, task):
    if not task.get("anomaly_case_id"):
        return {}
    return {"rule_note": "这是原现场的残留外壳，不是把某个人变成敌人。白天支持可削弱外壳；实际战斗与现场处置只切断外壳，不能替代本人参与。",
        "outcome": "外壳已切断，人物近况需本人确认" if task["state"] == "completed" else "尚未完成切断；公告不等于处理结果"}


def afterimage_invariant(state):
    try:
        active = set()
        for task in state.tasks.values():
            if not task.get("anomaly_case_id"):
                continue
            case = case_for_task(state, task)
            source = state.situations["night_sites"]["sites"][case["case_id"]]
            site = state.situations["night_sites"]["sites"][task["night_site_id"]]
            if (task["scene_id"] != source["location_id"] or site["victim_id"] is not None or site["kind"] != "containment"
                    or task["enemy_archetype_id"] != case["topic_id"] or task["created_day"] < case["created_day"]):
                return ["invalid afterimage source or location"]
            if task["state"] not in TERMINAL_STATES:
                if case["case_id"] in active:
                    return ["duplicate active afterimage task"]
                active.add(case["case_id"])
            if task["state"] == "completed" and not any(r.get("task_id") == task["task_id"] and night_receipt_valid(state, case, r) for r in case["history"]):
                return ["afterimage task completed without case effect"]
        for battle in state.battles.values():
            origin = battle.get("anomaly_origin")
            if origin is None:
                if state.tasks.get(battle.get("situation_id"), {}).get("anomaly_case_id"):
                    return ["missing afterimage battle source"]
                continue
            task = state.tasks[battle["situation_id"]]
            case = case_for_task(state, task)
            archetype = state.metadata["campus_combat"]["enemy_archetypes"][case["topic_id"]]
            expected = max(1, (archetype["max_health"] * origin["shell"] + INITIAL["shell"] - 1) // INITIAL["shell"])
            if (origin["case_id"] != case["case_id"] or type(origin["shell"]) is not int or not 0 < origin["shell"] <= INITIAL["shell"]
                    or origin["max_health"] != expected or len(battle["enemy_units"]) != 1
                    or any(e["max_health"] != expected for e in battle["enemy_units"].values())):
                return ["invalid afterimage enemy projection"]
        return []
    except (KeyError, TypeError, AttributeError, ValueError):
        return ["malformed afterimage linkage"]
