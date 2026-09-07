"""NPC cooperative departures and real daytime provisioning, not player control."""
from simulation.systems.campus_parties import create_party, party_for_actor, invitation_assessment
from simulation.systems.campus_departures import active_departure, has_upcoming_departure, assess_departure
from simulation.systems.campus_messaging import are_phone_contacts, append_structured_phone_message
from simulation.systems.campus_vitals import actor_layer, battle_locked
from simulation.systems.campus_enemy_turns import recovering_from_defeat
from simulation.systems.campus_inventory import _inventory, _catalog
from simulation.systems.campus_schedules import current_schedule_slot
from simulation.systems.campus_social import adjust_relationship
from simulation.actions.commands import SimulationCommand


def _ledger(state):
    return state.cognition.setdefault("night_expeditions", {"schema_version": 1, "plans": {}, "last_participation": {}, "supply_day": {}})


def active_expedition(state, actor_id, *, leader_only=False):
    for plan in state.cognition.get("night_expeditions", {}).get("plans", {}).values():
        if (plan["status"] == "reserved" and actor_id in plan["member_ids"]
                and (not leader_only or actor_id == plan["leader_id"])):
            return plan
    return None


def own_expedition_due(state, actor_id):
    plan = active_expedition(state, actor_id, leader_only=True)
    return bool(plan and plan["day"] == state.clock.day and plan["phase"] == state.clock.phase and active_departure(state, actor_id))


def already_fought_this_phase(state, actor_id):
    return state.cognition.get("night_expeditions", {}).get("last_participation", {}).get(actor_id) == [state.clock.day, state.clock.phase]


def _note(context, plan, kind, message):
    plan["history"].append({"day": context.state.clock.day, "phase": context.state.clock.phase, "kind": kind, "message": message})
    task = context.state.tasks.get(plan["task_id"], {})
    task.setdefault("history", []).append(dict(plan["history"][-1]))
    context.emit("NPC_EXPEDITION_UPDATED", message, actor_ids=plan["member_ids"], visibility="secret",
                 knowledge_tags=["night", "party", "commitment"], payload={"task_id": plan["task_id"], "status": plan["status"], "kind": kind})


def finish_expedition(context, task_id, receipt):
    battle = context.state.battles.get(receipt["battle_id"], {})
    if (battle.get("situation_id") != task_id or battle.get("phase") != "resolved"
            or battle.get("participant_ids") != receipt["actor_ids"] or not receipt["actor_ids"]
            or battle.get("result") != receipt["result"] or "player" in receipt["actor_ids"]):
        raise ValueError("expedition requires an actual resolved NPC battle")
    ledger = _ledger(context.state)
    from simulation.systems.campus_tasks import phase_index
    for actor_id in receipt["actor_ids"]:
        previous = ledger["last_participation"].get(actor_id)
        if previous is None or phase_index(*previous) <= phase_index(receipt["day"], receipt["phase"]):
            ledger["last_participation"][actor_id] = [receipt["day"], receipt["phase"]]
    plan = ledger["plans"].get(task_id)
    if plan is None or plan["status"] != "reserved":
        return
    plan.update(status="completed", battle_id=receipt["battle_id"], actual_member_ids=list(receipt["actor_ids"]))
    if receipt["result"] == "victory":
        total = int(context.state.tasks[task_id].get("reward", {}).get("wealth", 0))
        share = total // len(receipt["actor_ids"])
        plan["settled_rewards"] = {plan["leader_id"]: total}
        for member_id in receipt["actor_ids"]:
            if member_id == plan["leader_id"]:
                continue
            context.state.population[plan["leader_id"]]["wealth"] -= share
            context.state.population[member_id]["wealth"] += share
            plan["settled_rewards"][plan["leader_id"]] -= share
            plan["settled_rewards"][member_id] = share
            adjust_relationship(context.state, member_id, plan["leader_id"], {"trust": 2})
            adjust_relationship(context.state, plan["leader_id"], member_id, {"trust": 2})
        shares = "、".join(f"{context.state.population[actor]['display_name']} {amount}" for actor, amount in plan["settled_rewards"].items())
        _note(context, plan, "expedition_reward", f"实际参战 {len(receipt['actor_ids'])} 人，原任务报酬 {total} 已按约定分配：{shares}。")
    names = "、".join(context.state.population[actor]["display_name"] for actor in receipt["actor_ids"])
    absent = [actor for actor in plan["member_ids"] if actor not in receipt["actor_ids"]]
    suffix = "；未能参战：" + "、".join(context.state.population[actor]["display_name"] for actor in absent) if absent else ""
    _note(context, plan, "expedition_result", f"本次同行结束，实际参战：{names}{suffix}。")
    context.state.parties.pop(plan["party_id"], None)


