"""Lightweight story economy: catalog loading, ownership, quotes, and trades."""
from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from typing import Dict, Iterable, Tuple

from simulation.domain.inventory import (
    Inventory,
    ItemDefinition,
    PeerTradeOffer,
    PeerTradeReceipt,
    Shop,
    TradeMemory,
    TradeQuote,
    TradeReceipt,
)


PROFESSIONAL_TRADER_LIMITS = {
    "杂货商": (5, 3),
    "摊贩": (5, 3),
    "酒保": (4, 2),
    "酒馆侍者": (3, 2),
    "药剂师": (4, 2),
    "旅行商人": (6, 4),
}


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
        self.peer_offers: Dict[str, PeerTradeOffer] = {}
        self._next_peer_offer = 1
        self.trade_memories: list[TradeMemory] = []
        self.last_peer_trade_day: Dict[str, int] = {}
        self.peer_trade_daily_counts: Dict[str, int] = {}

    def actor_inventory(self, actor_id: str) -> Inventory:
        inventory = self.inventories.get(actor_id)
        if inventory is None:
            # Story systems may introduce residents after world initialization.
            # Their empty inventory is created lazily so dynamic NPCs can
            # immediately participate without coupling narrative code to economy.
            inventory = Inventory(actor_id, max_weight=25.0)
            self.inventories[actor_id] = inventory
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
        if actor_id != "player" and actor_id not in world.npcs:
            return None, self._failure("unknown_actor", "交易者不存在。", actor_id, shop_id, item_id, quantity, direction)
        self.actor_inventory(actor_id)
        if actor_id != "player" and world.npcs[actor_id].current_scene != shop.scene_id:
            return None, self._failure(
                "location_mismatch", f"交易者不在 {shop.name} 所在地点。",
                actor_id, shop_id, item_id, quantity, direction,
            )
        if world.phase.value not in shop.open_phases:
            return None, self._failure("shop_closed", f"{shop.name} 当前没有营业。", actor_id, shop_id, item_id, quantity, direction)
        if not item.tradeable:
            return None, self._failure("not_tradeable", f"{item.name} 不能通过普通交易转移。", actor_id, shop_id, item_id, quantity, direction)
        if item.legality not in shop.accepted_legalities:
            return None, self._failure("legality_rejected", f"{shop.name} 不接收 {item.name}。", actor_id, shop_id, item_id, quantity, direction)
        if direction == "sell" and shop.accepted_categories and item.category not in shop.accepted_categories:
            return None, self._failure("category_rejected", f"{shop.name} 不收购这类物品。", actor_id, shop_id, item_id, quantity, direction)
        equipped=(world.player_equipped_item_ids if actor_id=="player"
                  else world.npcs[actor_id].equipped_item_ids)
        if direction=="sell" and item_id in equipped:
            return None,self._failure("item_equipped","必须先卸下物品才能出售。",actor_id,shop_id,item_id,quantity,direction)
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
        actor_inventory = self.actor_inventory(actor_id)
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
        old_instance_state = self._instance_state(world, actor_inventory, shop_inventory)
        try:
            if direction == "buy":
                self._move_items(world,shop.inventory_id,actor_id,item_id,quantity)
                self.set_actor_balance(world, actor_id, actor_balance - quote.total_price)
                shop.cash += quote.total_price
            else:
                self._move_items(world,actor_id,shop.inventory_id,item_id,quantity)
                self.set_actor_balance(world, actor_id, actor_balance + quote.total_price)
                shop.cash -= quote.total_price
            invariant_errors = self.validate_invariants(world)
            if invariant_errors:
                raise RuntimeError("; ".join(invariant_errors))
        except Exception:
            self._restore_quantity(actor_inventory, item_id, actor_quantity)
            self._restore_quantity(shop_inventory, item_id, shop_quantity)
            self._restore_instance_state(world,actor_inventory,shop_inventory,old_instance_state)
            self.set_actor_balance(world, actor_id, old_actor_balance)
            shop.cash = old_shop_balance
            raise

        verb = "购买" if direction == "buy" else "出售"
        balance = self.actor_balance(world, actor_id)
        self._remember(
            actor_id=actor_id, counterparty_id=shop.id, kind="shop",
            direction=direction, item_id=item_id, quantity=quantity,
            unit_price=quote.unit_price, total_price=quote.total_price,
            day=world.day, phase=world.phase.value, status="accepted",
        )
        return TradeReceipt(
            True, "success",
            f"{actor_id} 从 {shop.name}{verb} {quantity} × {item.name}，共计 {quote.total_price} {self.currency}。",
            direction, actor_id, shop_id, item_id, quantity, quote.unit_price,
            quote.total_price, balance, shop.cash,
        )

    def create_peer_offer(
        self,
        world,
        *,
        seller_id: str,
        buyer_id: str,
        item_id: str,
        quantity: int = 1,
        unit_price: int,
        valid_days: int = 0,
    ) -> tuple[PeerTradeOffer | None, PeerTradeReceipt | None]:
        """Create a non-binding NPC-to-NPC quote without moving any assets."""
        if seller_id == buyer_id:
            return None, self._peer_failure("same_actor", "不能向自己报价。", "")
        if seller_id not in world.npcs or buyer_id not in world.npcs:
            return None, self._peer_failure("unknown_actor", "报价中的 NPC 不存在。", "")
        self.actor_inventory(seller_id)
        self.actor_inventory(buyer_id)
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            return None, self._peer_failure("invalid_quantity", "交易数量必须是正整数。", "")
        if isinstance(unit_price, bool) or not isinstance(unit_price, int) or unit_price <= 0:
            return None, self._peer_failure("invalid_price", "报价必须是正整数。", "")
        item = self.catalog.get(item_id)
        if item is None:
            return None, self._peer_failure("unknown_item", "没有找到这种物品。", "")
        if not item.tradeable:
            return None, self._peer_failure("not_tradeable", f"{item.name} 不能交易。", "")
        seller = world.npcs[seller_id]
        buyer = world.npcs[buyer_id]
        if item_id in seller.equipped_item_ids:
            return None,self._peer_failure("item_equipped","卖方必须先卸下物品。","")
        if seller.current_scene != buyer.current_scene:
            return None, self._peer_failure("not_colocated", "双方不在同一地点，无法当面报价。", "")
        cooldown=max(
            self.peer_trade_cooldown_remaining(world,seller_id,item_id),
            self.peer_trade_cooldown_remaining(world,buyer_id,item_id),
        )
        if cooldown:
            return None, self._peer_failure(
                "trade_cooldown",f"双方至少还需等待 {cooldown} 天再进行私人交易。",""
            )
        if self.inventories[seller_id].quantity(item_id) < quantity:
            return None, self._peer_failure("item_missing", f"卖方没有足够的 {item.name}。", "")
        offer_id = f"peer_offer_{self._next_peer_offer:06d}"
        self._next_peer_offer += 1
        offer = PeerTradeOffer(
            id=offer_id, seller_id=seller_id, buyer_id=buyer_id,
            item_id=item_id, quantity=quantity, unit_price=unit_price,
            total_price=unit_price * quantity, currency=self.currency,
            scene_id=seller.current_scene, created_day=world.day,
            created_phase=world.phase.value,
            expires_day=world.day + max(0, int(valid_days)),
        )
        self.peer_offers[offer.id] = offer
        for actor_id,direction in ((seller_id,"sell"),(buyer_id,"buy")):
            self._remember(
                actor_id=actor_id,counterparty_id=buyer_id if actor_id==seller_id else seller_id,
                kind="peer",direction=direction,item_id=item_id,quantity=quantity,
                unit_price=unit_price,total_price=offer.total_price,day=world.day,
                phase=world.phase.value,status="offered",offer_id=offer.id)
        return offer, None

    def respond_peer_offer(
        self,
        world,
        *,
        offer_id: str,
        responder_id: str,
        accept: bool,
        reason: str = "",
    ) -> PeerTradeReceipt:
        """Accept or reject a quote; accepted transfers settle atomically."""
        offer = self.peer_offers.get(offer_id)
        if offer is None:
            return self._peer_failure("unknown_offer", "没有找到这份报价。", offer_id)
        if responder_id != offer.buyer_id:
            return self._peer_failure("wrong_recipient", "只有报价接收方可以回应。", offer_id, offer)
        if offer.status != "pending":
            return self._peer_failure("offer_not_pending", "这份报价已经处理。", offer_id, offer)
        if world.day > offer.expires_day:
            offer.status = "expired"
            offer.response_reason = "报价已过期"
            return self._peer_failure("offer_expired", "这份报价已经过期。", offer_id, offer)
        if not accept:
            offer.status = "rejected"
            offer.response_reason = reason or "接收方拒绝报价"
            for actor_id,direction in ((offer.seller_id,"sell"),(offer.buyer_id,"buy")):
                self._remember(
                    actor_id=actor_id,
                    counterparty_id=offer.buyer_id if actor_id==offer.seller_id else offer.seller_id,
                    kind="peer",direction=direction,item_id=offer.item_id,
                    quantity=offer.quantity,unit_price=offer.unit_price,
                    total_price=offer.total_price,day=world.day,phase=world.phase.value,
                    status="rejected",offer_id=offer.id)
            return self._peer_failure("rejected", offer.response_reason, offer_id, offer)

        seller = world.npcs.get(offer.seller_id)
        buyer = world.npcs.get(offer.buyer_id)
        item = self.catalog.get(offer.item_id)
        if seller is None or buyer is None or item is None:
            return self._peer_failure("invalid_offer", "报价引用的参与者或物品已经不存在。", offer_id, offer)
        if seller.current_scene != buyer.current_scene or seller.current_scene != offer.scene_id:
            return self._peer_failure("not_colocated", "双方不在报价地点，无法完成交割。", offer_id, offer)
        seller_inventory = self.inventories[offer.seller_id]
        buyer_inventory = self.inventories[offer.buyer_id]
        if seller_inventory.quantity(offer.item_id) < offer.quantity:
            return self._peer_failure("item_missing", f"卖方已没有足够的 {item.name}。", offer_id, offer)
        if buyer.wealth < offer.total_price:
            return self._peer_failure("insufficient_funds", f"买方没有足够的 {self.currency}。", offer_id, offer)
        if not buyer_inventory.can_add(item, offer.quantity, self.catalog):
            return self._peer_failure("inventory_full", "买方物品栏无法接收这些物品。", offer_id, offer)

        seller_quantity = seller_inventory.quantity(offer.item_id)
        buyer_quantity = buyer_inventory.quantity(offer.item_id)
        seller_balance = int(seller.wealth)
        buyer_balance = int(buyer.wealth)
        old_status = offer.status
        old_instance_state = self._instance_state(world,seller_inventory,buyer_inventory)
        try:
            self._move_items(
                world,offer.seller_id,offer.buyer_id,offer.item_id,offer.quantity)
            seller.wealth = seller_balance + offer.total_price
            buyer.wealth = buyer_balance - offer.total_price
            offer.status = "accepted"
            offer.response_reason = reason or "接收方接受报价"
            invariant_errors = self.validate_invariants(world)
            if invariant_errors:
                raise RuntimeError("; ".join(invariant_errors))
        except Exception:
            self._restore_quantity(seller_inventory, offer.item_id, seller_quantity)
            self._restore_quantity(buyer_inventory, offer.item_id, buyer_quantity)
            self._restore_instance_state(world,seller_inventory,buyer_inventory,old_instance_state)
            seller.wealth = seller_balance
            buyer.wealth = buyer_balance
            offer.status = old_status
            offer.response_reason = ""
            raise
        for actor_id,direction in ((offer.seller_id,"sell"),(offer.buyer_id,"buy")):
            self.last_peer_trade_day[actor_id] = world.day
            self.last_peer_trade_day[f"{actor_id}:{offer.item_id}"] = world.day
            daily_key=f"{world.day}:{actor_id}"
            item_key=f"{world.day}:{actor_id}:{offer.item_id}"
            self.peer_trade_daily_counts[daily_key]=self.peer_trade_daily_counts.get(daily_key,0)+1
            self.peer_trade_daily_counts[item_key]=self.peer_trade_daily_counts.get(item_key,0)+1
            self._remember(
                actor_id=actor_id,
                counterparty_id=offer.buyer_id if actor_id==offer.seller_id else offer.seller_id,
                kind="peer",direction=direction,item_id=offer.item_id,
                quantity=offer.quantity,unit_price=offer.unit_price,
                total_price=offer.total_price,day=world.day,phase=world.phase.value,
                status="accepted",offer_id=offer.id)
        return PeerTradeReceipt(
            True, "success",
            f"{buyer.name} 接受 {seller.name} 的报价，购买 {offer.quantity} × {item.name}，"
            f"共计 {offer.total_price} {self.currency}。",
            offer.id, offer.seller_id, offer.buyer_id, offer.item_id,
            offer.quantity, offer.unit_price, offer.total_price,
            int(seller.wealth), int(buyer.wealth),
        )

    def expire_peer_offers(self, world) -> list[str]:
        expired = []
        for offer in self.peer_offers.values():
            if offer.status == "pending" and world.day >= offer.expires_day:
                offer.status = "expired"
                offer.response_reason = "当日结束，报价过期"
                expired.append(offer.id)
        return expired

    @staticmethod
    def is_professional_trader(world, actor_id: str) -> bool:
        npc=world.npcs.get(actor_id)
        return bool(npc and npc.occupation in PROFESSIONAL_TRADER_LIMITS)

    @staticmethod
    def peer_trade_cooldown_days(actor_id: str, item_id: str) -> int:
        """Stable per actor/item interval in the requested two-to-four day range."""
        checksum=sum(ord(char) for char in f"{actor_id}:{item_id}")
        return 2 + checksum % 3

    def peer_trade_cooldown_remaining(self, world, actor_id: str, item_id: str) -> int:
        npc=world.npcs.get(actor_id)
        limits=PROFESSIONAL_TRADER_LIMITS.get(npc.occupation) if npc else None
        if limits:
            daily_limit,item_limit=limits
            daily=self.peer_trade_daily_counts.get(f"{world.day}:{actor_id}",0)
            item_daily=self.peer_trade_daily_counts.get(f"{world.day}:{actor_id}:{item_id}",0)
            return 1 if daily>=daily_limit or item_daily>=item_limit else 0
        last_actor=self.last_peer_trade_day.get(actor_id,-10000)
        last_item=self.last_peer_trade_day.get(f"{actor_id}:{item_id}",-10000)
        elapsed=world.day-max(last_actor,last_item)
        return max(0,self.peer_trade_cooldown_days(actor_id,item_id)-elapsed)

    def recent_memories(self, actor_id: str, limit: int = 12) -> list[TradeMemory]:
        return [memory for memory in reversed(self.trade_memories)
                if memory.actor_id==actor_id][:limit]

    def recent_accepted_unit_price(self, actor_id: str, item_id: str) -> int | None:
        for memory in reversed(self.trade_memories):
            if (memory.actor_id==actor_id and memory.item_id==item_id
                    and memory.status=="accepted"):
                return memory.unit_price
        return None

    def peer_quote_recent(self, world, seller_id: str, buyer_id: str, item_id: str) -> bool:
        return any(
            memory.actor_id==seller_id and memory.counterparty_id==buyer_id
            and memory.item_id==item_id and memory.kind=="peer"
            and memory.status=="offered" and memory.day>=world.day-1
            for memory in reversed(self.trade_memories[-400:])
        )

    def _remember(self, **kwargs) -> None:
        self.trade_memories.append(TradeMemory(**kwargs))
        if len(self.trade_memories)>4000:
            del self.trade_memories[:-3000]

    @staticmethod
    def _peer_failure(
        code: str,
        message: str,
        offer_id: str,
        offer: PeerTradeOffer | None = None,
    ) -> PeerTradeReceipt:
        return PeerTradeReceipt(
            False, code, message, offer_id,
            offer.seller_id if offer else "",
            offer.buyer_id if offer else "",
            offer.item_id if offer else "",
            offer.quantity if offer else 0,
            offer.unit_price if offer else 0,
            offer.total_price if offer else 0,
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
        if hasattr(world,"item_instances"):
            world.item_instances.reconcile(world.day)
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
        if hasattr(world,"item_instances"):
            errors.extend(world.item_instances.validate())
        if hasattr(world,"equipment"):
            errors.extend(world.equipment.validate(world))
        return errors

    def public_inventory(self, inventory_id: str) -> list[dict]:
        inventory = self.actor_inventory(inventory_id)
        result = []
        for item_id in sorted(inventory.quantities):
            quantity = inventory.quantity(item_id)
            if quantity <= 0 or item_id not in self.catalog:
                continue
            item = self.catalog[item_id]
            result.append({**asdict(item), "quantity": quantity,
                           "instance_ids":list(inventory.instance_ids.get(item_id,[]))})
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
                amount=min(amount,desired-current)
                if hasattr(world,"item_instances"):
                    world.item_instances.add_new(world,shop.inventory_id,item_id,amount)
                else:
                    inventory.quantities[item_id] = current + amount
                changes[item_id] = inventory.quantity(item_id) - current
            if changes:
                world.ledger.emit(
                    day=world.day, phase="night_resolution", system="trade_system",
                    event_type="SHOP_RESTOCKED",
                    message=f"{shop.name} 完成日常补货。", scene_id=shop.scene_id,
                    actor_ids=[shop.keeper_id] if shop.keeper_id else [],
                    payload={"shop_id": shop.id, "changes": changes},
                )

    def _move_items(self,world,source_id,destination_id,item_id,quantity):
        if hasattr(world,"item_instances"):
            return world.item_instances.transfer(
                world,source_id,destination_id,item_id,quantity,
                change_legal_owner=True)
        source=self.inventories[source_id]; destination=self.inventories[destination_id]
        source.remove(item_id,quantity)
        destination.add(self.catalog[item_id],quantity,self.catalog)
        return []

    @staticmethod
    def _instance_state(world,*inventories):
        if not hasattr(world,"item_instances"):
            return None
        return ([deepcopy(inventory.instance_ids) for inventory in inventories],
                deepcopy(world.item_instances.instances))

    @staticmethod
    def _restore_instance_state(world,*args):
        if not hasattr(world,"item_instances"):
            return
        *inventories,state=args
        if state is None:
            return
        instance_ids,instances=state
        for inventory,saved in zip(inventories,instance_ids):
            inventory.instance_ids=saved
        world.item_instances.instances=instances


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
        if npc.sequence_pathway=="秘祈人" and npc.layer=="hostile_beyonder":
            # The demo's seeded secret ritual must start with a real, finite
            # recipe. Future attempts must acquire replacements through trade.
            inventories[npc.id].add(catalog["ritual_chalk"],1,catalog)
            inventories[npc.id].add(catalog["gray_ritual_powder"],1,catalog)
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
    "PROFESSIONAL_TRADER_LIMITS", "TradingSystem", "initialize_economy", "load_economy_content",
    "restock_essential_supplies",
]
