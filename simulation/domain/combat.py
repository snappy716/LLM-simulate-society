"""Validated values shared by combat preparation and the future card runtime."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Tuple


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


__all__ = [
    "COMBAT_ROWS", "DEPLOYMENT_STATES", "CombatDeploymentPolicy",
    "parse_combat_deployment_policy",
]