def upkeep_expeditions(context):
    state, closed = context.state, 0
    plans = state.cognition.get("night_expeditions", {}).get("plans", {})
    for plan in plans.values():
        if plan["status"] != "reserved":
            continue
        task = state.tasks.get(plan["task_id"], {})
        party = state.parties.get(plan["party_id"], {})
        changed = party.get("member_ids") != plan["member_ids"] or any(
            party.get("members", {}).get(actor, {}).get("departure") != {"day": plan["day"], "phase": plan["phase"]}
            for actor in plan["member_ids"])
        invalid = changed or task.get("state") not in {"locked", "in_progress"} or task.get("assignee_id") != plan["leader_id"]
        if state.clock.day <= plan["day"] and not invalid:
            continue
        plan["status"] = "cancelled" if invalid else "expired"
        _note(context, plan, "expedition_cancelled", "目标、同行承诺已变化或未能按时出发，本次同行约定结束。")
        if not invalid:
            for actor_id in plan["member_ids"]:
                if actor_id != plan["leader_id"]:
                    adjust_relationship(state, actor_id, plan["leader_id"], {"trust": -1})
        party = state.parties.get(plan["party_id"])
        if party and party.get("purpose_id") == "autonomous_expedition":
            del state.parties[plan["party_id"]]
        closed += 1
    return {"npc_expeditions_closed": closed}


def _can_contact(state, first, second):
    return are_phone_contacts(state, first, second) or (actor_layer(state, first) == actor_layer(state, second)
        and state.population[first]["current_location_id"] == state.population[second]["current_location_id"])


def form_npc_expeditions(context, graph, party_policy, party_handler, messaging_policy):
    state, count = context.state, 0
    if state.clock.phase != "evening":
        return {"npc_expeditions_formed": 0}
    ledger = _ledger(state)
    attempted = ledger.setdefault("attempted_task_ids", [])
    tasks = [task for task in state.tasks.values() if task.get("forum") == "night" and task.get("state") == "locked"
             and task.get("resolution_kind") != "field_recon"
             and task.get("assignee_id") not in {None, "player"} and task["task_id"] not in ledger["plans"]
             and task["task_id"] not in attempted]
    for task in tasks:
        leader_id = task["assignee_id"]
        if party_for_actor(state, leader_id) or has_upcoming_departure(state, leader_id) or recovering_from_defeat(state, leader_id):
            continue
        attempted.append(task["task_id"])
        party = create_party(state, leader_id, party_policy, purpose_id="autonomous_expedition")
        plan = {"task_id": task["task_id"], "party_id": party["party_id"], "leader_id": leader_id, "day": state.clock.day,
                "phase": "late_night", "member_ids": [leader_id], "status": "reserved", "history": [], "responses": []}
        candidates = []
        for target, actor in state.population.items():
            if (target in {leader_id, "player"} or not _can_contact(state, leader_id, target)
                    or actor.get("night_access") not in {"capable", "willing"} or actor.get("active_forum_task_id")
                    or party_for_actor(state, target) or has_upcoming_departure(state, target)
                    or battle_locked(state, target) or recovering_from_defeat(state, target)):
                continue
            slot = actor.get("weekly_schedule", {}).get(str((state.clock.day - 1) % 7), {}).get("late_night", {})
            if slot.get("priority", 0) >= 90 or actor.get("vitals", {}).get("health", 0) <= 0:
                continue
            if graph.shortest_route(actor["current_location_id"], task["scene_id"], phase="late_night", access_tags=actor.get("access_tags", ())) is None:
                continue
            assessment = invitation_assessment(state, leader_id, target, party_policy)
            candidates.append((-assessment.get("score", -1000), target))
        for _, target in sorted(candidates)[:4]:
            if len(party["member_ids"]) >= party_policy.max_members:
                break
            trial = {**party, "member_ids": [*party["member_ids"], target]}
            assessment = assess_departure(state, trial, state.clock.day, "late_night", party_policy)
            if any(item["reason"] != "insufficient_willingness" for item in assessment["blocked"]):
                continue
            command = SimulationCommand(f"{context.command.command_id}:expedition-invite:{leader_id}:{target}", leader_id,
                "INVITE_PARTY_MEMBER", state.revision, parameters={"target_id": target}, source="rule",
                issued_day=state.clock.day, issued_phase=state.clock.phase)
            outcome = party_handler(context, command)
            if not outcome.success and outcome.code != "invitation_declined":
                raise RuntimeError("unexpected autonomous invitation failure: " + outcome.code)
            plan["responses"].append({"actor_id": target, "accepted": outcome.success, "reason": outcome.code})
            if are_phone_contacts(state, leader_id, target):
                title = task["title"]
                append_structured_phone_message(context, leader_id, target, f"我接了《{title}》，想约深夜同行；以实际抵达和出战为准，报酬按实际参战人数均分。", messaging_policy, source="rule")
                append_structured_phone_message(context, target, leader_id,
                    "我愿意同行，约定时段会预留行动。" if outcome.success else "这次我不方便同行。", messaging_policy, source="rule")
        # A lone actor does not need a separate appointment; existing solo flow remains.
        if len(party["member_ids"]) == 1:
            del state.parties[party["party_id"]]
            continue
        reservation = SimulationCommand(f"{context.command.command_id}:expedition-reserve:{leader_id}", leader_id,
            "RESERVE_PARTY_DEPARTURE", state.revision, parameters={"day": state.clock.day, "phase": "late_night"},
            source="rule", issued_day=state.clock.day, issued_phase=state.clock.phase)
        outcome = party_handler(context, reservation)
        if not outcome.success:
            # Eligibility is rechecked by the common handler. Never leave phantom parties.
            for target in party["member_ids"][1:]:
                if are_phone_contacts(state, leader_id, target):
                    append_structured_phone_message(context, leader_id, target,
                        "出发预约未能协调成功，这次同行取消，不需要继续预留行动。", messaging_policy, source="rule")
            del state.parties[party["party_id"]]
            continue
        plan["member_ids"] = list(party["member_ids"])
        ledger["plans"][task["task_id"]] = plan
        names = "、".join(state.population[actor]["display_name"] for actor in plan["member_ids"])
        _note(context, plan, "expedition_reserved", f"{names}约定深夜同行；主要行动已预留，抵达后再确认实际阵容，报酬按实际参战人数均分。")
        count += 1
    return {"npc_expeditions_formed": count}


