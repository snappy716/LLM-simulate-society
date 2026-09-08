"""Persistent night objectives. Winning a fight is not evidence of a rescue.

Only actors already at a real location can become stranded. All rescue movement
uses the campus graph and its common traversal handler; no off-screen success.
"""
from dataclasses import replace

from simulation.actions.commands import SimulationCommand
from simulation.systems.transactions import TransactionOutcome
from simulation.systems.campus_vitals import actor_layer, battle_locked


SITE_KINDS = {"rescue", "stabilize", "containment"}


def site_for_task(state, task):
    return state.situations.get("night_sites", {}).get("sites", {}).get(task.get("night_site_id"))


def captive_site(state, actor_id):
    return next((site for site in state.situations.get("night_sites", {}).get("sites", {}).values()
                 if site.get("victim_id") == actor_id and site["status"] in {"active", "suppressed"}), None)


def rescued_this_phase(state, actor_id):
    return any(site.get("victim_id") == actor_id and site["status"] == "resolved"
               and site["receipt"]["day"] == state.clock.day and site["receipt"]["phase"] == state.clock.phase
               for site in state.situations.get("night_sites", {}).get("sites", {}).values())


def validate_site_profile(profile):
    if (not isinstance(profile, dict) or profile.get("kind") not in SITE_KINDS
            or any(not isinstance(profile.get(key), str) or not profile[key]
                   for key in ("label", "initial_state", "resolved_state", "operation"))
            or (profile["kind"] == "rescue" and not isinstance(profile.get("safe_location_id"), str))):
        raise ValueError("invalid night site profile")


def rescue_candidates(state, scene_id, safe_id, graph):
    from simulation.systems.campus_parties import party_for_actor
    from simulation.systems.campus_departures import has_upcoming_departure
    from simulation.systems.campus_enemy_turns import recovering_from_defeat
    from simulation.systems.campus_schedules import current_schedule_slot
    region = state.places[scene_id].get("region_id") or scene_id
    candidates = []
    for actor_id, actor in sorted(state.population.items()):
        location = actor.get("current_location_id")
        place = state.places.get(location, {})
        if (actor_id == "player" or actor.get("role_kind") != "student"
                or (place.get("region_id") or location) != region or location == safe_id
                or "medical" in place.get("tags", ())
                or actor_layer(state, actor_id) != "surface" or captive_site(state, actor_id)
                or party_for_actor(state, actor_id) or has_upcoming_departure(state, actor_id)
                or recovering_from_defeat(state, actor_id) or battle_locked(state, actor_id)
                or actor.get("active_forum_task_id") or actor.get("vitals", {}).get("health", 0) <= 0
                or current_schedule_slot(state, actor_id).get("priority", 0) >= 90):
            continue
        late = actor.get("weekly_schedule", {}).get(str((state.clock.day - 1) % 7), {}).get("late_night", {})
        if late.get("priority", 0) >= 90:
            continue
        if all(graph.is_open(location, phase) and graph.shortest_route(location, safe_id, phase=phase,
                   access_tags=actor.get("access_tags", ())) is not None for phase in ("evening", "late_night")):
            candidates.append(actor_id)
    return candidates


def create_night_site(context, task, profile, victim_id=None):
    validate_site_profile(profile)
    state = context.state
    if profile["kind"] == "rescue" and victim_id is None:
        raise ValueError("rescue requires a real eligible actor")
    site_id = "night-site:" + task["task_id"]
    if victim_id:
        task["scene_id"] = state.population[victim_id]["current_location_id"]
        task["execution_region_id"] = state.places[task["scene_id"]].get("region_id") or task["scene_id"]
        task["objective"] = f"压制现场威胁后，沿校园道路护送{state.population[victim_id]['display_name']}到{state.places[profile['safe_location_id']]['name']}。"
        night_actor = state.situations["night_world"]["actor_states"][victim_id]
        night_actor.update(layer="night", last_transition_day=state.clock.day, last_transition_phase=state.clock.phase)
        night_actor["pollution"] = min(100, night_actor["pollution"] + 3)
        state.population[victim_id].pop("current_activity", None)
        state.population[victim_id].pop("current_decision", None)
    site = {"site_id": site_id, "task_id": task["task_id"], "kind": profile["kind"],
        "label": profile["label"], "initial_state": profile["initial_state"], "resolved_state": profile["resolved_state"],
        "operation": profile["operation"], "location_id": task["scene_id"], "region_id": task["execution_region_id"],
        "created_day": state.clock.day, "expires_day": task["expires_day"], "status": "active", "revision": 1,
        "victim_id": victim_id, "safe_location_id": profile.get("safe_location_id"), "battle_id": None, "receipt": None}
    state.situations.setdefault("night_sites", {"schema_version": 1, "sites": {}})["sites"][site_id] = site
    task.update(resolution_kind=profile["kind"], night_site_id=site_id)
    if victim_id:
        context.emit("NPC_STRANDED_IN_NIGHT", f"{state.population[victim_id]['display_name']}在原地点陷入异常，等待安全护送。",
            actor_ids=[victim_id], scene_id=site["location_id"], visibility="secret", knowledge_tags=["night", "rescue"],
            payload={"site_id": site_id, "task_id": task["task_id"], "location_id": site["location_id"]})


