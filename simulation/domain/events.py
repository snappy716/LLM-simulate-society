"""Committed simulation facts emitted by the authoritative kernel."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Optional, Tuple


@dataclass(frozen=True)
class EventDraft:
    event_type: str
    public_summary: str
    actor_ids: Tuple[str, ...] = ()
    target_ids: Tuple[str, ...] = ()
    scene_id: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)
    visibility: str = "public"
    severity: int = 1
    knowledge_tags: Tuple[str, ...] = ()
    causation_id: Optional[str] = None
    correlation_id: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.event_type:
            raise ValueError("event_type is required")
        if not self.public_summary:
            raise ValueError("public_summary is required")
        if not 0 <= self.severity <= 10:
            raise ValueError("event severity must be between 0 and 10")
        object.__setattr__(self, "actor_ids", tuple(self.actor_ids))
        object.__setattr__(self, "target_ids", tuple(self.target_ids))
        object.__setattr__(self, "knowledge_tags", tuple(self.knowledge_tags))
        object.__setattr__(self, "payload", deepcopy(self.payload))


@dataclass(frozen=True)
class SimulationEvent:
    event_id: str
    event_type: str
    day: int
    phase: str
    minute: int
    world_revision: int
    command_id: str
    public_summary: str
    actor_ids: Tuple[str, ...] = ()
    target_ids: Tuple[str, ...] = ()
    scene_id: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)
    visibility: str = "public"
    severity: int = 1
    knowledge_tags: Tuple[str, ...] = ()
    causation_id: Optional[str] = None
    correlation_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "day": self.day,
            "phase": self.phase,
            "minute": self.minute,
            "world_revision": self.world_revision,
            "command_id": self.command_id,
            "public_summary": self.public_summary,
            # ``message`` keeps the current Godot event projection compatible.
            "message": self.public_summary,
            "actor_ids": list(self.actor_ids),
            "target_ids": list(self.target_ids),
            "scene_id": self.scene_id,
            "payload": deepcopy(self.payload),
            "visibility": self.visibility,
            "severity": self.severity,
            "knowledge_tags": list(self.knowledge_tags),
            "causation_id": self.causation_id,
            "correlation_id": self.correlation_id,
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "SimulationEvent":
        data = deepcopy(payload)
        data.pop("message", None)
        for name in ("actor_ids", "target_ids", "knowledge_tags"):
            data[name] = tuple(data.get(name, ()))
        return cls(**data)


def event_dicts(events: Iterable[SimulationEvent]) -> list[Dict[str, Any]]:
    return [event.to_dict() for event in events]


__all__ = ["EventDraft", "SimulationEvent", "event_dicts"]
