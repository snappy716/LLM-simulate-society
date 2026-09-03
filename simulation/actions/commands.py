"""Versioned commands and results shared by player, rules, LLM, and narrative."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Tuple

from simulation.domain.events import SimulationEvent
from simulation.domain.entities import PHASES


class CommandSource(str, Enum):
    PLAYER = "player"
    RULE = "rule"
    LLM = "llm"
    NARRATIVE = "narrative"


@dataclass(frozen=True)
class SimulationCommand:
    command_id: str
    actor_id: str
    action_id: str
    expected_world_revision: int
    target_ids: Tuple[str, ...] = ()
    parameters: Dict[str, Any] = field(default_factory=dict)
    issued_day: int = 1
    issued_phase: str = "morning"
    issued_minute: int = 0
    source: str = CommandSource.PLAYER.value

    def __post_init__(self) -> None:
        if not self.command_id or not self.actor_id or not self.action_id:
            raise ValueError("command_id, actor_id, and action_id are required")
        if (
            isinstance(self.expected_world_revision, bool)
            or not isinstance(self.expected_world_revision, int)
            or self.expected_world_revision < 1
        ):
            raise ValueError("expected_world_revision must be >= 1")
        if self.source not in {item.value for item in CommandSource}:
            raise ValueError(f"unsupported command source: {self.source}")
        if (
            isinstance(self.issued_day, bool)
            or not isinstance(self.issued_day, int)
            or self.issued_day < 1
            or isinstance(self.issued_minute, bool)
            or not isinstance(self.issued_minute, int)
            or not 0 <= self.issued_minute <= 359
        ):
            raise ValueError("invalid issued clock")
        if self.issued_phase not in {phase.value for phase in PHASES}:
            raise ValueError(f"unsupported issued phase: {self.issued_phase}")
        if not isinstance(self.parameters, dict):
            raise ValueError("command parameters must be an object")
        if any(not isinstance(target_id, str) or not target_id for target_id in self.target_ids):
            raise ValueError("target_ids must contain non-empty strings")
        if len(set(self.target_ids)) != len(self.target_ids):
            raise ValueError("target_ids must be unique")
        object.__setattr__(self, "target_ids", tuple(self.target_ids))
        object.__setattr__(self, "parameters", deepcopy(self.parameters))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "command_id": self.command_id,
            "actor_id": self.actor_id,
            "action_id": self.action_id,
            "target_ids": list(self.target_ids),
            "parameters": deepcopy(self.parameters),
            "expected_world_revision": self.expected_world_revision,
            "issued_day": self.issued_day,
            "issued_phase": self.issued_phase,
            "issued_minute": self.issued_minute,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "SimulationCommand":
        data = deepcopy(payload)
        data["target_ids"] = tuple(data.get("target_ids", ()))
        return cls(**data)

    def fingerprint(self) -> str:
        canonical = json.dumps(
            self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()


@dataclass(frozen=True)
class CommandResult:
    command_id: str
    accepted: bool
    performed: bool
    success: bool
    code: str
    message: str
    world_revision: int
    events: Tuple[SimulationEvent, ...] = ()
    payload: Dict[str, Any] = field(default_factory=dict)
    replayed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "events", tuple(self.events))
        object.__setattr__(self, "payload", deepcopy(self.payload))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "command_id": self.command_id,
            "accepted": self.accepted,
            "performed": self.performed,
            "success": self.success,
            "code": self.code,
            "message": self.message,
            "world_revision": self.world_revision,
            "events": [event.to_dict() for event in self.events],
            "payload": deepcopy(self.payload),
            "replayed": self.replayed,
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "CommandResult":
        data = deepcopy(payload)
        data["events"] = tuple(SimulationEvent.from_dict(item) for item in data.get("events", ()))
        return cls(**data)


__all__ = ["CommandResult", "CommandSource", "SimulationCommand"]