def site_exposure(state, actor_id):
    location = state.population[actor_id].get("current_location_id")
    region = state.places.get(location, {}).get("region_id") or location
    from simulation.systems.campus_situations import regional_pressure
    return regional_pressure(state, location) // 4 + min(3, sum(site["region_id"] == region and site["status"] in {"active", "suppressed"}
                      for site in state.situations.get("night_sites", {}).get("sites", {}).values()))


def upkeep_night_sites(context):
    state, released = context.state, 0
    for site in state.situations.get("night_sites", {}).get("sites", {}).values():
        if site["status"] not in {"active", "suppressed"} or state.clock.day <= site["expires_day"]:
            continue
        site.update(status="expired", revision=site["revision"] + 1)
        victim_id = site["victim_id"]
        if victim_id:
            # Dawn releases at the actual location, not a fabricated rescue/home warp.
            actor = state.population[victim_id]
            actor["vitals"]["health"] = max(1, actor["vitals"]["health"] - 10)
            state.situations["night_world"]["actor_states"][victim_id]["layer"] = "surface"
            released += 1
            context.emit("NIGHT_RESCUE_MISSED", f"晨光使{actor['display_name']}在原地点脱离夜相，但未获得安全护送并留下伤势。",
                actor_ids=[victim_id], scene_id=actor["current_location_id"], visibility="secret",
                knowledge_tags=["night", "rescue", "expired"], payload={"site_id": site["site_id"], "health": actor["vitals"]["health"]})
    return {"night_stranded_released_count": released}


