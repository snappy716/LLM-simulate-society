"""Material assistance promises: ask, choose, prepare and physically deliver.

Promises never create inventory. The only fulfillment path calls the common
GIVE_ITEM handler after validating an accepted commitment and its participants.
"""
from copy import deepcopy
from dataclasses import replace
from simulation.actions.commands import SimulationCommand
from simulation.systems.campus_inventory import _catalog, _inventory, make_campus_inventory_handler
from simulation.systems.campus_trade import tick, reserve_quantity, carried_nutrition
from simulation.systems.campus_vitals import actor_layer, battle_locked
from simulation.systems.campus_departures import active_departure
from simulation.systems.campus_messaging import are_phone_contacts, append_structured_phone_message
from simulation.systems.campus_social import DEFAULT_RELATIONSHIP, adjust_relationship
from simulation.systems.transactions import TransactionOutcome

ASSISTANCE_ACTIONS = ("REQUEST_MATERIAL_HELP", "RESPOND_MATERIAL_HELP", "DELIVER_MATERIAL_HELP", "CANCEL_MATERIAL_HELP", "WAIT_MATERIAL_HELP")
ITEMS = ("blank_notebook", "bandage_roll", "bread_loaf")
OPEN = {"pending", "accepted"}
STATUSES = OPEN | {"declined", "fulfilled", "expired", "cancelled", "no_longer_needed"}
STATUS_TEXT = {"pending": "等待答复", "accepted": "已答应，尚未交付", "declined": "已拒绝", "fulfilled": "已实际交付",
               "expired": "约定已到期", "cancelled": "已撤回", "no_longer_needed": "需求已由其他途径解决"}


def _ledger(state):
    return state.cognition.setdefault("material_assistance", {"schema_version": 1, "sequence": 0, "requests": {}})


def needs_item(state, actor_id, item_id):
    quantities = state.inventories.get("actors", {}).get(actor_id, {}).get("quantities", {})
    actor = state.population[actor_id]
    if item_id == "blank_notebook":
        return quantities.get(item_id, 0) < 1
    if item_id == "bandage_roll":
        vitals = actor.get("vitals", {})
        protected = state.inventories.get("protected_items", {}).get(actor.get("occupation_id"), {}).get(item_id, 0)
        return quantities.get(item_id, 0) < max(protected, int(vitals.get("health", 0) < vitals.get("max_health", 0)))
    return item_id == "bread_loaf" and actor.get("needs", {}).get("food", 0) >= 25 and carried_nutrition(state, actor_id) < 25


def _reachable_person(state, first, second):
    if battle_locked(state, first) or battle_locked(state, second):
        return False
    return (are_phone_contacts(state, first, second) or
            (state.population[first]["current_location_id"] == state.population[second]["current_location_id"]
             and actor_layer(state, first) == actor_layer(state, second)))


def _retained(state, actor_id, item_id):
    record = state.inventories["actors"][actor_id]
    if actor_id == "player":
        return sum(value == item_id for value in record.get("equipped", {}).values())
    occupation = state.population[actor_id].get("occupation_id")
    return max(reserve_quantity(state, actor_id, item_id),
               state.inventories.get("protected_items", {}).get(occupation, {}).get(item_id, 0),
               sum(value == item_id for value in record.get("equipped", {}).values()))


def _surplus(state, actor_id, item_id):
    return max(0, state.inventories["actors"][actor_id]["quantities"].get(item_id, 0) - _retained(state, actor_id, item_id))


def _decision(state, request):
    helper = state.population[request["helper_id"]]
    relation = state.relationships.get(request["helper_id"], {}).get(request["requester_id"], DEFAULT_RELATIONSHIP)
    personality = helper.get("personality", {})
    price = state.inventories["catalog"][request["item_id"]]["base_price"]
    missing = max(0, _retained(state, request["helper_id"], request["item_id"]) + 1
                  - state.inventories["actors"][request["helper_id"]]["quantities"].get(request["item_id"], 0))
    if helper.get("wealth", 0) - missing * price < (30 if missing else 0):
        return False
    if max(helper.get("needs", {}).get(key, 0) for key in ("rest", "food", "safety")) >= 90:
        return False
    score = (0.4 * personality.get("altruism", 50) + 0.2 * personality.get("agreeableness", 50)
             + 0.3 * relation.get("trust", 50) + 0.1 * relation.get("closeness", 0)
             - 0.4 * relation.get("suspicion", 0) - 0.15 * helper.get("needs", {}).get("money", 0))
    return score >= 40


