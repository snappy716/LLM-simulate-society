"""Structured, replayable facts about an actor's lived history."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Tuple


CHRONICLE_CATEGORIES = {
    "routine", "social", "task", "trade", "organization",
    "injury", "night", "combat", "discovery", "story",
}
CHRONICLE_VISIBILITIES = {"public", "observable", "private", "secret"}
CHRONICLE_PHASES = {"morning", "afternoon", "evening", "late_night"}


@dataclass(frozen=True)
class NpcChronicleEntry:
    entry_id: str
    actor_id: str
    day: int
    phase: str
    minute: int
    category: str
    event_type: str
    scene_id: str | None
    related_actor_ids: Tuple[str, ...] = ()
    importance: int = 0
    outcome: str = "completed"
    visibility: str = "private"
    summary_key: str = "event_recorded"
    parameters: Dict[str, Any] = field(default_factory=dict)
    source_event_ids: Tuple[str, ...] = ()
    knowledge_tags: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.entry_id or not self.actor_id:
            raise ValueError("chronicle entry and actor IDs are required")
        if isinstance(self.day, bool) or not isinstance(self.day, int) or self.day < 1:
            raise ValueError("chronicle day must be an integer >= 1")
        if isinstance(self.minute, bool) or not isinstance(self.minute, int) or not 0 <= self.minute <= 359:
            raise ValueError("chronicle minute must be between 0 and 359")
        if self.phase not in CHRONICLE_PHASES:
            raise ValueError(f"unsupported chronicle phase: {self.phase}")
        if self.category not in CHRONICLE_CATEGORIES:
            raise ValueError(f"unsupported chronicle category: {self.category}")
        if self.visibility not in CHRONICLE_VISIBILITIES:
            raise ValueError(f"unsupported chronicle visibility: {self.visibility}")
        if isinstance(self.importance, bool) or not isinstance(self.importance, int) or not 0 <= self.importance <= 5:
            raise ValueError("chronicle importance must be between 0 and 5")
        if not self.event_type or not self.summary_key or not self.source_event_ids:
            raise ValueError("chronicle event type, summary key, and source events are required")
        object.__setattr__(self, "related_actor_ids", tuple(dict.fromkeys(self.related_actor_ids)))
        object.__setattr__(self, "source_event_ids", tuple(dict.fromkeys(self.source_event_ids)))
        object.__setattr__(self, "knowledge_tags", tuple(dict.fromkeys(self.knowledge_tags)))
        object.__setattr__(self, "parameters", deepcopy(self.parameters))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entry_id": self.entry_id, "actor_id": self.actor_id,
            "day": self.day, "phase": self.phase, "minute": self.minute,
            "category": self.category, "event_type": self.event_type,
            "scene_id": self.scene_id,
            "related_actor_ids": list(self.related_actor_ids),
            "importance": self.importance, "outcome": self.outcome,
            "visibility": self.visibility, "summary_key": self.summary_key,
            "parameters": deepcopy(self.parameters),
            "source_event_ids": list(self.source_event_ids),
            "knowledge_tags": list(self.knowledge_tags),
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "NpcChronicleEntry":
        # ``__post_init__`` already makes the mutable parameters defensive.
        # Avoid a second full copy when validating large saved chronicles.
        data = dict(payload)
        for name in ("related_actor_ids", "source_event_ids", "knowledge_tags"):
            data[name] = tuple(data.get(name, ()))
        return cls(**data)


def chronicle_dicts(entries: Iterable[NpcChronicleEntry]) -> list[Dict[str, Any]]:
    return [entry.to_dict() for entry in entries]


__all__ = ["CHRONICLE_CATEGORIES", "CHRONICLE_PHASES", "CHRONICLE_VISIBILITIES", "NpcChronicleEntry", "chronicle_dicts"]
