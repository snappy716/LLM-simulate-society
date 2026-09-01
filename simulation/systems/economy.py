"""Lightweight story economy: catalog loading, ownership, quotes, and trades."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Dict, Iterable, Tuple

from simulation.domain.inventory import (
    Inventory,
    ItemDefinition,
    Shop,
    TradeQuote,
    TradeReceipt,
)


class TradingSystem:
    def __init__(
        self,
        catalog: Dict[str, ItemDefinition],
        shops: Dict[str, Shop],
        inventories: Dict[str, Inventory],
        currency: str = "便士",
    ) -> None:
        self.catalog = catalog
        self.shops = shops
        self.inventories = inventories
        self.currency = currency

    def actor_inventory(self, actor_id: str) -> Inventory:
        inventory = self.inventories.get(actor_id)
        if inventory is None:
            raise KeyError(f"unknown inventory owner: {actor_id}")
        return inventory

    @staticmethod
    def actor_balance(world, actor_id: str) -> int:
        if actor_id == "player":
            return int(world.player_wealth)
        npc = world.npcs.get(actor_id)
        if npc is None:
            raise KeyError(f"unknown actor: {actor_id}")
        return int(npc.wealth)

    @staticmethod
    def set_actor_balance(world, actor_id: str, value: int) -> None:
        if actor_id == "player":
            world.player_wealth = int(value)
            return
        npc = world.npcs.get(actor_id)
        if npc is None:
            raise KeyError(f"unknown actor: {actor_id}")
        npc.wealth = int(value)

    def _unit_price(self, shop: Shop, item: ItemDefinition, direction: str) -> int:
        inventory = self.inventories[shop.inventory_id]
        desired = max(1, int(shop.desired_stock.get(item.id, 1)))
        stock_ratio = inventory.quantity(item.id) / desired
        scarcity = 1.0
        if stock_ratio <= 0.25:
            scarcity = 1.35
        elif stock_ratio <= 0.5:
            scarcity = 1.18
        elif stock_ratio >= 1.5:
            scarcity = 0.9
        if direction == "buy":
            return max(1, round(item.base_price * shop.buy_markup * scarcity))
        return max(1, round(item.base_price * shop.sell_ratio * min(1.15, scarcity)))

    def quote(
        self,
        world,
        *,
        actor_id: str,
        shop_id: str,
        item_id: str,
        quantity: int,
        direction: str,
    ) -> Tuple[TradeQuote | None, TradeReceipt | None]:
        if direction not in {"buy", "sell"}:
            return None, self._failure("invalid_direction", "交易方向只能是 buy 或 sell。", actor_id, shop_id, item_id, quantity, direction)
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            return None, self._failure("invalid_quantity", "交易数量必须是正整数。", actor_id, shop_id, item_id, quantity, direction)
        shop = self.shops.get(shop_id)
        item = self.catalog.get(item_id)
        if shop is None:
            return None, self._failure("unknown_shop", "没有找到这家商店。", actor_id, shop_id, item_id, quantity, direction)
        if item is None:
            return None, self._failure("unknown_item", "没有找到这种物品。", actor_id, shop_id, item_id, quantity, direction)
        if actor_id not in self.inventories or (actor_id != "player" and actor_id not in world.npcs):
            return None, self._failure("unknown_actor", "交易者不存在。", actor_id, shop_id, item_id, quantity, direction)
        if world.phase.value not in shop.open_phases:
            return None, self._failure("shop_closed", f"{shop.name} 当前没有营业。", actor_id, shop_id, item_id, quantity, direction)
        if not item.tradeable:
            return None, self._failure("not_tradeable", f"{item.name} 不能通过普通交易转移。", actor_id, shop_id, item_id, quantity, direction)
        if item.legality not in shop.accepted_legalities:
            return None, self._failure("legality_rejected", f"{shop.name} 不接收 {item.name}。", actor_id, shop_id, item_id, quantity, direction)
        if direction == "sell" and shop.accepted_categories and item.category not in shop.accepted_categories:
            return None, self._failure("category_rejected", f"{shop.name} 不收购这类物品。", actor_id, shop_id, item_id, quantity, direction)
        unit_price = self._unit_price(shop, item, direction)
        quote = TradeQuote(direction, actor_id, shop_id, item_id, quantity, unit_price,
                           unit_price * quantity, self.currency)
        return quote, None

    def trade(
        self,
        world,
        *,
        actor_id: str,
        shop_id: str,
        item_id: str,
        quantity: int = 1,
        direction: str = "buy",
    ) -> TradeReceipt:
        quote, error = self.quote(
            world, actor_id=actor_id, shop_id=shop_id, item_id=item_id,
            quantity=quantity, direction=direction,
        )
        if error is not None:
            return error
        assert quote is not None
        shop = self.shops[shop_id]
        item = self.catalog[item_id]
        actor_inventory = self.inventories[actor_id]
        shop_inventory = self.inventories[shop.inventory_id]
        actor_balance = self.actor_balance(world, actor_id)

        if direction == "buy":
            if shop_inventory.quantity(item_id) < quantity:
                return self._failure("out_of_stock", f"{shop.name} 的 {item.name} 库存不足。", actor_id, shop_id, item_id, quantity, direction)
            if actor_balance < quote.total_price:
                return self._failure("insufficient_funds", f"购买 {item.name} 需要 {quote.total_price} {self.currency}。", actor_id, shop_id, item_id, quantity, direction)
            if not actor_inventory.can_add(item, quantity, self.catalog):
                return self._failure("inventory_full", "背包容量不足或已持有该唯一物品。", actor_id, shop_id, item_id, quantity, direction)
        else:
            if actor_inventory.quantity(item_id) < quantity:
                return self._failure("item_missing", f"没有足够的 {item.name} 可以出售。", actor_id, shop_id, item_id, quantity, direction)
            if shop.cash < quote.total_price:
                return self._failure("shop_insufficient_funds", f"{shop.name} 暂时没有足够现金收购。", actor_id, shop_id, item_id, quantity, direction)
            if not shop_inventory.can_add(item, quantity, self.catalog):
                return self._failure("shop_inventory_full", f"{shop.name} 无法再收下 {item.name}。", actor_id, shop_id, item_id, quantity, direction)

        actor_quantity = actor_inventory.quantity(item_id)
        shop_quantity = shop_inventory.quantity(item_id)
        old_actor_balance = actor_balance
        old_shop_balance = shop.cash
        try:
            if direction == "buy":
                shop_inventory.remove(item_id, quantity)
                actor_inventory.add(item, quantity, self.catalog)
                self.set_actor_balance(world, actor_id, actor_balance - quote.total_price)
                shop.cash += quote.total_price
            else:
                actor_inventory.remove(item_id, quantity)
                shop_inventory.add(item, quantity, self.catalog)
                self.set_actor_balance(world, actor_id, actor_balance + quote.total_price)
                shop.cash -= quote.total_price
            invariant_errors = self.validate_invariants(world)
            if invariant_errors:
                raise RuntimeError("; ".join(invariant_errors))
        except Exception:
            self._restore_quantity(actor_inventory, item_id, actor_quantity)
            self._restore_quantity(shop_inventory, item_id, shop_quantity)
            self.set_actor_balance(world, actor_id, old_actor_balance)
            shop.cash = old_shop_balance
            raise

        verb = "购买" if direction == "buy" else "出售"
        balance = self.actor_balance(world, actor_id)
        return TradeReceipt(
            True, "success",
            f"{actor_id} 从 {shop.name}{verb} {quantity} × {item.name}，共计 {quote.total_price} {self.currency}。",
            direction, actor_id, shop_id, item_id, quantity, quote.unit_price,
            quote.total_price, balance, shop.cash,
        )

    @staticmethod
    def _restore_quantity(inventory: Inventory, item_id: str, quantity: int) -> None:
        if quantity > 0:
            inventory.quantities[item_id] = quantity
        else:
            inventory.quantities.pop(item_id, None)

    @staticmethod
    def _failure(code, message, actor_id, shop_id, item_id, quantity, direction) -> TradeReceipt:
        return TradeReceipt(False, code, message, direction, actor_id, shop_id,
                            item_id, quantity if isinstance(quantity, int) else 0)

    def validate_invariants(self, world) -> list[str]:
        errors: list[str] = []
        unique_owners: Dict[str, str] = {}
        for inventory_id, inventory in self.inventories.items():
            for item_id, quantity in inventory.quantities.items():
                if item_id not in self.catalog:
                    errors.append(f"{inventory_id}: unknown item {item_id}")
                    continue
                if not isinstance(quantity, int) or quantity <= 0:
                    errors.append(f"{inventory_id}: invalid quantity for {item_id}")
                definition = self.catalog[item_id]
                if definition.unique:
                    previous = unique_owners.get(item_id)
                    if quantity != 1 or previous is not None:
                        errors.append(f"unique item has multiple owners: {item_id}")
                    unique_owners[item_id] = inventory_id
            if inventory.total_weight(self.catalog) > inventory.max_weight + 1e-9:
                errors.append(f"{inventory_id}: overweight")
        if int(world.player_wealth) < 0:
            errors.append("player: negative balance")
        for npc in world.npcs.values():
            if int(npc.wealth) < 0:
                errors.append(f"{npc.id}: negative balance")
        for shop in self.shops.values():
            if shop.cash < 0:
                errors.append(f"{shop.id}: negative balance")
        return errors

    def public_inventory(self, inventory_id: str) -> list[dict]:
        inventory = self.inventories[inventory_id]
        result = []
        for item_id in sorted(inventory.quantities):
            quantity = inventory.quantity(item_id)
            if quantity <= 0 or item_id not in self.catalog:
                continue
            item = self.catalog[item_id]
            result.append({**asdict(item), "quantity": quantity})
        return result

    def restock_shops(self, world) -> None:
        for shop in self.shops.values():
            inventory = self.inventories[shop.inventory_id]
            changes = {}
            for item_id, desired in shop.desired_stock.items():
                current = inventory.quantity(item_id)
                if current >= desired:
                    continue
                amount = max(1, (desired - current + 2) // 3)
                inventory.quantities[item_id] = min(desired, current + amount)
                changes[item_id] = inventory.quantity(item_id) - current
            if changes:
                world.ledger.emit(
                    day=world.day, phase="night_resolution", system="trade_system",
                    event_type="SHOP_RESTOCKED",
                    message=f"{shop.name} 完成日常补货。", scene_id=shop.scene_id,
                    actor_ids=[shop.keeper_id] if shop.keeper_id else [],
                    payload={"shop_id": shop.id, "changes": changes},
                )


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_economy_content(content_dir: Path) -> tuple[Dict[str, ItemDefinition], list[dict], str]:
    item_payload = _read_json(content_dir / "items" / "catalog.json")
    shop_payload = _read_json(content_dir / "items" / "shops.json")
    if item_payload.get("schema_version") != 1 or shop_payload.get("schema_version") != 1:
        raise ValueError("unsupported item content schema")
    catalog: Dict[str, ItemDefinition] = {}
    for raw in item_payload.get("items", []):
        definition = ItemDefinition(**raw)
        if definition.id in catalog:
            raise ValueError(f"duplicate item definition: {definition.id}")
        if definition.base_price < 0 or definition.weight < 0 or definition.stack_limit < 1:
            raise ValueError(f"invalid item definition: {definition.id}")
        if definition.legality not in {"legal", "restricted", "contraband"}:
            raise ValueError(f"invalid legality: {definition.id}")
        catalog[definition.id] = definition
    if not 30 <= len(catalog) <= 50:
        raise ValueError("demo item catalog must contain 30 to 50 effective items")
    shops = list(shop_payload.get("shops", []))
    return catalog, shops, str(item_payload.get("currency", "便士"))


def initialize_economy(world, content_dir: Path) -> TradingSystem:
    catalog, raw_shops, currency = load_economy_content(content_dir)
    inventories: Dict[str, Inventory] = {
        "player": Inventory("player", max_weight=35.0),
    }
    for npc_id in world.npcs:
        inventories[npc_id] = Inventory(npc_id, max_weight=25.0)

    shops: Dict[str, Shop] = {}
    for raw in raw_shops:
        stock = {str(key): int(value) for key, value in raw.pop("stock").items()}
        for item_id, quantity in stock.items():
            if item_id not in catalog or quantity <= 0:
                raise ValueError(f"invalid stock in {raw.get('id')}: {item_id}")
        inventory_id = f"shop:{raw['id']}"
        inventories[inventory_id] = Inventory(inventory_id, max_weight=100000.0,
                                               quantities=dict(stock))
        shop = Shop(inventory_id=inventory_id, desired_stock=dict(stock), **raw)
        if shop.id in shops:
            raise ValueError(f"duplicate shop: {shop.id}")
        candidates = sorted(
            (npc for npc in world.npcs.values()
             if npc.occupation in shop.keeper_occupations and npc.work_scene == shop.scene_id),
            key=lambda npc: npc.id,
        )
        if not candidates:
            candidates = sorted(
                (npc for npc in world.npcs.values() if npc.work_scene == shop.scene_id),
                key=lambda npc: npc.id,
            )
        if not candidates and "black_market" in shop.tags:
            candidates = sorted(
                (npc for npc in world.npcs.values() if npc.layer == "hostile_beyonder"),
                key=lambda npc: npc.id,
            )
        shop.keeper_id = candidates[0].id if candidates else None
        shops[shop.id] = shop

    system = TradingSystem(catalog, shops, inventories, currency)
    player_inventory = inventories["player"]
    for item_id, quantity in {"bread_loaf": 2, "newspaper_issue": 1, "hemp_rope": 1}.items():
        player_inventory.add(catalog[item_id], quantity, catalog)
    world.player_wealth = 120

    # Deterministic profession kits do not consume the world's RNG stream.
    profession_items = {
        "医生": "bandage_roll", "护士": "bandage_roll", "药剂师": "pain_tonic",
        "记者": "blank_notebook", "警察": "walking_cane", "码头工人": "hemp_rope",
        "机械师": "crowbar", "裁缝": "sewing_kit", "酒保": "beer_bottle",
        "占卜师": "silver_charm",
    }
    for npc in world.npcs.values():
        item_id = profession_items.get(npc.occupation)
        if item_id:
            inventories[npc.id].add(catalog[item_id], 1, catalog)
    errors = system.validate_invariants(world)
    if errors:
        raise ValueError("invalid initial economy: " + "; ".join(errors))
    return system


def restock_essential_supplies(world):
    supplies = [
        ("object:market_food_crate", 70, 240, "市场摊贩与周边农场补充日常食物"),
        ("object:hospital_medicine", 8, 60, "医院药剂师完成药品调配与补给"),
        ("object:church_community_meal", 4, 80, "教会厨房补充救济餐"),
    ]
    for object_id, amount, capacity, reason in supplies:
        obj = world.objects[object_id]
        old = obj.quantity
        obj.quantity = min(capacity, obj.quantity + amount)
        if obj.quantity != old:
            world.ledger.emit(
                day=world.day,
                phase="night_resolution",
                system="supply_system",
                event_type="SUPPLY_RESTOCKED",
                message=f"{reason}：{obj.name} 从 {old} 补充到 {obj.quantity}。",
                scene_id=obj.scene_id,
                payload={
                    "object_id": object_id,
                    "old_quantity": old,
                    "new_quantity": obj.quantity,
                },
            )
    economy = getattr(world, "economy", None)
    if economy is not None:
        economy.restock_shops(world)


__all__ = [
    "TradingSystem", "initialize_economy", "load_economy_content",
    "restock_essential_supplies",
]