def prepare_npc_combat_supplies(context, graph, traverse_handler, inventory_handler):
    """Experienced/willing NPCs buy one real healing supply before routine activity."""
    state, purchased, route_steps = context.state, 0, 0
    if state.clock.phase != "afternoon":
        return {"npc_combat_supply_purchases": 0, "npc_combat_supply_route_steps": 0}
    ledger, catalog = _ledger(state), _catalog(state)
    for actor_id, actor in sorted(state.population.items()):
        if purchased >= 12:
            break
        night = state.situations["night_world"]["actor_states"][actor_id]
        if (actor_id == "player" or actor.get("night_access") not in {"capable", "willing"}
                or not (actor.get("night_access") == "willing" or night.get("night_forum_discovered"))
                or actor_layer(state, actor_id) != "surface" or battle_locked(state, actor_id) or recovering_from_defeat(state, actor_id)
                or actor.get("active_forum_task_id") or has_upcoming_departure(state, actor_id)
                or current_schedule_slot(state, actor_id).get("priority", 0) >= 90
                or ledger["supply_day"].get(actor_id) == state.clock.day):
            continue
        slots = actor.get("weekly_schedule", {}).get(str((state.clock.day - 1) % 7), {})
        if any(slots.get(phase, {}).get("priority", 0) >= 90 for phase in ("evening", "late_night")):
            continue
        quantities = state.inventories["actors"][actor_id]["quantities"]
        if any(state.inventories["rules"].get(item, {}).get("heal_percent", 0) > 0 and amount > 0 for item, amount in quantities.items()):
            continue
        choices = []
        for shop in state.inventories["shops"].values():
            if state.clock.phase not in state.places[shop["location_id"]].get("open_phases", []):
                continue
            for item_id, stock in shop["quantities"].items():
                if stock <= 0 or item_id not in shop["accepted_item_ids"] or not catalog[item_id].tradeable or state.inventories["rules"].get(item_id, {}).get("heal_percent", 0) <= 0:
                    continue
                price = catalog[item_id].base_price
                if actor["wealth"] - price < 30 or not _inventory(state.inventories["actors"][actor_id]).can_add(catalog[item_id], 1, catalog):
                    continue
                route = graph.shortest_route(actor["current_location_id"], shop["location_id"], phase=state.clock.phase, access_tags=actor.get("access_tags", ()))
                if route is not None:
                    choices.append((price, route.total_minutes, shop["id"], item_id, shop, route))
        if not choices:
            continue
        _, _, _, item_id, shop, route = min(choices, key=lambda c: c[:4])
        actor.pop("current_activity", None)
        actor.pop("current_decision", None)
        for index, step in enumerate(route.steps):
            moved = traverse_handler(context, SimulationCommand(f"{context.command.command_id}:supply-move:{actor_id}:{index}", actor_id,
                "TRAVERSE_LOCATION_PASSAGE", state.revision, parameters={"passage_id": step.passage_id}, source="rule",
                issued_day=state.clock.day, issued_phase=state.clock.phase))
            if not moved.success:
                raise RuntimeError("prepared supply route became invalid: " + moved.code)
            route_steps += 1
        outcome = inventory_handler(context, SimulationCommand(f"{context.command.command_id}:combat-supply:{actor_id}", actor_id,
            "BUY_ITEM", state.revision, parameters={"shop_id": shop["id"], "item_id": item_id, "quantity": 1}, source="rule",
            issued_day=state.clock.day, issued_phase=state.clock.phase))
        if outcome.success:
            ledger["supply_day"][actor_id] = state.clock.day
            purchased += 1
            context.emit("NPC_COMBAT_SUPPLY_PREPARED", "为可能的夜间调查购买了一份实际医疗物资。", actor_ids=[actor_id],
                scene_id=shop["location_id"], payload={"item_id": item_id, "quantity": 1, "shop_id": shop["id"]}, visibility="private", knowledge_tags=["inventory", "preparation"])
        elif outcome.code not in {"shop_closed", "item_missing", "stock_insufficient", "inventory_full", "insufficient_funds"}:
            raise RuntimeError("unexpected combat supply refusal: " + outcome.code)
    return {"npc_combat_supply_purchases": purchased, "npc_combat_supply_route_steps": route_steps}


