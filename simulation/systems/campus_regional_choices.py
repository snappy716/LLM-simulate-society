"""Response to a read night-forum notice, not omniscient danger sensing."""


def situation_task_motivation(state, actor_id, task):
    actor = state.population[actor_id]
    if (task.get("forum") != "night" or actor_id not in task.get("viewer_ids", ())
            or not state.situations.get("night_world", {}).get("actor_states", {}).get(actor_id, {}).get("night_forum_discovered")):
        return {"adjustment": 0.0, "pressure": 0, "reason": ""}
    pressure = max(0, min(12, int(task.get("pressure_at_creation", 0))))
    if not pressure:
        return {"adjustment": 0.0, "pressure": 0, "reason": ""}
    traits, needs = actor.get("personality", {}), actor.get("needs", {})
    region = task["execution_region_id"]
    local = any((state.places.get(actor.get(key), {}).get("region_id") or actor.get(key)) == region
                for key in ("home_location_id", "primary_location_id"))
    responsibility = traits.get("altruism", 50) / 100 + traits.get("conscientiousness", 50) / 200 + (0.5 if local else 0)
    vitals = actor.get("vitals", {})
    injury = 1 - vitals.get("health", 1) / max(1, vitals.get("max_health", 1))
    pollution = state.situations["night_world"]["actor_states"][actor_id].get("pollution", 0)
    caution = (100 - traits.get("risk_tolerance", 50)) / 100 + needs.get("safety", 0) / 100 + pollution / 80 + injury
    adjustment = round(max(-36, min(36, pressure * 2 * (responsibility - caution))), 3)
    reason = ("已读公告提示该区域有遗留风险，我更想帮助处理" if adjustment > 0 else
              "已读公告提示该区域有遗留风险，我会把稳妥程度列入选择依据" if adjustment < 0 else
              "我会把已读公告的遗留风险和自身准备一起考虑")
    if local:
        reason += "；这里也是我平常生活或活动的地区"
    return {"adjustment": adjustment, "pressure": pressure, "reason": reason + "。"}


def record_regional_notice(state, actor_id, task):
    if task.get("forum") != "night":
        return
    awareness = state.cognition.setdefault("regional_awareness", {})
    own = awareness.setdefault(actor_id, {})
    region = task["execution_region_id"]
    previous = own.get(region)
    # Old posts may be read later; retain the newest publication, not stale risk.
    if previous and previous["published_day"] > task["created_day"]:
        return
    own[region] = {"region_id": region, "pressure": int(task.get("pressure_at_creation", 0)),
        "published_day": task["created_day"], "observed_day": state.clock.day,
        "source_task_id": task["task_id"]}


def regional_awareness_invariant(state):
    try:
        for task in state.tasks.values():
            choice = task.get("situation_choice")
            if choice is not None and (task.get("forum") != "night" or choice["actor_id"] == "player"
                    or choice["actor_id"] != task.get("assignee_id") or choice["actor_id"] not in task["viewer_ids"]
                    or type(choice["pressure"]) is not int or not 1 <= choice["pressure"] <= 12
                    or choice["pressure"] != task.get("pressure_at_creation")
                    or not isinstance(choice["reason"], str) or not 1 <= len(choice["reason"]) <= 200):
                return ["invalid regional choice receipt"]
        for actor_id, regions in state.cognition.get("regional_awareness", {}).items():
            if actor_id not in state.population:
                return ["unknown regional notice reader"]
            for region, row in regions.items():
                task = state.tasks[row["source_task_id"]]
                if (row["region_id"] != region or task.get("execution_region_id") != region or task.get("forum") != "night"
                        or actor_id not in task["viewer_ids"] or row["published_day"] != task["created_day"]
                        or type(row["pressure"]) is not int or row["pressure"] != task.get("pressure_at_creation", 0)
                        or not 0 <= row["pressure"] <= 12 or not row["published_day"] <= row["observed_day"] <= state.clock.day):
                    return ["invalid observed regional notice"]
        return []
    except (KeyError, TypeError, AttributeError):
        return ["malformed regional awareness"]
