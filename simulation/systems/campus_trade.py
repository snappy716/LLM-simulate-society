"""Campus private quotes and demand-driven trade; no legacy World or LLM calls.

Offers are intentions, not escrow. Acceptance revalidates both parties and
settles inside the caller's WorldKernel transaction. Histories are bounded;
event/chronicle storage remains the durable audit trail.
"""
from copy import deepcopy
from hashlib import sha256

from simulation.actions.commands import SimulationCommand
from simulation.systems.campus_inventory import (
    _busy, _catalog, _failure, _inventory, _layer, _movable,
)
from simulation.systems.campus_social import DEFAULT_RELATIONSHIP, adjust_relationship
from simulation.systems.transactions import TransactionOutcome

TRADE_ACTIONS = ("OFFER_TRADE", "ACCEPT_TRADE", "REJECT_TRADE", "CANCEL_TRADE", "REQUEST_TRADE_RESPONSE")
PHASES = ("morning", "afternoon", "evening", "late_night")


def tick(state):
    return (state.clock.day - 1) * 4 + PHASES.index(state.clock.phase)


def _rank(state, *parts):
    return int(sha256((':'.join(map(str, (state.master_seed, *parts)))).encode()).hexdigest()[:8], 16)


def install_campus_trade(state):
    if "trade" in state.inventories:
        raise ValueError("campus trade already installed")
    state.inventories["trade"] = {
        "schema_version": 1, "sequence": 0, "offers": {}, "memories": {},
        "next_private_tick": {}, "acquired": {}, "pair_tick": {},
        "phase_counts": {}, "last_autonomy_tick": -1,
        "policy": {"necessary_items": {"bread_loaf": 1, "blank_notebook": 1},
                   "trading_occupations": ["campus_service_staff"],
                   "ordinary_interval_days": [2, 4], "item_cooldown_phases": 8,
                   "food_reorder_nutrition": 25, "food_buffer_nutrition": [100, 150],
                   "professional_item_cooldown_phases": 1,
                   "professional_trades_per_phase": 4, "offer_lifetime_phases": 2},
    }


def professional(state, actor_id):
    return state.population[actor_id].get("occupation_id") in state.inventories["trade"]["policy"]["trading_occupations"]


def reserve_quantity(state, actor_id, item_id):
    rules = state.inventories.get("rules", {})
    if rules.get(item_id, {}).get("food_reduction"):
        quantities = state.inventories["actors"][actor_id]["quantities"]
        other_food = sum(quantity * rules.get(key, {}).get("food_reduction", 0)
                         for key, quantity in quantities.items() if key != item_id)
        return 1 if other_food < 25 else 0
    return state.inventories.get("trade", {}).get("policy", {}).get("necessary_items", {}).get(item_id, 0)


def acquisition_locked(state, actor_id, item_id):
    if actor_id == "player" or "trade" not in state.inventories:
        return False
    trade = state.inventories["trade"]
    acquired = trade["acquired"].get(actor_id, {}).get(item_id)
    cooldown = trade["policy"]["professional_item_cooldown_phases" if professional(state, actor_id) else "item_cooldown_phases"]
    return acquired is not None and tick(state) - acquired < cooldown


def remember(state, actor_id, entry):
    memory = state.inventories["trade"]["memories"].setdefault(actor_id, [])
    memory.append({"tick": tick(state), **entry})
    del memory[:-24]


def acquired(state, actor_id, item_id):
    if "trade" in state.inventories:
        state.inventories["trade"]["acquired"].setdefault(actor_id, {})[item_id] = tick(state)


def carried_nutrition(state, actor_id):
    rules = state.inventories["rules"]
    return sum(quantity * rules.get(key, {}).get("food_reduction", 0)
               for key, quantity in state.inventories["actors"][actor_id]["quantities"].items())


