"""Campus-only inventory ledger. Never reads or writes the legacy World.

Currency lives on population records; stock/equipment live in inventories.
All commands use WorldKernel's clone/validate/commit transaction, including
failed transfers. Shop prices are authoritative, never client-supplied.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict

from simulation.domain.inventory import Inventory, ItemDefinition
from simulation.systems.transactions import TransactionOutcome


CAMPUS_ITEM_ACTIONS = (
    "BUY_ITEM", "SELL_ITEM", "USE_ITEM", "GIVE_ITEM", "DROP_ITEM",
    "PICK_UP_ITEM", "EQUIP_ITEM", "UNEQUIP_ITEM",
)


def install_campus_inventory(state, registry):
    """Explicit one-time initialization; reinstalling never replenishes assets."""
    if state.inventories:
        raise ValueError("campus inventory already installed")
    policy = registry.get("configuration", "campus_economy")
    catalog = {}
    for entry in policy["items"]:
        base = registry.get("item", entry["id"])
        if base is None:
            raise ValueError("unknown campus item " + entry["id"])
        base.update({key: entry[key] for key in ("name", "description")})
        catalog[entry["id"]] = asdict(ItemDefinition(**base))
    shops = {}
    for spec in policy["shops"]:
        if spec["location_id"] not in state.places or spec["id"] in shops:
            raise ValueError("invalid campus shop location or duplicate id")
        shops[spec["id"]] = {
            **deepcopy(spec), "quantities": deepcopy(spec["stock"]),
            "accepted_item_ids": list(spec["stock"]),
        }
        del shops[spec["id"]]["stock"]
    state.inventories = {
        "schema_version": 1, "currency": policy["currency"],
        "catalog": catalog, "rules": {item["id"]: deepcopy(item) for item in policy["items"]},
        "protected_items": deepcopy(policy["protected_items"]),
        "actors": {}, "shops": shops, "ground": {},
    }
    for actor_id, actor in state.population.items():
        quantities = deepcopy(policy["starter_items"])
        for item_id, quantity in policy["profession_items"].get(actor.get("occupation_id"), {}).items():
            quantities[item_id] = quantities.get(item_id, 0) + quantity
        state.inventories["actors"][actor_id] = {
            "owner_id": actor_id, "max_weight": policy["max_weight"],
            "quantities": quantities, "equipped": {},
        }
    errors = list(campus_inventory_invariant(state))
    if errors:
        raise ValueError("; ".join(errors))


def _catalog(state):
    return {key: ItemDefinition(**value) for key, value in state.inventories["catalog"].items()}


def _inventory(record, owner_id="container"):
    return Inventory(owner_id, record.get("max_weight", 1000000), record["quantities"])


def _layer(state, actor_id):
    return state.situations.get("night_world", {}).get("actor_states", {}).get(actor_id, {}).get("layer", "surface")


def _ground_key(state, actor_id):
    return _layer(state, actor_id) + ":" + state.population[actor_id]["current_location_id"]


def _busy(state, actor_id):
    return bool(state.metadata.get("campus_combat", {}).get("active_battle_by_actor", {}).get(actor_id))


def _failure(code, message):
    return TransactionOutcome(False, False, code, message)


def _movable(state, actor_id, item_id, quantity):
    record = state.inventories["actors"][actor_id]
    reserve = sum(1 for equipped in record["equipped"].values() if equipped == item_id)
    if actor_id != "player":
        occupation = state.population[actor_id].get("occupation_id")
        reserve = max(reserve, state.inventories["protected_items"].get(occupation, {}).get(item_id, 0))
    return record["quantities"].get(item_id, 0) - quantity >= reserve


def make_campus_inventory_handler():
    def handle(context, command):
        state, actor_id, params = context.state, command.actor_id, command.parameters
        ledger = state.inventories
        if actor_id not in ledger.get("actors", {}):
            return _failure("unknown_actor", "没有找到校园角色的库存。")
        if command.source == "player" and actor_id != "player":
            return _failure("actor_not_authorized", "玩家不能代替 NPC 处置物品。")
        if command.issued_day != state.clock.day or command.issued_phase != state.clock.phase:
            return _failure("command_clock_mismatch", "物品指令所属的日期或时段已过期。")
        if _busy(state, actor_id):
            return _failure("battle_locked", "战斗期间的物品费用与效果尚未接通，不能从手机绕过战斗规则。")
        item_id = params.get("item_id")
        if not isinstance(item_id, str) or item_id not in ledger["catalog"]:
            return _failure("unknown_item", "没有找到这种校园物品。")
        quantity = params.get("quantity", 1)
        if type(quantity) is not int or not 1 <= quantity <= 999:
            return _failure("invalid_quantity", "数量必须为 1～999 的整数。")
        action = command.action_id
        actor = state.population[actor_id]
        record = ledger["actors"][actor_id]
        catalog = _catalog(state)
        item = catalog[item_id]
        rule = ledger["rules"][item_id]
        source, destination = record, None
        target_id, shop, total = None, None, 0
        if action in {"BUY_ITEM", "SELL_ITEM"}:
            shop_id = params.get("shop_id")
            shop = ledger["shops"].get(shop_id) if isinstance(shop_id, str) else None
            if shop is None:
                return _failure("unknown_shop", "没有找到商店。")
            if actor["current_location_id"] != shop["location_id"] or _layer(state, actor_id) != "surface":
                return _failure("location_mismatch", "请先到表世界的商店柜台，手机不能远程取货。")
            if state.clock.phase not in state.places[shop["location_id"]].get("open_phases", []):
                return _failure("shop_closed", "当前时段商店未营业。")
            if not item.tradeable or item_id not in shop["accepted_item_ids"]:
                return _failure("not_tradeable", "这家商店不交易这种物品。")
            if action == "SELL_ITEM" and shop["sell_percent"] <= 0:
                return _failure("not_buying", "这个窗口不回收物品。")
            unit_price = item.base_price if action == "BUY_ITEM" else max(1, item.base_price * shop["sell_percent"] // 100)
            total = unit_price * quantity
            if (actor["wealth"] if action == "BUY_ITEM" else shop["cash"]) < total:
                return _failure("insufficient_funds", "付款方余额不足。")
            source, destination = (shop, record) if action == "BUY_ITEM" else (record, shop)
        elif action == "GIVE_ITEM":
            target_id = params.get("target_id")
            if not isinstance(target_id, str) or target_id not in ledger["actors"] or target_id == actor_id:
                return _failure("invalid_target", "请选择另一名角色。")
            target = state.population[target_id]
            if target["current_location_id"] != actor["current_location_id"] or _layer(state, target_id) != _layer(state, actor_id):
                return _failure("location_mismatch", "双方必须在同一地点与同一世界层。")
            if _busy(state, target_id):
                return _failure("battle_locked", "对方正在战斗，不能绕过战斗流程转交物品。")
            destination = ledger["actors"][target_id]
        elif action in {"DROP_ITEM", "PICK_UP_ITEM"}:
            ground = ledger["ground"].setdefault(_ground_key(state, actor_id), {"quantities": {}})
            source, destination = (record, ground) if action == "DROP_ITEM" else (ground, record)
        elif action not in CAMPUS_ITEM_ACTIONS:
            return _failure("unknown_action", "不支持的物品行动。")

        if source["quantities"].get(item_id, 0) < quantity:
            return _failure("item_missing", "库存不足。")
        if destination is not None:
            if source is record and not _movable(state, actor_id, item_id, quantity):
                return _failure("item_protected", "须先卸下装备；NPC 不会交出职业必需品的最后一份。")
            if not _inventory(destination).can_add(item, quantity, catalog):
                return _failure("inventory_full", "接收方背包负重不足。")
            _inventory(source).remove(item_id, quantity)
            _inventory(destination).add(item, quantity, catalog)
            if shop is not None:
                paid = total if action == "BUY_ITEM" else -total
                actor["wealth"] -= paid
                shop["cash"] += paid
        elif action == "USE_ITEM":
            if quantity != 1:
                return _failure("single_item_required", "每次使用一件物品。")
            reduction = rule.get("food_reduction", 0)
            if not reduction:
                return _failure("requires_other_system", item.description)
            before = actor["needs"]["food"]
            if before <= 0:
                return _failure("no_effect", "目前不饿，无需消耗食物。")
            actor["needs"]["food"] = max(0, before - reduction)
            _inventory(record).remove(item_id, 1)
        else:
            if quantity != 1:
                return _failure("single_item_required", "每次装备或卸下一件物品。")
            slot = rule.get("slot")
            if not slot:
                return _failure("not_equippable", "这件物品不是装备。")
            if action == "EQUIP_ITEM":
                if slot in record["equipped"]:
                    return _failure("slot_occupied", "请先卸下这个部位的装备。")
                record["equipped"][slot] = item_id
            else:
                if record["equipped"].get(slot) != item_id:
                    return _failure("not_equipped", "尚未装备这件物品。")
                del record["equipped"][slot]
        verbs = {"BUY_ITEM":"购买", "SELL_ITEM":"出售", "USE_ITEM":"使用", "GIVE_ITEM":"转交", "DROP_ITEM":"放下", "PICK_UP_ITEM":"拾取", "EQUIP_ITEM":"装备", "UNEQUIP_ITEM":"卸下"}
        message = f"{actor.get('display_name', actor_id)}{verbs[action]}了 {quantity} 件{item.name}。"
        payload = {"action_id":action, "item_id":item_id, "quantity":quantity, "total_price":total, "balance":actor["wealth"], "target_id":target_id}
        if shop:
            payload.update(shop_id=shop["id"], unit_price=unit_price)
        if action == "USE_ITEM":
            payload["food_change"] = actor["needs"]["food"] - before
        context.emit("CAMPUS_ITEM_ACTION_COMPLETED", message, actor_ids=[actor_id] + ([target_id] if target_id else []), scene_id=actor["current_location_id"], payload=payload, knowledge_tags=["trade"] if shop else ["item"])
        return TransactionOutcome(True, True, "success", message, commit=True, payload=payload)
    return handle


def campus_inventory_invariant(state):
    ledger = state.inventories
    if not ledger:
        return
    if ledger.get("schema_version") != 1:
        yield "unsupported campus inventory version"
        return
    try:
        catalog = _catalog(state)
        if set(ledger["actors"]) != set(state.population):
            yield "campus actor inventory coverage differs"
        for actor_id, actor in state.population.items():
            if type(actor.get("wealth")) is not int or actor["wealth"] < 0:
                yield "invalid campus wealth: " + actor_id
        for key, shop in ledger["shops"].items():
            if type(shop.get("cash")) is not int or shop["cash"] < 0 or shop["location_id"] not in state.places:
                yield "invalid campus shop: " + key
        containers = list(ledger["actors"].values()) + list(ledger["shops"].values()) + list(ledger["ground"].values())
        for record in containers:
            for item_id, quantity in record["quantities"].items():
                if item_id not in catalog or type(quantity) is not int or quantity <= 0:
                    yield "invalid campus item quantity"
            inventory = _inventory(record)
            if inventory.max_weight < 0 or inventory.total_weight(catalog) > inventory.max_weight + 1e-9:
                yield "campus inventory overweight"
            for slot, item_id in record.get("equipped", {}).items():
                if record["quantities"].get(item_id, 0) < 1 or ledger["rules"].get(item_id, {}).get("slot") != slot:
                    yield "invalid campus equipped item"
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        yield "invalid campus inventory structure: " + str(exc)


def campus_inventory_view(state, actor_id="player"):
    ledger = state.inventories
    if not ledger:
        return {"enabled": False}
    record = ledger["actors"][actor_id]
    location = state.population[actor_id]["current_location_id"]
    shops = []
    for shop in ledger["shops"].values():
        nearby = location == shop["location_id"] and _layer(state, actor_id) == "surface"
        open_now = state.clock.phase in state.places[shop["location_id"]].get("open_phases", [])
        shops.append({
            "id": shop["id"], "name": shop["name"], "location_id": shop["location_id"],
            "location_name": state.places[shop["location_id"]]["name"],
            "nearby": nearby, "open": open_now, "cash": shop["cash"],
            "goods": [{"item_id": item_id, "stock": shop["quantities"].get(item_id, 0),
                       "buy_price": ledger["catalog"][item_id]["base_price"],
                       "sell_price": max(1, ledger["catalog"][item_id]["base_price"] * shop["sell_percent"] // 100) if shop["sell_percent"] else 0}
                      for item_id in shop["accepted_item_ids"]],
        })
    return deepcopy({
        "enabled":True, "currency":ledger["currency"], "balance":state.population[actor_id]["wealth"],
        "items":ledger["catalog"], "inventory":record, "weight":_inventory(record).total_weight(_catalog(state)),
        "ground":ledger["ground"].get(_ground_key(state, actor_id), {"quantities":{}}),
        "shops":shops, "battle_locked":_busy(state, actor_id),
        "nearby_actor_ids":[key for key, actor in state.population.items() if key != actor_id and actor["current_location_id"] == location and _layer(state, key) == _layer(state, actor_id) and not _busy(state, key)],
    })