def _say(context, sender, receiver, message, policy):
    if are_phone_contacts(context.state, sender, receiver):
        append_structured_phone_message(context, sender, receiver, message, policy, source="rule")


def _close(context, request, status, message):
    request.update(status=status, updated_tick=tick(context.state), last_reason=message)
    context.emit("MATERIAL_HELP_UPDATED", message, actor_ids=[request["requester_id"], request["helper_id"]],
                 visibility="private", knowledge_tags=["assistance", "discovery"],
                 payload={"request_id": request["request_id"], "status": status, "item_id": request["item_id"]})


def waiting_for_material_help(state, actor_id, item_id):
    return any(r["status"] == "accepted" and r["requester_id"] == actor_id and r["item_id"] == item_id
               and tick(state) < r["expires_tick"] for r in state.cognition.get("material_assistance", {}).get("requests", {}).values())


def own_assistance_context(state, actor_id):
    return [{key: deepcopy(request[key]) for key in ("request_id", "requester_id", "helper_id", "item_id", "status", "expires_tick")}
            for request in state.cognition.get("material_assistance", {}).get("requests", {}).values()
            if request["status"] in OPEN and actor_id in {request["requester_id"], request["helper_id"]}][:4]


def make_assistance_handler(messaging_policy):
    # Only this validated fulfillment path relaxes purchase-to-gift cooldown;
    # personal/professional reserves and the recipient's acquisition timestamp remain.
    give = make_campus_inventory_handler(allow_recent_gifts=True)
    def handle(context, command):
        state, actor_id, params = context.state, command.actor_id, command.parameters
        def fail(code, message):
            return TransactionOutcome(False, False, code, message)
        if actor_id not in state.population or (command.source == "player" and actor_id != "player"):
            return fail("actor_not_authorized", "不能代替别人处理互助约定。")
        if command.issued_day != state.clock.day or command.issued_phase != state.clock.phase:
            return fail("command_clock_mismatch", "互助指令所属时段已过期。")
        if battle_locked(state, actor_id):
            return fail("battle_locked", "请先处理当前战斗。")
        ledger = _ledger(state)
        if command.action_id == "REQUEST_MATERIAL_HELP":
            target, item = params.get("helper_id"), params.get("item_id")
            if not isinstance(target, str) or target == actor_id or target not in state.population or not _reachable_person(state, actor_id, target):
                return fail("helper_unavailable", "需要当面联系，或先拥有对方的手机联系方式。")
            if item not in ITEMS or not needs_item(state, actor_id, item):
                return fail("no_material_need", "当前没有这项实际缺物需求。")
            pending = [r for r in ledger["requests"].values() if r["status"] in OPEN and tick(state) < r["expires_tick"]]
            if any(r["requester_id"] == actor_id and r["item_id"] == item for r in pending):
                return fail("request_exists", "这项物资已有待处理约定。")
            if sum(r["helper_id"] == target for r in pending) >= 2:
                return fail("helper_overcommitted", "对方已有两项待处理的互助安排。")
            ledger["sequence"] += 1
            request_id = f"material-help:{ledger['sequence']:06d}"
            request = {"request_id": request_id, "requester_id": actor_id, "helper_id": target, "item_id": item,
                       "meeting_location_id": "library_reading_hall",
                       "quantity": 1, "status": "pending", "created_tick": tick(state), "updated_tick": tick(state),
                       "expires_tick": tick(state) + 8, "attempts": 0, "last_reason": "等待对方明确答复。"}
            ledger["requests"][request_id] = request
            name = state.inventories["catalog"][item]["name"]
            message = f"我现在缺少一份{name}，能否在两天内帮忙带到图书馆阅览大厅？如果碰面也可直接交给我，不方便可以拒绝。"
            _say(context, actor_id, target, message, messaging_policy)
            _close(context, request, "pending", message)
            if target != "player":
                response = replace(command, actor_id=target, action_id="RESPOND_MATERIAL_HELP", source="rule",
                                   parameters={"request_id": request_id, "accepted": _decision(state, request)})
                handle(context, response)
            return TransactionOutcome(True, True, "success", STATUS_TEXT[request["status"]], commit=True, payload={"request": deepcopy(request)})
        request_id = params.get("request_id")
        request = ledger["requests"].get(request_id) if isinstance(request_id, str) else None
        if not request or actor_id not in {request["requester_id"], request["helper_id"]}:
            return fail("unknown_request", "没有找到属于你的互助约定。")
        if request["status"] not in OPEN:
            return fail("request_closed", "约定已结束，不能重复结算。")
        if tick(state) >= request["expires_tick"]:
            return fail("request_expired", "约定已到期，未交付物品。")
        if command.action_id == "CANCEL_MATERIAL_HELP":
            _close(context, request, "cancelled", "已撤回约定，没有转移物资。")
            other = request["helper_id"] if actor_id == request["requester_id"] else request["requester_id"]
            _say(context, actor_id, other, request["last_reason"], messaging_policy)
        elif command.action_id == "RESPOND_MATERIAL_HELP":
            if actor_id != request["helper_id"] or request["status"] != "pending" or type(params.get("accepted")) is not bool:
                return fail("invalid_response", "只有被请求者可以明确接受或拒绝待答复约定。")
            accepted = params["accepted"]
            message = "我答应帮忙带一份，实际交付前还不算完成。" if accepted else "抱歉，我目前没有余力，不能答应这件事。"
            _close(context, request, "accepted" if accepted else "declined", message)
            _say(context, actor_id, request["requester_id"], message, messaging_policy)
        elif command.action_id == "DELIVER_MATERIAL_HELP":
            if actor_id != request["helper_id"] or request["status"] != "accepted":
                return fail("not_accepted_helper", "只有已经答应的帮手可以履约。")
            if not needs_item(state, request["requester_id"], request["item_id"]):
                return fail("no_material_need", "对方已经通过其他方式补齐物资，请刷新约定。")
            before_helper = state.inventories["actors"][actor_id]["quantities"].get(request["item_id"], 0)
            before_requester = state.inventories["actors"][request["requester_id"]]["quantities"].get(request["item_id"], 0)
            outcome = give(context, replace(command, action_id="GIVE_ITEM", parameters={"item_id": request["item_id"],
                             "target_id": request["requester_id"], "quantity": 1}))
            if not outcome.success:
                return outcome
            request["receipt"] = {"command_id": command.command_id, "item_id": request["item_id"], "quantity": 1,
                                  "helper_before": before_helper, "helper_after": before_helper - 1,
                                  "requester_before": before_requester, "requester_after": before_requester + 1}
            _close(context, request, "fulfilled", "约定物资已当面交付，库存已经真实转移。")
            adjust_relationship(state, request["requester_id"], actor_id, {"trust": 3, "closeness": 2})
            _say(context, actor_id, request["requester_id"], "约好的物资已经交给你了。", messaging_policy)
        elif command.action_id == "WAIT_MATERIAL_HELP":
            if (request["status"] != "accepted" or state.population[actor_id]["current_location_id"] != request["meeting_location_id"]
                    or actor_layer(state, actor_id) != "surface"):
                return fail("meeting_unavailable", "需要先到表世界的约定地点。")
            context.emit("MATERIAL_HELP_MEETING", "来到约定地点，等待物资互助碰面。", actor_ids=[actor_id],
                         scene_id=request["meeting_location_id"], visibility="private", knowledge_tags=["assistance", "discovery"],
                         payload={"request_id": request_id})
            return TransactionOutcome(True, True, "success", "已到约定地点，尚未交付物资。", commit=True)
        else:
            return fail("unknown_action", "不支持的互助行动。")
        return TransactionOutcome(True, True, "success", request["last_reason"], commit=True, payload={"request": deepcopy(request)})
    return handle