def procurement_demand(state, actor_id, item_id):
    """Restock a low pantry in batches; nearby private trades cover small gaps.

    Target and reorder threshold differ deliberately. Daily top-ups would keep
    refreshing the existing same-item resale lock. No generated surplus or
    guaranteed counterparty: purchased goods still cost cash and carry weight.
    """
    nutrition = state.inventories["rules"][item_id].get("food_reduction", 0)
    if not nutrition:
        return demand(state, actor_id, item_id)
    actor = state.population[actor_id]
    policy = state.inventories["trade"]["policy"]
    carried = carried_nutrition(state, actor_id)
    if actor["needs"]["food"] < 25 or carried > policy.get("food_reorder_nutrition", 25):
        return 0
    low, high = policy.get("food_buffer_nutrition", [100, 150])
    diligence = actor["personality"].get("conscientiousness", 50)
    target = low + (high - low) * diligence // 100
    # Financial stress reduces the intended reserve, never the hard food floor.
    if actor["wealth"] < 50:
        target = min(target, 50)
    elif actor["needs"]["money"] >= 75:
        # Money anxiety is not insolvency: modestly reduce the buffer instead
        # of making well-funded residents return to perpetual daily top-ups.
        target = max(75, target - 25)
    return max(0, (target - carried + nutrition - 1) // nutrition)


def demand(state, actor_id, item_id):
    """A real shortage, never an instruction to buy arbitrary generated goods."""
    actor = state.population[actor_id]
    stock = state.inventories["actors"][actor_id]["quantities"].get(item_id, 0)
    rules = state.inventories["rules"]
    nutrition = rules[item_id].get("food_reduction", 0)
    if nutrition:
        carried = carried_nutrition(state, actor_id)
        return max(0, (50 - carried + nutrition - 1) // nutrition) if actor["needs"]["food"] >= 25 else 0
    protected = state.inventories["protected_items"].get(actor.get("occupation_id"), {}).get(item_id, 0)
    if protected:
        return max(0, protected + (1 if item_id == "bandage_roll" else 0) - stock)
    if item_id == "bandage_roll" and actor.get("vitals", {}).get("health", 1) < actor.get("vitals", {}).get("max_health", 1):
        return max(0, 1 - stock)
    if item_id == "blank_notebook":
        return max(0, 1 - stock)
    return 0


def _ready(state, actor_id):
    if actor_id == "player":
        return True
    trade = state.inventories["trade"]
    if professional(state, actor_id):
        count = trade["phase_counts"].get(actor_id, {})
        return count.get("tick") != tick(state) or count.get("count", 0) < trade["policy"]["professional_trades_per_phase"]
    return tick(state) >= trade["next_private_tick"].get(actor_id, 0)


def _pair_key(a, b):
    return ':'.join(sorted((a, b)))


def _same_place(state, a, b):
    return (state.population[a]["current_location_id"] == state.population[b]["current_location_id"]
            and _layer(state, a) == _layer(state, b))


def valuation(state, actor_id, counterpart, item_id, *, buying):
    actor = state.population[actor_id]
    relation = state.relationships.get(actor_id, {}).get(counterpart, DEFAULT_RELATIONSHIP)
    personality = actor["personality"]
    base = state.inventories["catalog"][item_id]["base_price"]
    previous = [m["unit_price"] for m in state.inventories["trade"]["memories"].get(actor_id, [])
                if m.get("item_id") == item_id and m.get("status") == "settled"]
    anchor = base if not previous else (base * 2 + max(base // 2, min(base * 2, previous[-1]))) / 3
    pressure = max(actor["needs"]["money"] / 100, 1 - actor["wealth"] / 100)
    distrust = relation["suspicion"] / 160 + relation["conflict"] / 250
    goodwill = (relation["trust"] - 50) / 400 + relation["closeness"] / 500
    kindness = (personality["agreeableness"] - 50) / 600
    if buying:
        urgency = min(0.4, demand(state, actor_id, item_id) * 0.15)
        factor = 1.05 + urgency + goodwill + kindness - distrust - pressure * 0.3
    else:
        factor = 0.9 + distrust - goodwill - kindness - pressure * 0.25
    return max(1, round(anchor * max(0.35, min(2.0, factor))))


def _validate_settlement(state, offer):
    buyer, seller, item_id, quantity = (offer[k] for k in ("buyer_id", "seller_id", "item_id", "quantity"))
    if not _same_place(state, buyer, seller):
        return _failure("location_mismatch", "成交时双方必须在同一地点、同一世界层。")
    if _busy(state, buyer) or _busy(state, seller):
        return _failure("battle_locked", "战斗中不能结算私人交易。")
    if not _ready(state, buyer) or not _ready(state, seller):
        return _failure("trade_cooldown", "对方近期已完成私人交易，暂不重复交易。")
    if state.inventories["trade"]["pair_tick"].get(_pair_key(buyer, seller)) == tick(state):
        return _failure("pair_cooldown", "同一对角色本时段已成交。")
    if acquisition_locked(state, seller, item_id):
        return _failure("item_cooldown", "刚获得的物品暂不转手。")
    if not _movable(state, seller, item_id, quantity):
        return _failure("item_protected", "卖方库存不足，或须保留生活必需品、职业工具与装备。")
    if state.population[buyer]["wealth"] < offer["unit_price"] * quantity:
        return _failure("insufficient_funds", "买方余额已不足。")
    catalog = _catalog(state)
    if not _inventory(state.inventories["actors"][buyer]).can_add(catalog[item_id], quantity, catalog):
        return _failure("inventory_full", "买方背包负重不足。")
    return None


def npc_response(state, offer):
    actor_id = offer["recipient_id"]
    if actor_id == "player":
        return False, "等待玩家选择"
    buying = actor_id == offer["buyer_id"]
    counterpart = offer["proposer_id"]
    if state.relationships.get(actor_id, {}).get(counterpart, {}).get("suspicion", 0) >= 85:
        return False, "对报价方过于怀疑"
    item_id = offer["item_id"]
    if buying and demand(state, actor_id, item_id) < offer["quantity"]:
        # Trading professions may acquire surplus for a real resale margin,
        # but still need money, capacity, cooldown and retained essentials.
        base = state.inventories["catalog"][item_id]["base_price"]
        stock = state.inventories["actors"][actor_id]["quantities"].get(item_id, 0)
        if not (professional(state, actor_id) and stock + offer["quantity"] <= 6 and offer["unit_price"] <= base * 0.65):
            return False, "没有这项需求，也没有合理转售空间"
    limit = valuation(state, actor_id, counterpart, item_id, buying=buying)
    okay = offer["unit_price"] <= limit if buying else offer["unit_price"] >= limit
    return okay, "价格与需求匹配" if okay else "报价不符合当前估值与经济压力"


def _close(context, offer, status, reason):
    offer.update(status=status, closed_tick=tick(context.state), reason=reason)
    for actor_id in (offer["buyer_id"], offer["seller_id"]):
        remember(context.state, actor_id, {k: offer[k] for k in ("offer_id", "item_id", "unit_price", "quantity", "status", "reason")})
    state = context.state
    buyer_name = state.population[offer["buyer_id"]]["display_name"]
    seller_name = state.population[offer["seller_id"]]["display_name"]
    item_name = state.inventories["catalog"][offer["item_id"]]["name"]
    message = f"{buyer_name} 向 {seller_name} 购买{item_name}的报价：{reason}。"
    context.emit("CAMPUS_TRADE_" + status.upper(), message,
                 actor_ids=[offer["buyer_id"], offer["seller_id"]],
                 scene_id=context.state.population[offer["proposer_id"]]["current_location_id"],
                 payload=deepcopy(offer), visibility="private", knowledge_tags=["trade"])
    return TransactionOutcome(True, True, status, message, commit=True, payload={"offer": deepcopy(offer)})


def make_campus_trade_handler():
    def handle(context, command):
        state, actor_id, params = context.state, command.actor_id, command.parameters
        trade = state.inventories.get("trade")
        if not trade or actor_id not in state.population:
            return _failure("unknown_actor", "找不到校园交易参与者。")
        if command.source == "player" and actor_id != "player":
            return _failure("actor_not_authorized", "不能替 NPC 同意报价。")
        if (command.issued_day, command.issued_phase) != (state.clock.day, state.clock.phase):
            return _failure("command_clock_mismatch", "报价指令已过期。")
        if command.action_id == "OFFER_TRADE":
            other, item_id = params.get("target_id"), params.get("item_id")
            quantity, price = params.get("quantity", 1), params.get("unit_price")
            side = params.get("side", "buy")
            if not isinstance(other, str) or other not in state.population or other == actor_id:
                return _failure("invalid_target", "请选择另一名在场角色。")
            if not isinstance(item_id, str) or item_id not in state.inventories["catalog"] or not state.inventories["catalog"][item_id]["tradeable"]:
                return _failure("unknown_item", "该物品不能交易。")
            if side not in ("buy", "sell") or type(quantity) is not int or not 1 <= quantity <= 99 or type(price) is not int or not 1 <= price <= 100000:
                return _failure("invalid_quote", "须指定买/卖、正整数数量与单价。")
            pending = [o for o in trade["offers"].values() if o["status"] == "pending" and o["expires_tick"] > tick(state)]
            if any(_pair_key(o["buyer_id"], o["seller_id"]) == _pair_key(actor_id, other) for o in pending):
                return _failure("pending_offer", "双方已有待处理报价，请先处理或撤销。")
            if sum(actor_id in (o["buyer_id"], o["seller_id"]) for o in pending) >= 8 or sum(other in (o["buyer_id"], o["seller_id"]) for o in pending) >= 8:
                return _failure("pending_offer", "待处理报价过多，请先处理现有报价。")
            buyer, seller = (actor_id, other) if side == "buy" else (other, actor_id)
            offer = {"offer_id": f"quote:{trade['sequence'] + 1}", "proposer_id": actor_id,
                     "recipient_id": other, "buyer_id": buyer, "seller_id": seller,
                     "item_id": item_id, "quantity": quantity, "unit_price": price,
                     "created_tick": tick(state), "expires_tick": tick(state) + trade["policy"]["offer_lifetime_phases"],
                     "status": "pending", "reason": "等待回应"}
            failure = _validate_settlement(state, offer)
            if failure:
                return failure
            trade["sequence"] += 1
            trade["offers"][offer["offer_id"]] = offer
            # Quote history is distinct from成交; a proposed price cannot poison
            # the recent-settled-price anchor used by the evaluation policy.
            for participant in (buyer, seller):
                remember(state, participant, {k: offer[k] for k in ("offer_id", "item_id", "unit_price", "quantity", "status", "reason")})
            context.emit("CAMPUS_TRADE_OFFERED", f"{state.population[actor_id]['display_name']} 提出了一份私人报价，尚未成交。",
                         actor_ids=[buyer, seller], scene_id=state.population[actor_id]["current_location_id"],
                         payload=deepcopy(offer), visibility="private", knowledge_tags=["trade"])
            return TransactionOutcome(True, True, "offered", "报价已提出，尚未扣款或交货。", commit=True, payload={"offer": deepcopy(offer)})
        offer_id = params.get("offer_id")
        offer = trade["offers"].get(offer_id) if isinstance(offer_id, str) else None
        if not offer:
            return _failure("unknown_offer", "报价不存在。")
        expected_actor = offer["proposer_id"] if command.action_id in ("CANCEL_TRADE", "REQUEST_TRADE_RESPONSE") else offer["recipient_id"]
        if actor_id != expected_actor:
            return _failure("actor_not_authorized", "只能处理发给自己的报价，或撤销自己发出的报价。")
        if offer["status"] != "pending":
            return _failure("offer_closed", "报价已经处理，不能重复结算。")
        if tick(state) >= offer["expires_tick"]:
            return _close(context, offer, "expired", "报价已过期，未结算")
        if command.action_id == "REQUEST_TRADE_RESPONSE":
            if offer["recipient_id"] == "player":
                return _failure("actor_not_authorized", "玩家必须亲自选择是否接受。")
            return handle(context, rule_command(context, offer["recipient_id"], "ACCEPT_TRADE", offer_id=offer_id))
        if command.action_id in ("REJECT_TRADE", "CANCEL_TRADE"):
            return _close(context, offer, "rejected" if command.action_id == "REJECT_TRADE" else "cancelled", "报价被拒绝" if command.action_id == "REJECT_TRADE" else "发起方撤销报价")
        if command.action_id != "ACCEPT_TRADE":
            return _failure("unknown_action", "不支持的交易指令。")
        failure = _validate_settlement(state, offer)
        if failure:
            return failure
        if actor_id != "player":
            accepted, reason = npc_response(state, offer)
            if not accepted:
                return _close(context, offer, "rejected", reason)
        buyer, seller, item_id = (offer[k] for k in ("buyer_id", "seller_id", "item_id"))
        catalog = _catalog(state)
        _inventory(state.inventories["actors"][seller]).remove(item_id, offer["quantity"])
        _inventory(state.inventories["actors"][buyer]).add(catalog[item_id], offer["quantity"], catalog)
        total = offer["quantity"] * offer["unit_price"]
        state.population[buyer]["wealth"] -= total
        state.population[seller]["wealth"] += total
        acquired(state, buyer, item_id)
        trade["pair_tick"][_pair_key(buyer, seller)] = tick(state)
        for participant in (buyer, seller):
            old = trade["phase_counts"].get(participant, {})
            count = old.get("count", 0) if old.get("tick") == tick(state) else 0
            trade["phase_counts"][participant] = {"tick": tick(state), "count": count + 1}
            days = 2 + _rank(state, participant, offer["offer_id"]) % 3
            trade["next_private_tick"][participant] = tick(state) + days * 4
        adjust_relationship(state, buyer, seller, {"familiarity": 2, "trust": 1})
        adjust_relationship(state, seller, buyer, {"familiarity": 2, "trust": 1})
        return _close(context, offer, "settled", f"实际交货 {offer['quantity']} 件，总价 {total} 元")
    return handle


def rule_command(context, actor_id, action_id, **parameters):
    return SimulationCommand(f"{context.command.command_id}:trade:{actor_id}:{action_id}:{context.state.inventories['trade']['sequence']}",
                             actor_id, action_id, context.state.revision, parameters=parameters,
                             issued_day=context.state.clock.day, issued_phase=context.state.clock.phase, source="rule")


def advance_campus_trade(context):
    """After actual activity/movement: respond and match co-located shortages."""
    state, handler = context.state, make_campus_trade_handler()
    trade = state.inventories["trade"]
    if trade["last_autonomy_tick"] == tick(state):
        return {"private_trade_settled": 0}
    trade["last_autonomy_tick"] = tick(state)
    settled = 0
    for offer in list(trade["offers"].values()):
        if offer["status"] != "pending":
            continue
        if tick(state) >= offer["expires_tick"]:
            _close(context, offer, "expired", "报价到期，未结算")
        elif offer["recipient_id"] != "player":
            result = handler(context, rule_command(context, offer["recipient_id"], "ACCEPT_TRADE", offer_id=offer["offer_id"]))
            if not result.success:
                _close(context, offer, "rejected", result.message)
            settled += result.code == "settled"
    groups = {}
    for actor_id, actor in state.population.items():
        if actor_id != "player" and not _busy(state, actor_id):
            groups.setdefault((_layer(state, actor_id), actor["current_location_id"]), []).append(actor_id)
    for members in groups.values():
        ordered = sorted(members, key=lambda a: _rank(state, a, tick(state)))
        for buyer in ordered:
            if not _ready(state, buyer) or (buyer not in trade["next_private_tick"] and tick(state) < _rank(state, buyer, "trade_start") % 12):
                continue
            for item_id in state.inventories["catalog"]:
                if not demand(state, buyer, item_id):
                    continue
                for seller in ordered:
                    if seller == buyer or not _ready(state, seller) or not _movable(state, seller, item_id, 1) or acquisition_locked(state, seller, item_id):
                        continue
                    price = valuation(state, seller, buyer, item_id, buying=False)
                    if price > valuation(state, buyer, seller, item_id, buying=True):
                        continue
                    result = handler(context, rule_command(context, buyer, "OFFER_TRADE", target_id=seller, item_id=item_id, quantity=1, unit_price=price, side="buy"))
                    if not result.success:
                        continue
                    offer = result.payload["offer"]
                    result = handler(context, rule_command(context, seller, "ACCEPT_TRADE", offer_id=offer["offer_id"]))
                    settled += result.code == "settled"
                    break
                if not _ready(state, buyer):
                    break
    # Keep all pending offers and the latest 200 closed records. Full events
    # remain in the existing chronicles/event sink rather than growing snapshots.
    closed = [key for key, offer in trade["offers"].items() if offer["status"] != "pending"]
    for key in closed[:-200]:
        del trade["offers"][key]
    trade["pair_tick"] = {key: value for key, value in trade["pair_tick"].items() if value == tick(state)}
    return {"private_trade_settled": settled}


def make_procurement_selector(base_selector, graph, protected_priority):
    def select(context, actor_id, schedule_plan, occupancy):
        state, actor = context.state, context.state.population[actor_id]
        if (int(schedule_plan.get("priority", 0)) >= protected_priority or actor.get("active_forum_task_id")
                or _layer(state, actor_id) != "surface" or _busy(state, actor_id)):
            return base_selector(context, actor_id, schedule_plan, occupancy)
        candidates = []
        catalog = _catalog(state)
        for shop in state.inventories["shops"].values():
            if state.clock.phase not in state.places[shop["location_id"]].get("open_phases", []):
                continue
            for item_id in shop["accepted_item_ids"]:
                needed = procurement_demand(state, actor_id, item_id)
                price = state.inventories["catalog"][item_id]["base_price"]
                quantity = min(needed, shop["quantities"].get(item_id, 0), actor["wealth"] // price)
                if quantity <= 0:
                    continue
                inventory = _inventory(state.inventories["actors"][actor_id])
                while quantity > 0 and not inventory.can_add(catalog[item_id], quantity, catalog):
                    quantity -= 1
                if quantity <= 0:
                    continue
                route = graph.shortest_route(actor["current_location_id"], shop["location_id"], phase=state.clock.phase, access_tags=actor.get("access_tags", ()))
                if route is not None:
                    candidates.append((price * quantity + len(route.steps), shop["id"], item_id, quantity, route))
        if not candidates:
            return base_selector(context, actor_id, schedule_plan, occupancy)
        _, shop_id, item_id, quantity, route = min(candidates, key=lambda c: c[:3])
        return {"activity_id": "BUY_ITEM", "action_class": "free", "location_id": route.destination_id,
                "parameters": {"shop_id": shop_id, "item_id": item_id, "quantity": quantity},
                "decision_source": "rule", "decision_reason": "necessary_item_shortage",
                "reason_codes": ["need", "affordable", "shop_open", "reachable"], "candidate_count": len(candidates),
                "scheduled_activity_id": schedule_plan.get("activity_id", ""),
                "day": state.clock.day, "phase": state.clock.phase}
    return select


def trade_view(state, actor_id):
    trade = state.inventories.get("trade", {})
    offers = [deepcopy(o) for o in trade.get("offers", {}).values() if actor_id in (o["buyer_id"], o["seller_id"])]
    for offer in offers:
        failure = _validate_settlement(state, offer) if offer["status"] == "pending" else None
        offer["can_accept"] = offer["status"] == "pending" and offer["recipient_id"] == actor_id and offer["expires_tick"] > tick(state) and failure is None
        offer["unavailable_reason"] = failure.message if failure else ""
    return {"offers": offers[-30:], "memories": deepcopy(trade.get("memories", {}).get(actor_id, []))}


def campus_trade_invariant(state):
    trade = state.inventories.get("trade")
    if not trade:
        return
    try:
        if trade["schema_version"] != 1 or type(trade["sequence"]) is not int or trade["sequence"] < 0:
            yield "invalid campus trade version/sequence"
        threshold = trade["policy"].get("food_reorder_nutrition", 25)
        buffer = trade["policy"].get("food_buffer_nutrition", [100, 150])
        if (type(threshold) is not int or threshold < 0 or not isinstance(buffer, (list, tuple))
                or len(buffer) != 2 or any(type(value) is not int for value in buffer)
                or not threshold < buffer[0] <= buffer[1] <= 300):
            yield "invalid campus food buffer policy"
        for key, offer in trade["offers"].items():
            if key != offer["offer_id"] or offer["status"] not in {"pending", "settled", "rejected", "cancelled", "expired"}:
                yield "invalid campus offer identity/status"
            if any(offer[k] not in state.population for k in ("buyer_id", "seller_id", "proposer_id", "recipient_id")):
                yield "unknown campus offer participant"
            if offer["buyer_id"] == offer["seller_id"] or {offer["buyer_id"], offer["seller_id"]} != {offer["proposer_id"], offer["recipient_id"]}:
                yield "invalid campus offer parties"
            if offer["item_id"] not in state.inventories["catalog"] or any(type(offer[k]) is not int or offer[k] < 1 for k in ("unit_price", "quantity")):
                yield "invalid campus offer assets"
            if any(type(offer[k]) is not int or offer[k] < 0 for k in ("created_tick", "expires_tick")) or offer["expires_tick"] <= offer["created_tick"]:
                yield "invalid campus offer clock"
        for actor_id, memories in trade["memories"].items():
            if actor_id not in state.population or not isinstance(memories, list) or len(memories) > 24:
                yield "invalid campus trade memory"
                continue
            for entry in memories:
                if (not isinstance(entry, dict) or entry.get("item_id") not in state.inventories["catalog"]
                        or type(entry.get("unit_price")) is not int or entry["unit_price"] < 1
                        or type(entry.get("tick")) is not int or entry["tick"] < 0):
                    yield "invalid campus trade memory entry"
        for field in ("next_private_tick", "acquired", "phase_counts"):
            if not set(trade[field]).issubset(state.population):
                yield "unknown campus trade cooldown actor"
        for value in [*trade["next_private_tick"].values(), *trade["pair_tick"].values()]:
            if type(value) is not int or value < 0:
                yield "invalid campus trade cooldown tick"
        for items in trade["acquired"].values():
            for item_id, value in items.items():
                if item_id not in state.inventories["catalog"] or type(value) is not int or value < 0:
                    yield "invalid campus acquisition clock"
        for count in trade["phase_counts"].values():
            if any(type(count.get(key)) is not int or count[key] < 0 for key in ("tick", "count")):
                yield "invalid campus trade phase count"
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        yield "invalid campus trade structure: " + str(exc)
