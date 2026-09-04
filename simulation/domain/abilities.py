"""College abilities shared by surface checks and future card combat."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Tuple


CARD_TYPES = {
    "attack",
    "control",
    "defense",
    "knowledge",
    "signature",
    "support",
    "technique",
}
CARD_TARGETS = {"ally", "contextual", "enemy", "self_or_ally"}
CARD_RANGE_PATTERNS = {
    "any_ally",
    "any_enemy",
    "card_defined",
    "front_two_enemy_rows",
    "frontmost_enemy",
    "same_or_adjacent_ally",
}
ABILITY_SOURCE_KINDS = {"common", "specialization"}


@dataclass(frozen=True)
class CardBlueprint:
    card_id: str
    name: str
    source_ability_id: str
    actor_bound: bool
    card_type: str
    command_cost: int
    target: str
    range_pattern: str
    base_power: int
    effect_ids: Tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.card_id or not self.source_ability_id or not self.name:
            raise ValueError("card identifiers and name are required")
        if self.card_type not in CARD_TYPES:
            raise ValueError(f"unsupported card type: {self.card_type}")
        if self.target not in CARD_TARGETS:
            raise ValueError(f"unsupported card target: {self.target}")
        if self.range_pattern not in CARD_RANGE_PATTERNS:
            raise ValueError(f"unsupported card range pattern: {self.range_pattern}")
        if isinstance(self.command_cost, bool) or not isinstance(self.command_cost, int):
            raise ValueError("card command cost must be an integer")
        if not 0 <= self.command_cost <= 6:
            raise ValueError("card command cost must be between 0 and 6")
        if isinstance(self.base_power, bool) or not isinstance(self.base_power, int):
            raise ValueError("card base power must be an integer")
        if self.base_power < 0:
            raise ValueError("card base power cannot be negative")
        if not self.effect_ids:
            raise ValueError("card requires at least one effect")

    def to_state_dict(self) -> Dict[str, Any]:
        return {
            "card_id": self.card_id,
            "name": self.name,
            "source_ability_id": self.source_ability_id,
            "actor_bound": self.actor_bound,
            "card_type": self.card_type,
            "command_cost": self.command_cost,
            "target": self.target,
            "range_pattern": self.range_pattern,
            "base_power": self.base_power,
            "effect_ids": list(self.effect_ids),
        }


@dataclass(frozen=True)
class CampusAbilityDefinition:
    ability_id: str
    name: str
    college_id: str
    source_kind: str
    profile_id: str
    check_tags: Tuple[str, ...]
    surface_modifier: int
    card: CardBlueprint

    def __post_init__(self) -> None:
        if not self.ability_id or not self.name or not self.college_id or not self.profile_id:
            raise ValueError("ability identifiers and name are required")
        if self.source_kind not in ABILITY_SOURCE_KINDS:
            raise ValueError(f"unsupported ability source: {self.source_kind}")
        if not self.check_tags or any(not tag for tag in self.check_tags):
            raise ValueError("ability requires at least one check tag")
        if isinstance(self.surface_modifier, bool) or not isinstance(self.surface_modifier, int):
            raise ValueError("surface modifier must be an integer")
        if not 0 <= self.surface_modifier <= 10:
            raise ValueError("surface modifier must be between 0 and 10")
        if self.card.source_ability_id != self.ability_id:
            raise ValueError("card source must match its ability")

    def to_state_dict(self) -> Dict[str, Any]:
        return {
            "ability_id": self.ability_id,
            "name": self.name,
            "college_id": self.college_id,
            "source_kind": self.source_kind,
            "profile_id": self.profile_id,
            "check_tags": list(self.check_tags),
            "surface_modifier": self.surface_modifier,
            "card_id": self.card.card_id,
        }


__all__ = [
    "ABILITY_SOURCE_KINDS",
    "CARD_TARGETS",
    "CARD_RANGE_PATTERNS",
    "CARD_TYPES",
    "CampusAbilityDefinition",
    "CardBlueprint",
]