def advance_assistance_upkeep(context):
    state, changed = context.state, 0
    requests = state.cognition.get("material_assistance", {}).get("requests", {})
    for request in requests.values():
        if request["status"] not in OPEN:
            continue
        if not needs_item(state, request["requester_id"], request["item_id"]):
            _close(context, request, "no_longer_needed", "需求已由其他途径解决，不再重复索取物资。")
            changed += 1
        elif tick(state) >= request["expires_tick"]:
            if request["status"] == "accepted":
                adjust_relationship(state, request["requester_id"], request["helper_id"], {"trust": -2})
            _close(context, request, "expired", "约定到期，尚未交付；请求者可以重新安排。")
            changed += 1
    closed = [key for key, request in requests.items() if request["status"] not in OPEN]
    for key in closed[:-100]:
        del requests[key]
    return {"material_help_closed": changed}


def project_assistance_events(state, events):
    """A real matching backpack gift also fulfills a promise; no special UI ritual."""
    requests = state.cognition.get("material_assistance", {}).get("requests", {})
    for event in events:
        if event.event_type != "CAMPUS_ITEM_ACTION_COMPLETED" or event.payload.get("action_id") != "GIVE_ITEM":
            continue
        gift = event.payload.get("gift_receipt")
        if not gift or not event.actor_ids:
            continue
        for request in requests.values():
            if (request["status"] != "accepted" or tick(state) >= request["expires_tick"]
                    or request["helper_id"] != event.actor_ids[0] or request["requester_id"] != event.payload.get("target_id")
                    or request["item_id"] != event.payload.get("item_id") or event.payload.get("quantity", 0) < request["quantity"]):
                continue
            request.update(status="fulfilled", updated_tick=tick(state), last_reason="已通过背包实际转交履行约定。",
                receipt={"command_id": event.command_id, "source_event_id": event.event_id, "item_id": request["item_id"],
                         "quantity": event.payload["quantity"], "helper_before": gift["source_before"], "helper_after": gift["source_after"],
                         "requester_before": gift["target_before"], "requester_after": gift["target_after"]})
            adjust_relationship(state, request["requester_id"], request["helper_id"], {"trust": 3, "closeness": 2})