def make_site_resolution_handler(graph, action_policy):
    from simulation.systems.campus_locations import make_traverse_location_handler
    traverse = make_traverse_location_handler(graph)
    def handle(context, command):
        state, actor_id = context.state, command.actor_id
        def fail(code, message):
            return TransactionOutcome(False, False, code, message)
        if actor_id not in state.population or (actor_id != "player" and command.source != "rule"):
            return fail("actor_not_authorized", "不能替其他人处理现场。")
        if command.issued_day != state.clock.day or command.issued_phase != state.clock.phase:
            return fail("command_clock_mismatch", "现场请求已过期。")
        if set(command.parameters) - {"task_id", "expected_task_revision"}:
            return fail("invalid_site_resolution", "现场结果必须通过实际行动产生。")
        task_id = command.parameters.get("task_id")
        task = state.tasks.get(task_id, {}) if isinstance(task_id, str) else {}
        site = site_for_task(state, task)
        if not site or task.get("state") != "locked" or task.get("assignee_id") != actor_id:
            return fail("task_not_owned", "没有持有可处理的现场任务。")
        if type(command.parameters.get("expected_task_revision")) is not int or command.parameters["expected_task_revision"] != task["lock_revision"]:
            return fail("task_revision_conflict", "任务状态已改变，请刷新。")
        if state.clock.day > site["expires_day"] or state.clock.phase not in {"evening", "late_night"}:
            return fail("invalid_phase", "已超过当夜处理窗口。")
        if actor_layer(state, actor_id) != "night":
            return fail("night_layer_required", "请进入夜相现场。")
        actor = state.population[actor_id]
        if actor["current_location_id"] != site["location_id"]:
            return fail("task_location_required", "必须实际到达目标所在地点。")
        if battle_locked(state, actor_id) or captive_site(state, actor_id):
            return fail("battle_already_active", "当前不能自由处理现场。")
        if actor["vitals"]["health"] <= 0:
            return fail("incapacitated", "当前无法处理现场。")
        battle = state.battles.get(site["battle_id"], {})
        if (site["status"] != "suppressed" or battle.get("result") != "victory"
                or battle.get("phase") != "resolved" or battle.get("situation_id") != task_id):
            return fail("site_threat_active", "现场威胁尚未压制。")
        routes = {}
        victim_id = site["victim_id"]
        if victim_id:
            victim = state.population.get(victim_id, {})
            if (victim.get("current_location_id") != site["location_id"] or actor_layer(state, victim_id) != "night"
                    or victim.get("vitals", {}).get("health", 0) <= 0 or captive_site(state, victim_id) is not site):
                return fail("rescue_target_unavailable", "被救对象不在现场或无法安全移动，不能虚构完成。")
            for traveller in (actor_id, victim_id):
                route = graph.shortest_route(site["location_id"], site["safe_location_id"], phase=state.clock.phase,
                                             access_tags=state.population[traveller].get("access_tags", ()))
                if route is None:
                    return fail("rescue_route_unavailable", "当前没有双方都能通行的安全护送路线。")
                routes[traveller] = route
            if [step.passage_id for step in routes[actor_id].steps] != [step.passage_id for step in routes[victim_id].steps]:
                return fail("rescue_route_unavailable", "双方缺少共同可通行的护送路线。")
        # Combat paid for immediate follow-through. A later replacement pays its own action.
        cost = int(actor_id not in battle.get("participant_ids", ()))
        if cost:
            from simulation.systems.time import consume_major_action
            spent = consume_major_action(state, action_policy, command)
            if not spent.success:
                return fail(spent.code, spent.message)
        site["status"] = "escorting"
        if victim_id:
            for step in routes[actor_id].steps:
                for traveller in (actor_id, victim_id):
                    result = traverse(context, replace(command, actor_id=traveller, source="rule",
                        action_id="TRAVERSE_LOCATION_PASSAGE", parameters={"passage_id": step.passage_id}))
                    if not result.success:
                        raise RuntimeError("prevalidated escort route failed: " + result.code)
            state.situations["night_world"]["actor_states"][victim_id]["layer"] = "surface"
        receipt = {"actor_id": actor_id, "victim_id": victim_id, "site_id": site["site_id"], "battle_id": battle["battle_id"],
            "day": state.clock.day, "phase": state.clock.phase, "destination_id": site["safe_location_id"] or site["location_id"],
            "passage_ids": [step.passage_id for step in routes[actor_id].steps] if victim_id else [], "major_action_cost": cost}
        site.update(status="resolved", revision=site["revision"] + 1, receipt=receipt)
        from simulation.systems.campus_situations import advance_campus_situations
        advance_campus_situations(context)
        from simulation.systems.campus_tasks import complete_assigned_task
        if not complete_assigned_task(context, actor_id, {"task_id": task_id, "site_resolution": True}):
            raise RuntimeError("validated site resolution could not settle task")
        message = f"{site['operation']}：{site['resolved_state']}。现场目标已实际完成，报酬已结算。"
        task["history"].append({"day": state.clock.day, "phase": state.clock.phase, "kind": "site_resolved", "message": message})
        context.emit("NIGHT_SITE_RESOLVED", message, actor_ids=[actor_id], target_ids=[victim_id] if victim_id else [],
            scene_id=receipt["destination_id"], visibility="secret", knowledge_tags=["night", "task", site["kind"]], payload=receipt)
        return TransactionOutcome(True, True, "success", message, commit=True,
            payload={"site_resolution": receipt, "task_completed": True, "effects": {}})
    return handle


def finish_site_combat(context, battle, leader_id, handler):
    state = context.state
    task = state.tasks[battle["situation_id"]]
    site = site_for_task(state, task)
    if not site:
        return None
    site.update(status="suppressed", battle_id=battle["battle_id"], revision=site["revision"] + 1)
    if handler is None:
        return False
    result = handler(context, SimulationCommand(command_id="site-follow-through:" + battle["battle_id"], actor_id=leader_id,
        action_id="RESOLVE_NIGHT_SITE", expected_world_revision=state.revision, issued_day=state.clock.day,
        issued_phase=state.clock.phase, source="player" if leader_id == "player" else "rule",
        parameters={"task_id": task["task_id"], "expected_task_revision": task["lock_revision"]}))
    if not result.success:
        task["history"].append({"day": state.clock.day, "phase": state.clock.phase, "kind": "site_blocked",
            "message": "威胁已压制，现场目标尚未完成：" + result.message})
    return result.success


