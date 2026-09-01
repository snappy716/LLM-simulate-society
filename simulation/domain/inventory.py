"""Item, inventory, shop, and trade domain models.

The models intentionally stay small: the demo needs story-bearing ownership and
transactions, not randomized affixes or a complete market simulator.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class ItemDefinition:
    id: str
    name: str
    category: str
    description: str
    base_price: int
    weight: float = 0.0
    stack_limit: int = 1
    legality: str = "legal"
    tradeable: bool = True
    consumable: bool = False
    unique: bool = False
    tags: List[str] = field(default_factory=list)


@dataclass
class Inventory:
    owner_id: str
    max_weight: float = 30.0
    quantities: Dict[str, int] = field(default_factory=dict)

    def quantity(self, item_id: str) -> int:
        return max(0, int(self.quantities.get(item_id, 0)))

    def total_weight(self, catalog: Dict[str, ItemDefinition]) -> float:
        return round(sum(
            catalog[item_id].weight * quantity
            for item_id, quantity in self.quantities.items()
            if item_id in catalog and quantity > 0
        ), 4)

    def can_add(
        self,
        definition: ItemDefinition,
        quantity: int,
        catalog: Dict[str, ItemDefinition],
    ) -> bool:
        if quantity <= 0:
            return False
        # ``stack_limit`` is a UI/storage-stack hint. The domain inventory keeps
        # aggregate quantities, so only truly unique definitions are globally capped.
        if definition.unique and self.quantity(definition.id) + quantity > 1:
            return False
        return self.total_weight(catalog) + definition.weight * quantity <= self.max_weight + 1e-9

    def add(self, definition: ItemDefinition, quantity: int, catalog: Dict[str, ItemDefinition]) -> None:
        if not self.can_add(definition, quantity, catalog):
            raise ValueError(f"inventory cannot accept {quantity} x {definition.id}")
        self.quantities[definition.id] = self.quantity(definition.id) + quantity

    def remove(self, item_id: str, quantity: int) -> None:
        if quantity <= 0 or self.quantity(item_id) < quantity:
            raise ValueError(f"inventory lacks {quantity} x {item_id}")
        remaining = self.quantity(item_id) - quantity
        if remaining:
            self.quantities[item_id] = remaining
        else:
            self.quantities.pop(item_id, None)


@dataclass
class Shop:
    id: str
    name: str
    scene_id: str
    keeper_occupations: List[str]
    inventory_id: str
    cash: int
    buy_markup: float = 1.0
    sell_ratio: float = 0.5
    desired_stock: Dict[str, int] = field(default_factory=dict)
    open_phases: List[str] = field(default_factory=list)
    accepted_categories: List[str] = field(default_factory=list)
    accepted_legalities: List[str] = field(default_factory=lambda: ["legal"])
    keeper_id: Optional[str] = None
    tags: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class TradeQuote:
    direction: str
    actor_id: str
    shop_id: str
    item_id: str
    quantity: int
    unit_price: int
    total_price: int
    currency: str


@dataclass
class TradeReceipt:
    success: bool
    code: str
    message: str
    direction: str
    actor_id: str
    shop_id: str
    item_id: str
    quantity: int
    unit_price: int = 0
    total_price: int = 0
    actor_balance: int = 0
    shop_balance: int = 0
    event_id: Optional[str] = None


__all__ = [
    "Inventory", "ItemDefinition", "Shop", "TradeQuote", "TradeReceipt",
]