def record_assistance_outcome(context, plan, outcome):
    request = context.state.cognition.get("material_assistance", {}).get("requests", {}).get(plan.get("assistance_id"))
    if request is not None:
        request["attempts"] += 1
        request["last_reason"] = outcome.message
        request["updated_tick"] = tick(context.state)


EXPECTED_ASSISTANCE_FAILURES = {"no_material_need", "item_missing", "item_protected", "inventory_full", "location_mismatch",
                                "battle_locked", "request_expired", "request_closed", "unknown_request", "not_accepted_helper", "meeting_unavailable"}


def assistance_candidates(context, actor_id, schedule_plan, graph, occupancy, policy, base_score):
    from simulation.systems.campus_decisions import _destination_is_open_and_accessible, _has_capacity
    state, result = context.state, []
    actor = state.population[actor_id]
    if (actor_layer(state, actor_id) != "surface" or battle_locked(state, actor_id) or active_departure(state, actor_id)
            or actor.get("active_forum_task_id") or schedule_plan.get("priority", 0) >= policy.protected_schedule_priority
            or max(actor.get("needs", {}).get(key, 0) for key in ("rest", "food", "safety")) >= policy.emergency_need_threshold):
        return []
    requests = state.cognition.get("material_assistance", {}).get("requests", {})
    for request in requests.values():
        if actor_id not in {request["helper_id"], request["requester_id"]} or request["status"] != "accepted" or tick(state) >= request["expires_tick"]:
            continue
        if not needs_item(state, request["requester_id"], request["item_id"]):
            continue
        item = request["item_id"]
        options = []
        if actor_id == request["requester_id"]:
            options.append((request["meeting_location_id"], "WAIT_MATERIAL_HELP", {"request_id": request["request_id"]}))
        elif _surplus(state, actor_id, item) >= 1:
            target = request["requester_id"]
            # A contact is not a live GPS tracker. Go to the agreed venue unless
            # the helper can already see the requester at their current place.
            met_here = actor["current_location_id"] == state.population[target]["current_location_id"] and actor_layer(state, target) == "surface"
            destination = actor["current_location_id"] if met_here else request["meeting_location_id"]
            options.append((destination, "DELIVER_MATERIAL_HELP", {"request_id": request["request_id"]}))
        else:
            catalog = _catalog(state)
            inventory = _inventory(state.inventories["actors"][actor_id])
            quantity = _retained(state, actor_id, item) + 1 - state.inventories["actors"][actor_id]["quantities"].get(item, 0)
            price = state.inventories["catalog"][item]["base_price"]
            if actor["wealth"] - quantity * price >= 30 and inventory.can_add(catalog[item], quantity, catalog):
                for shop in state.inventories["shops"].values():
                    if shop["quantities"].get(item, 0) >= quantity:
                        options.append((shop["location_id"], "BUY_ITEM", {"shop_id": shop["id"], "item_id": item, "quantity": quantity}))
        legal = []
        for destination, action, params in options:
            if not _destination_is_open_and_accessible(graph, actor, destination, state.clock.phase) or not _has_capacity(graph, occupancy, destination):
                continue
            route = graph.shortest_route(actor["current_location_id"], destination, phase=state.clock.phase, access_tags=actor.get("access_tags", ()))
            if route is not None:
                legal.append((route.total_minutes, destination, action, params))
        if not legal:
            request["last_reason"] = "仍在准备：物资、余钱、地点或对方当前状态不满足条件。"
            continue
        minutes, destination, action, params = min(legal, key=lambda row: (row[0], row[1]))
        score = base_score + 12 + actor.get("personality", {}).get("conscientiousness", 50) * .05
        result.append({"candidate_id": "assist:" + request["request_id"], "activity_id": action, "action_class": "free",
            "location_id": destination, "parameters": params, "assistance_id": request["request_id"],
            "priority": 80, "decision_source": "rule", "decision_reason": "accepted_material_promise",
            "reason_codes": ["commitment", "actual_delivery", "legal_next_step"], "score": score, "score_jitter": 0.0,
            "score_contributions": {"commitment": score}, "candidate_count": 1, "route_minutes": minutes,
            "scheduled_activity_id": schedule_plan.get("activity_id", ""), "scheduled_location_id": schedule_plan.get("location_id", ""),
            "day": state.clock.day, "phase": state.clock.phase})
    return result