def site_view(state, actor_id, task):
    site = site_for_task(state, task)
    if not site:
        return {}
    status = {"active": site["initial_state"], "suppressed": "威胁已压制，待处理现场", "resolved": site["resolved_state"], "expired": "已随晨光失效"}[site["status"]]
    return {"kind": site["kind"], "label": site["label"], "status": status,
        "can_follow_through": site["status"] == "suppressed" and task.get("assignee_id") == actor_id,
        "rule_note": "战斗压制威胁后实际" + site["operation"] + "，完成现场目标才发奖。",
        "victim_name": state.population[site["victim_id"]]["display_name"] if site["victim_id"] else "",
        "destination_name": state.places[site["safe_location_id"]]["name"] if site["safe_location_id"] else ""}


def night_sites_invariant(state):
    ledger = state.situations.get("night_sites")
    if ledger is None:
        return [] if not any(t.get("night_site_id") for t in state.tasks.values()) else ["night task without site"]
    try:
        if ledger["schema_version"] != 1:
            return ["invalid night sites schema"]
        if any(task.get("night_site_id") and site_for_task(state, task) is None for task in state.tasks.values()):
            return ["task references a missing night objective"]
        captives = set()
        for site_id, site in ledger["sites"].items():
            task = state.tasks[site["task_id"]]
            if (site_id != site["site_id"] or task.get("night_site_id") != site_id or task.get("resolution_kind") != site["kind"]
                    or site["kind"] not in SITE_KINDS or site["location_id"] != task["scene_id"]
                    or site["region_id"] != (state.places[site["location_id"]].get("region_id") or site["location_id"])
                    or type(site["created_day"]) is not int or site["created_day"] < 1
                    or site["expires_day"] != task["expires_day"] or site["status"] not in {"active", "suppressed", "resolved", "expired"}
                    or type(site["revision"]) is not int or site["revision"] < 1):
                return ["invalid night objective site"]
            victim_id = site["victim_id"]
            if (site["kind"] == "rescue") != bool(victim_id) or (victim_id and (victim_id == "player" or victim_id not in state.population or site["safe_location_id"] not in state.places)):
                return ["invalid rescue target"]
            if victim_id and site["status"] in {"active", "suppressed"}:
                if (victim_id in captives or actor_layer(state, victim_id) != "night"
                        or state.population[victim_id]["current_location_id"] != site["location_id"]
                        or state.population[victim_id].get("active_forum_task_id") or battle_locked(state, victim_id)):
                    return ["stranded actor moved or double booked"]
                captives.add(victim_id)
            if site["status"] in {"suppressed", "resolved"}:
                battle = state.battles[site["battle_id"]]
                if battle["result"] != "victory" or battle["phase"] != "resolved" or battle["situation_id"] != task["task_id"]:
                    return ["night objective missing actual suppression"]
            if site["status"] == "resolved":
                receipt = site["receipt"]
                if (task["state"] != "completed" or receipt["actor_id"] != task["assignee_id"]
                        or receipt["actor_id"] not in state.population
                        or receipt["site_id"] != site_id or receipt["battle_id"] != site["battle_id"]
                        or receipt["victim_id"] != victim_id or receipt["destination_id"] != (site["safe_location_id"] or site["location_id"])
                        or receipt["phase"] not in {"evening", "late_night"} or not site["created_day"] <= receipt["day"] <= site["expires_day"]
                        or task.get("completion_evidence") != {"kind": "site_resolution", "site_id": site_id, "battle_id": site["battle_id"]}):
                    return ["invalid physical site completion receipt"]
                if (type(receipt["major_action_cost"]) is not int
                        or receipt["major_action_cost"] != int(receipt["actor_id"] not in battle["participant_ids"])):
                    return ["invalid site action accounting"]
                current = site["location_id"]
                if not isinstance(receipt["passage_ids"], list) or (not victim_id and receipt["passage_ids"]):
                    return ["invalid site movement receipt"]
                for passage_id in receipt["passage_ids"]:
                    passage = state.metadata["campus_passages"][passage_id]
                    if current == passage["from_id"]:
                        current = passage["to_id"]
                    elif current == passage["to_id"] and passage["bidirectional"]:
                        current = passage["from_id"]
                    else:
                        return ["disconnected escort route"]
                if current != receipt["destination_id"]:
                    return ["escort did not reach safety"]
            elif task["state"] == "completed":
                return ["unresolved night objective awarded"]
    except (KeyError, TypeError, AttributeError):
        return ["invalid nested night objective state"]
    return []
