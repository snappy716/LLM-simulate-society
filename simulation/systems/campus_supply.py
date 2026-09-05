"""Paid external shop supply, executed only inside campus transactions.

An order transfers shop cash to an explicit outside account. Only a later
delivery imports goods. Nothing resets stock and no player wallet funds shops.
"""
from collections import Counter
from copy import deepcopy


def validate_supply_policy(policy):
    if not isinstance(policy, dict):
        raise ValueError("campus supply policy must be an object")
    if not isinstance(policy.get("supplier_name"), str) or not policy["supplier_name"]:
        raise ValueError("campus supply requires supplier_name")
    for field, low, high in (("wholesale_percent", 1, 100), ("reorder_percent", 1, 99),
                             ("cash_reserve", 0, 1000000)):
        if type(policy.get(field)) is not int or not low <= policy[field] <= high:
            raise ValueError("invalid campus supply " + field)


def install_campus_supply(state, registry):
    if "supply" in state.inventories:
        raise ValueError("campus supply already installed")
    policy = registry.get("configuration", "campus_economy")["supply_policy"]
    validate_supply_policy(policy)
    state.inventories["supply"] = {
        "schema_version": 1, "policy": deepcopy(policy), "available": True,
        "sequence": 0, "orders": {}, "last_order_day": {},
        "supplier_receipts": 0, "imported_quantities": {},
        "targets": {shop_id: deepcopy(shop["quantities"])
                    for shop_id, shop in state.inventories["shops"].items()},
    }


def _incoming(supply, shop_id, item_id):
    return [order for order in supply["orders"].values()
            if order["status"] == "in_transit" and order["shop_id"] == shop_id and order["item_id"] == item_id]


def receive_campus_supply(context):
    state = context.state
    supply = state.inventories.get("supply")
    if not supply:
        return {"supply_deliveries": 0}
    count = 0
    for order in supply["orders"].values():
        if order["status"] != "in_transit" or state.clock.day < order["due_day"]:
            continue
        shop = state.inventories["shops"][order["shop_id"]]
        if state.clock.phase not in state.places[shop["location_id"]].get("open_phases", []):
            continue
        if not supply["available"]:
            if order.get("last_delay_day") != state.clock.day:
                order["last_delay_day"] = state.clock.day
                context.emit("CAMPUS_SUPPLY_DELAYED", f"{shop['name']}的到货因校外运输暂停而延迟，货款不重复扣除。",
                             scene_id=shop["location_id"], payload=deepcopy(order), knowledge_tags=["trade", "supply"])
            continue
        item_id, quantity = order["item_id"], order["quantity"]
        shop["quantities"][item_id] = shop["quantities"].get(item_id, 0) + quantity
        supply["imported_quantities"][item_id] = supply["imported_quantities"].get(item_id, 0) + quantity
        order.update(status="delivered", delivered_day=state.clock.day, delivered_phase=state.clock.phase)
        context.emit("CAMPUS_SUPPLY_DELIVERED", f"{shop['name']}收到校外供货：{state.inventories['catalog'][item_id]['name']} {quantity} 件，已入库。",
                     scene_id=shop["location_id"], payload=deepcopy(order), knowledge_tags=["trade", "supply"])
        count += 1
    return {"supply_deliveries": count}