def advance_assistance_requests(context, messaging_policy, pair_cooldown=1):
    state, created, used = context.state, 0, set()
    handler = make_assistance_handler(messaging_policy)
    requests = state.cognition.get("material_assistance", {}).get("requests", {})
    for actor_id, actor in sorted(state.population.items()):
        if created >= 4:
            break
        if actor_id == "player" or actor_id in used or battle_locked(state, actor_id):
            continue
        # Help is not a way for affluent NPCs to accumulate free stock.
        items = [item for item in ITEMS if needs_item(state, actor_id, item)
                 and actor["wealth"] < state.inventories["catalog"][item]["base_price"]]
        if not items:
            continue
        item = items[0]
        if any(r["requester_id"] == actor_id and r["item_id"] == item and r["status"] in OPEN for r in requests.values()):
            continue
        candidates = []
        for other in state.population:
            if other == actor_id or other in used or not _reachable_person(state, actor_id, other):
                continue
            pair = "|".join(sorted((actor_id, other)))
            last = state.cognition["interactions"]["pair_last_phase"].get(pair, -100)
            if tick(state) - last <= pair_cooldown:
                continue
            if any(r["requester_id"] == actor_id and r["helper_id"] == other and tick(state) - r["created_tick"] < 8 for r in requests.values()):
                continue
            relation = state.relationships.get(actor_id, {}).get(other, DEFAULT_RELATIONSHIP)
            candidates.append((-(relation.get("trust", 50) + relation.get("closeness", 0)), other))
        if not candidates:
            continue
        target = min(candidates)[1]
        command = SimulationCommand(f"{context.command.command_id}:help:{actor_id}", actor_id, "REQUEST_MATERIAL_HELP", state.revision,
                    parameters={"helper_id": target, "item_id": item}, issued_day=state.clock.day, issued_phase=state.clock.phase, source="rule")
        outcome = handler(context, command)
        if outcome.success:
            requests = state.cognition["material_assistance"]["requests"]
            created += 1
            used.update((actor_id, target))
            state.cognition["interactions"]["pair_last_phase"]["|".join(sorted((actor_id, target)))] = tick(state)
    return {"material_help_requested": created}


def advance_assistance_deliveries(context, messaging_policy):
    """Free handovers after movement/duties; no off-screen tracking or player control."""
    state, completed, used = context.state, 0, set()
    handler = make_assistance_handler(messaging_policy)
    for request in state.cognition.get("material_assistance", {}).get("requests", {}).values():
        helper, recipient = request["helper_id"], request["requester_id"]
        if (helper == "player" or helper in used or recipient in used or request["status"] != "accepted"
                or tick(state) >= request["expires_tick"] or not needs_item(state, recipient, request["item_id"])
                or battle_locked(state, helper) or battle_locked(state, recipient)
                or state.population[helper]["current_location_id"] != state.population[recipient]["current_location_id"]
                or actor_layer(state, helper) != actor_layer(state, recipient) or _surplus(state, helper, request["item_id"]) < 1):
            continue
        command = SimulationCommand(f"{context.command.command_id}:deliver:{request['request_id']}", helper,
            "DELIVER_MATERIAL_HELP", state.revision, parameters={"request_id": request["request_id"]},
            issued_day=state.clock.day, issued_phase=state.clock.phase, source="rule")
        outcome = handler(context, command)
        record_assistance_outcome(context, {"assistance_id": request["request_id"]}, outcome)
        if not outcome.success:
            if outcome.code not in EXPECTED_ASSISTANCE_FAILURES:
                raise RuntimeError("unexpected automatic material delivery refusal: " + outcome.code)
            continue
        completed += 1
        used.update((helper, recipient))
    return {"material_help_delivered": completed}


