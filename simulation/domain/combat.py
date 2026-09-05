"""Validated values shared by combat preparation and the future card runtime."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Tuple

from simulation.domain.abilities import CardBlueprint


COMBAT_ROWS = ("front", "middle", "back")
DEPLOYMENT_STATES = {"reserve", "deployed", "incapacitated", "withdrawn"}


@dataclass(frozen=True)
class CombatDeploymentPolicy:
    max_friendly_characters: int
    row_capacity: int
    allowed_rows: Tuple[str, ...]
    setup_phases: Tuple[str, ...]
    required_world_layer: str
    reposition_command_cost: int
    fear_limit: int
    injury_limit: int
    pollution_limit: int
    base_commands: Mapping[str, str]
    fallback_command_card_id: str
    preferred_row_weights: Mapping[str, Mapping[str, int]]

    def __post_init__(self) -> None:
        if self.max_friendly_characters != 3:
            raise ValueError("demo combat preparation requires exactly three friendly slots")
        if not 1 <= self.row_capacity <= 2:
            raise ValueError("combat row capacity must be one or two")
        if self.allowed_rows != COMBAT_ROWS:
            raise ValueError("combat rows must be front, middle, back in order")
        if not self.setup_phases or any(
            phase not in {"evening", "late_night"} for phase in self.setup_phases
        ):
            raise ValueError("combat setup phases must be evening or late_night")
        if self.required_world_layer != "night":
            raise ValueError("campus demo combat preparation belongs to the night layer")
        if not 0 <= self.reposition_command_cost <= 6:
            raise ValueError("combat reposition cost must be between zero and six")
        for name, value in (
            ("fear", self.fear_limit),
            ("injury", self.injury_limit),
            ("pollution", self.pollution_limit),
        ):
            if not 1 <= value <= 100:
                raise ValueError(f"combat {name} limit must be between one and one hundred")
        if set(self.base_commands) != set(COMBAT_ROWS) or any(
            not isinstance(value, str) or not value for value in self.base_commands.values()
        ):
            raise ValueError("each combat row requires one base command")
        if not self.fallback_command_card_id:
            raise ValueError("combat fallback command card is required")
        if set(self.preferred_row_weights) != set(COMBAT_ROWS):
            raise ValueError("each combat row requires preferred-row weights")
        for row, weights in self.preferred_row_weights.items():
            if not weights or any(
                not isinstance(name, str)
                or not name
                or isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
                for name, value in weights.items()
            ):
                raise ValueError(f"combat preferred-row weights are invalid for {row}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_friendly_characters": self.max_friendly_characters,
            "row_capacity": self.row_capacity,
            "allowed_rows": list(self.allowed_rows),
            "setup_phases": list(self.setup_phases),
            "required_world_layer": self.required_world_layer,
            "reposition_command_cost": self.reposition_command_cost,
            "readiness_limits": {
                "fear": self.fear_limit,
                "injury": self.injury_limit,
                "pollution": self.pollution_limit,
            },
            "base_commands": dict(self.base_commands),
            "fallback_command_card_id": self.fallback_command_card_id,
            "preferred_row_weights": deepcopy(dict(self.preferred_row_weights)),
        }


@dataclass(frozen=True)
class CombatRoundPolicy:
    deck_size_per_actor: int
    cards_drawn_per_actor: int
    initial_command_points: int
    command_point_growth_per_round: int
    maximum_command_points: int
    required_generic_card_ids: Tuple[str, ...]
    fallback_card_id: str
    generic_card_blueprints: Mapping[str, Mapping[str, Any]]
    base_command_blueprints: Mapping[str, Mapping[str, Any]]

    def __post_init__(self) -> None:
        if self.deck_size_per_actor != 8:
            raise ValueError("demo combat requires eight cards per actor deck")
        if self.cards_drawn_per_actor != 2:
            raise ValueError("demo combat requires two cards drawn per deployed actor")
        if not 1 <= self.initial_command_points <= self.maximum_command_points <= 6:
            raise ValueError("combat command point limits are invalid")
        if self.command_point_growth_per_round != 1:
            raise ValueError("demo combat command points must grow by one per round")
        if not self.required_generic_card_ids or len(set(self.required_generic_card_ids)) != len(
            self.required_generic_card_ids
        ):
            raise ValueError("required generic combat cards must be unique")
        if self.fallback_card_id not in self.generic_card_blueprints:
            raise ValueError("combat fallback card needs a generic blueprint")
        if not set(self.required_generic_card_ids).issubset(self.generic_card_blueprints):
            raise ValueError("required generic combat card blueprint is missing")
        required_types = {
            str(self.generic_card_blueprints[card_id].get("card_type", ""))
            for card_id in self.required_generic_card_ids
        }
        if "defense" not in required_types:
            raise ValueError("required generic combat cards must guarantee defense")
        if not required_types.intersection({"defense", "support", "control", "knowledge"}):
            raise ValueError("required generic combat cards must guarantee a non-damage option")
        for card_id, payload in self.generic_card_blueprints.items():
            if card_id != payload.get("card_id"):
                raise ValueError(f"generic combat card id mismatch: {card_id}")
            CardBlueprint(
                card_id=str(payload.get("card_id", "")),
                name=str(payload.get("name", "")),
                source_ability_id=str(payload.get("source_ability_id", "")),
                actor_bound=bool(payload.get("actor_bound", False)),
                card_type=str(payload.get("card_type", "")),
                command_cost=int(payload.get("command_cost", -1)),
                target=str(payload.get("target", "")),
                range_pattern=str(payload.get("range_pattern", "")),
                base_power=int(payload.get("base_power", -1)),
                effect_ids=tuple(map(str, payload.get("effect_ids", ()))),
            )
            if payload.get("actor_bound") is not True:
                raise ValueError("generic combat cards must remain actor-bound")
        if set(self.base_command_blueprints) != {
            "basic_guard", "basic_coordinate", "basic_observe",
        }:
            raise ValueError("combat requires guard, coordinate, and observe base commands")
        for card_id, payload in self.base_command_blueprints.items():
            if card_id != payload.get("card_id"):
                raise ValueError(f"base combat command id mismatch: {card_id}")
            CardBlueprint(
                card_id=str(payload.get("card_id", "")),
                name=str(payload.get("name", "")),
                source_ability_id=str(payload.get("source_ability_id", "")),
                actor_bound=bool(payload.get("actor_bound", False)),
                card_type=str(payload.get("card_type", "")),
                command_cost=int(payload.get("command_cost", -1)),
                target=str(payload.get("target", "")),
                range_pattern=str(payload.get("range_pattern", "")),
                base_power=int(payload.get("base_power", -1)),
                effect_ids=tuple(map(str, payload.get("effect_ids", ()))),
            )
            if payload.get("actor_bound") is not True:
                raise ValueError("base combat commands must remain actor-bound")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "deck_size_per_actor": self.deck_size_per_actor,
            "cards_drawn_per_actor": self.cards_drawn_per_actor,
            "initial_command_points": self.initial_command_points,
            "command_point_growth_per_round": self.command_point_growth_per_round,
            "maximum_command_points": self.maximum_command_points,
            "required_generic_card_ids": list(self.required_generic_card_ids),
            "fallback_card_id": self.fallback_card_id,
            "generic_card_blueprints": [
                deepcopy(dict(self.generic_card_blueprints[card_id]))
                for card_id in sorted(self.generic_card_blueprints)
            ],
            "base_command_blueprints": [
                deepcopy(dict(self.base_command_blueprints[card_id]))
                for card_id in sorted(self.base_command_blueprints)
            ],
        }


def parse_combat_deployment_policy(payload: Mapping[str, Any]) -> CombatDeploymentPolicy:
    limits = payload.get("readiness_limits", {})
    return CombatDeploymentPolicy(
        max_friendly_characters=int(payload.get("max_friendly_characters", 0)),
        row_capacity=int(payload.get("row_capacity", 0)),
        allowed_rows=tuple(map(str, payload.get("allowed_rows", ()))),
        setup_phases=tuple(map(str, payload.get("setup_phases", ()))),
        required_world_layer=str(payload.get("required_world_layer", "")),
        reposition_command_cost=int(payload.get("reposition_command_cost", -1)),
        fear_limit=int(limits.get("fear", 0)),
        injury_limit=int(limits.get("injury", 0)),
        pollution_limit=int(limits.get("pollution", 0)),
        base_commands=deepcopy(dict(payload.get("base_commands", {}))),
        fallback_command_card_id=str(payload.get("fallback_command_card_id", "")),
        preferred_row_weights=deepcopy(dict(payload.get("preferred_row_weights", {}))),
    )


def parse_combat_round_policy(payload: Mapping[str, Any]) -> CombatRoundPolicy:
    blueprints: Dict[str, Dict[str, Any]] = {}
    for value in payload.get("generic_card_blueprints", ()):
        if not isinstance(value, Mapping):
            raise ValueError("generic combat card blueprint must be a mapping")
        card_id = str(value.get("card_id", ""))
        if not card_id or card_id in blueprints:
            raise ValueError("generic combat card ids must be present and unique")
        blueprints[card_id] = deepcopy(dict(value))
    base_commands: Dict[str, Dict[str, Any]] = {}
    for value in payload.get("base_command_blueprints", ()):
        if not isinstance(value, Mapping):
            raise ValueError("base combat command blueprint must be a mapping")
        card_id = str(value.get("card_id", ""))
        if not card_id or card_id in base_commands:
            raise ValueError("base combat command ids must be present and unique")
        base_commands[card_id] = deepcopy(dict(value))
    return CombatRoundPolicy(
        deck_size_per_actor=int(payload.get("deck_size_per_actor", 0)),
        cards_drawn_per_actor=int(payload.get("cards_drawn_per_actor", 0)),
        initial_command_points=int(payload.get("initial_command_points", 0)),
        command_point_growth_per_round=int(payload.get("command_point_growth_per_round", 0)),
        maximum_command_points=int(payload.get("maximum_command_points", 0)),
        required_generic_card_ids=tuple(map(str, payload.get("required_generic_card_ids", ()))),
        fallback_card_id=str(payload.get("fallback_card_id", "")),
        generic_card_blueprints=blueprints,
        base_command_blueprints=base_commands,
    )


__all__ = [
    "COMBAT_ROWS", "DEPLOYMENT_STATES", "CombatDeploymentPolicy", "CombatRoundPolicy",
    "parse_combat_deployment_policy", "parse_combat_round_policy",
]