def expedition_invariant(state):
    ledger = state.cognition.get("night_expeditions")
    if ledger is None:
        return []
    errors = []
    try:
        if ledger["schema_version"] != 1:
            errors.append("invalid expedition schema")
        attempted = ledger.get("attempted_task_ids", [])
        if not isinstance(attempted, list) or len(set(attempted)) != len(attempted) or any(task not in state.tasks for task in attempted):
            errors.append("invalid expedition invitation attempts")
        for actor, marker in ledger["last_participation"].items():
            if actor == "player" or actor not in state.population or not isinstance(marker, list) or len(marker) != 2 or type(marker[0]) is not int or marker[0] < 1 or marker[1] not in {"evening", "late_night"}:
                errors.append("invalid expedition participation marker")
        for actor, day in ledger["supply_day"].items():
            if actor == "player" or actor not in state.population or type(day) is not int or not 1 <= day <= state.clock.day:
                errors.append("invalid expedition supply marker")
        for task_id, plan in ledger["plans"].items():
            if (task_id != plan["task_id"] or task_id not in state.tasks or plan["leader_id"] not in plan["member_ids"]
                    or "player" in plan["member_ids"] or len(set(plan["member_ids"])) != len(plan["member_ids"])
                    or any(actor not in state.population for actor in plan["member_ids"])
                    or plan["status"] not in {"reserved", "completed", "cancelled", "expired"}
                    or type(plan["day"]) is not int or plan["day"] < 1 or plan["phase"] != "late_night"):
                errors.append("invalid NPC expedition plan")
            if plan["status"] == "reserved":
                party = state.parties.get(plan["party_id"], {})
                if party.get("purpose_id") != "autonomous_expedition" or party.get("leader_id") != plan["leader_id"] or party.get("member_ids") != plan["member_ids"]:
                    errors.append("expedition party commitment mismatch")
                elif any(party["members"][actor].get("departure") != {"day": plan["day"], "phase": plan["phase"]} for actor in plan["member_ids"]):
                    errors.append("expedition departure reservation mismatch")
            if plan["status"] == "completed":
                battle = state.battles.get(plan["battle_id"], {})
                actual = plan["actual_member_ids"]
                if (battle.get("phase") != "resolved" or battle.get("situation_id") != task_id
                        or actual != battle.get("participant_ids") or plan["leader_id"] not in actual
                        or not set(actual) <= set(plan["member_ids"])):
                    errors.append("expedition result lacks actual battle proof")
                rewards = plan.get("settled_rewards", {})
                if battle.get("result") == "victory":
                    total = state.tasks[task_id].get("reward", {}).get("wealth", 0)
                    if (set(rewards) != set(actual) or any(type(value) is not int or value < 0 for value in rewards.values())
                            or sum(rewards.values()) != total
                            or any(rewards[actor] != total // len(actual) for actor in actual if actor != plan["leader_id"])):
                        errors.append("expedition rewards are not conserved")
                elif rewards:
                    errors.append("failed expedition must not pay rewards")
    except (KeyError, TypeError, ValueError, AttributeError):
        errors.append("invalid nested expedition state")
    return errors