def assistance_view(state, actor_id="player"):
    if actor_id not in state.population or not state.inventories:
        return {"requests": [], "needs": [], "contacts": []}
    requests = []
    for request in state.cognition.get("material_assistance", {}).get("requests", {}).values():
        if actor_id not in {request["requester_id"], request["helper_id"]}:
            continue
        item = deepcopy(request)
        item.update(item_name=state.inventories["catalog"][request["item_id"]]["name"], status_text=STATUS_TEXT[request["status"]],
                    meeting_name=state.places[request["meeting_location_id"]]["name"],
                    requester_name=state.population[request["requester_id"]]["display_name"], helper_name=state.population[request["helper_id"]]["display_name"])
        active = request["status"] in OPEN and tick(state) < request["expires_tick"] and not battle_locked(state, actor_id)
        item["can_respond"] = active and actor_id == request["helper_id"] and request["status"] == "pending"
        item["can_cancel"] = active
        item["can_deliver"] = (active and actor_id == request["helper_id"] and request["status"] == "accepted"
            and _surplus(state, actor_id, request["item_id"]) >= 1 and not battle_locked(state, request["requester_id"])
            and state.population[actor_id]["current_location_id"] == state.population[request["requester_id"]]["current_location_id"]
            and actor_layer(state, actor_id) == actor_layer(state, request["requester_id"])
            and needs_item(state, request["requester_id"], request["item_id"])
            and _inventory(state.inventories["actors"][request["requester_id"]]).can_add(_catalog(state)[request["item_id"]], 1, _catalog(state)))
        requests.append(item)
    return {"requests": requests[-30:],
            "needs": [{"item_id": item, "name": state.inventories["catalog"][item]["name"]} for item in ITEMS if needs_item(state, actor_id, item)],
            "contacts": [{"actor_id": other, "name": actor["display_name"], "channel": "手机" if are_phone_contacts(state, actor_id, other) else "当面"}
                         for other, actor in state.population.items() if other != actor_id and _reachable_person(state, actor_id, other)]}


def assistance_invariant(state):
    ledger = state.cognition.get("material_assistance")
    if ledger is None:
        return []
    errors = []
    try:
        if ledger["schema_version"] != 1 or type(ledger["sequence"]) is not int or ledger["sequence"] < 0 or not isinstance(ledger["requests"], dict):
            return ["invalid material assistance ledger"]
        active = set()
        for key, request in ledger["requests"].items():
            if (key != request["request_id"] or request["status"] not in STATUSES or request["item_id"] not in ITEMS
                    or request["meeting_location_id"] not in state.places
                    or request["requester_id"] not in state.population or request["helper_id"] not in state.population
                    or request["helper_id"] == request["requester_id"] or type(request["quantity"]) is not int or request["quantity"] != 1):
                errors.append("invalid material assistance request")
            if any(type(request[field]) is not int or request[field] < 0 for field in ("created_tick", "updated_tick", "expires_tick", "attempts")):
                errors.append("invalid assistance counters")
            elif not request["created_tick"] <= request["updated_tick"] < request["expires_tick"] and request["status"] in OPEN:
                errors.append("invalid assistance clock")
            if not isinstance(request["last_reason"], str):
                errors.append("invalid assistance reason")
            if request["status"] == "fulfilled":
                receipt = request["receipt"]
                if (not isinstance(receipt["command_id"], str) or not receipt["command_id"] or receipt["item_id"] != request["item_id"]
                        or type(receipt["quantity"]) is not int or receipt["quantity"] < request["quantity"]
                        or any(type(receipt[field]) is not int or receipt[field] < 0 for field in ("helper_before", "helper_after", "requester_before", "requester_after"))
                        or receipt["helper_before"] - receipt["helper_after"] != receipt["quantity"]
                        or receipt["requester_after"] - receipt["requester_before"] != receipt["quantity"]):
                    errors.append("invalid material delivery receipt")
            identity = (request["requester_id"], request["item_id"])
            if request["status"] in OPEN and tick(state) < request["expires_tick"]:
                if identity in active:
                    errors.append("duplicate unresolved material demand")
                active.add(identity)
    except (KeyError, TypeError, ValueError, AttributeError):
        errors.append("invalid nested assistance structure")
    return errors