def review_campus_supply(context):
    """Review after NPC purchases. At most one order per shop/item/day.

    On-hand plus in-transit stock determines the shortage. Partial affordable
    orders are allowed; cash reserves remain available for normal shop buybacks.
    """
    state = context.state
    supply = state.inventories.get("supply")
    if not supply or not supply["available"]:
        return {"supply_orders": 0}
    policy, count = supply["policy"], 0
    for shop_id, shop in sorted(state.inventories["shops"].items()):
        if state.clock.phase not in state.places[shop["location_id"]].get("open_phases", []):
            continue
        targets = supply["targets"][shop_id]
        # Scarcer ratios first. Stable item ids break ties deterministically.
        candidates = sorted(targets, key=lambda item: (shop["quantities"].get(item, 0) / targets[item], item))
        for item_id in candidates:
            stock = shop["quantities"].get(item_id, 0)
            target = targets[item_id]
            incoming = _incoming(supply, shop_id, item_id)
            key = shop_id + ":" + item_id
            if stock * 100 > target * policy["reorder_percent"] or incoming or supply["last_order_day"].get(key) == state.clock.day:
                continue
            unit_price = max(1, (state.inventories["catalog"][item_id]["base_price"] * policy["wholesale_percent"] + 99) // 100)
            quantity = min(target - stock, max(0, shop["cash"] - policy["cash_reserve"]) // unit_price)
            if quantity <= 0:
                continue
            cost = quantity * unit_price
            supply["sequence"] += 1
            order_id = f"supply:{supply['sequence']}"
            order = {"order_id": order_id, "shop_id": shop_id, "item_id": item_id,
                     "quantity": quantity, "unit_price": unit_price, "total_price": cost,
                     "ordered_day": state.clock.day, "ordered_phase": state.clock.phase,
                     "due_day": state.clock.day + 1, "status": "in_transit"}
            shop["cash"] -= cost
            supply["supplier_receipts"] += cost
            supply["orders"][order_id] = order
            supply["last_order_day"][key] = state.clock.day
            context.emit("CAMPUS_SUPPLY_ORDERED", f"{shop['name']}支付 {cost} 元订购{state.inventories['catalog'][item_id]['name']} {quantity} 件，预计第 {order['due_day']} 天营业时到货。",
                         scene_id=shop["location_id"], payload=deepcopy(order), knowledge_tags=["trade", "supply"])
            count += 1
    return {"supply_orders": count}


def supply_view(state, shop_id):
    supply = state.inventories.get("supply")
    if not supply:
        return {"enabled": False, "goods": {}}
    shop, policy = state.inventories["shops"][shop_id], supply["policy"]
    goods = {}
    for item_id, target in supply["targets"][shop_id].items():
        orders = _incoming(supply, shop_id, item_id)
        unit_price = max(1, (state.inventories["catalog"][item_id]["base_price"] * policy["wholesale_percent"] + 99) // 100)
        low = shop["quantities"].get(item_id, 0) * 100 <= target * policy["reorder_percent"]
        due = min((order["due_day"] for order in orders), default=None)
        if orders:
            status = "delayed" if not supply["available"] or state.clock.day > due else "in_transit"
        elif low and not supply["available"]:
            status = "supply_paused"
        elif low and shop["cash"] - policy["cash_reserve"] < unit_price:
            status = "insufficient_shop_funds"
        elif low:
            status = "awaiting_review"
        else:
            status = "stocked"
        goods[item_id] = {"status": status, "in_transit": sum(order["quantity"] for order in orders),
                          "due_day": due, "target_stock": target}
    return {"enabled": True, "supplier_name": policy["supplier_name"], "goods": goods}


def campus_supply_invariant(state):
    supply = state.inventories.get("supply")
    if supply is None:
        return
    try:
        if supply["schema_version"] != 1 or type(supply["available"]) is not bool:
            yield "invalid campus supply version/availability"
        validate_supply_policy(supply["policy"])
        if type(supply["sequence"]) is not int or supply["sequence"] < 0 or supply["sequence"] != len(supply["orders"]):
            yield "invalid campus supply sequence"
        if set(supply["targets"]) != set(state.inventories["shops"]):
            yield "invalid campus supply target shops"
        for shop_id, targets in supply["targets"].items():
            if set(targets) != set(state.inventories["shops"][shop_id]["accepted_item_ids"]):
                yield "invalid campus supply target items"
            if any(type(qty) is not int or qty <= 0 for qty in targets.values()):
                yield "invalid campus supply target stock"
        paid, imported, pending, ordered_days = 0, Counter(), set(), {}
        for key, order in supply["orders"].items():
            if key != order["order_id"] or order["shop_id"] not in state.inventories["shops"]:
                yield "invalid campus supply order identity"
                continue
            shop = state.inventories["shops"][order["shop_id"]]
            if order["item_id"] not in shop["accepted_item_ids"] or order["status"] not in ("in_transit", "delivered"):
                yield "invalid campus supply order item/status"
            if any(type(order[field]) is not int or order[field] < 1 for field in ("quantity", "unit_price", "total_price", "ordered_day", "due_day")):
                yield "invalid campus supply order amount/day"
                continue
            if order["total_price"] != order["quantity"] * order["unit_price"] or order["due_day"] != order["ordered_day"] + 1:
                yield "invalid campus supply payment/due day"
            pair = order["shop_id"] + ":" + order["item_id"]
            order_day_key = (pair, order["ordered_day"])
            if order_day_key in ordered_days:
                yield "duplicate same-day campus supply order"
            ordered_days[order_day_key] = True
            if order["status"] == "in_transit":
                if pair in pending:
                    yield "duplicate in-transit campus supply order"
                pending.add(pair)
            else:
                if type(order.get("delivered_day")) is not int or not order["due_day"] <= order["delivered_day"] <= state.clock.day:
                    yield "invalid campus supply delivery day"
                imported[order["item_id"]] += order["quantity"]
            paid += order["total_price"]
        if type(supply["supplier_receipts"]) is not int or supply["supplier_receipts"] != paid:
            yield "campus supply outside cash ledger mismatch"
        if dict(imported) != supply["imported_quantities"] or any(type(qty) is not int or qty <= 0 for qty in supply["imported_quantities"].values()):
            yield "campus supply import ledger mismatch"
        expected_days = {}
        for pair, day in ordered_days:
            expected_days[pair] = max(day, expected_days.get(pair, 0))
        if supply["last_order_day"] != expected_days:
            yield "campus supply last-order index mismatch"
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        yield "invalid campus supply structure: " + str(exc)
