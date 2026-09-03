"""Data-driven campus activities shared by players, rules, and future LLM plans."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Tuple

from simulation.domain.entities import PHASES


NEED_NAMES = (
    "rest", "food", "safety", "social", "money", "achievement",
    "curiosity", "commitment_pressure",
)
EMOTION_NAMES = ("joy", "fear", "anger", "sadness", "shame")
ACTIVITY_CATEGORIES = {"study", "research", "social", "club", "exploration", "personal", "work", "rest"}


def _integer_deltas(
    payload: Mapping[str, Any],
    *,
    allowed: Tuple[str, ...],
    field_name: str,
) -> Dict[str, int]:
    unknown = set(payload) - set(allowed)
    if unknown:
        raise ValueError(f"{field_name} contains unknown keys: {sorted(unknown)}")
    result: Dict[str, int] = {}
    for key, value in payload.items():
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{field_name}.{key} must be an integer")
        result[key] = value
    return result


@dataclass(frozen=True)
class CampusActivityDefinition:
    activity_id: str
    profile_id: str
    category: str
    action_class: str
    allowed_phases: Tuple[str, ...]
    need_deltas: Dict[str, int]
    emotion_deltas: Dict[str, int]
    knowledge_topic: str
    knowledge_gain: int
    wealth_delta: int

    def __post_init__(self) -> None:
        if not self.activity_id or not self.profile_id:
            raise ValueError("activity_id and profile_id are required")
        if self.category not in ACTIVITY_CATEGORIES:
            raise ValueError(f"unsupported campus activity category: {self.category}")
        if self.action_class not in {"major", "free"}:
            raise ValueError(f"unsupported campus activity action class: {self.action_class}")
        valid_phases = {phase.value for phase in PHASES}
        if not self.allowed_phases or not set(self.allowed_phases).issubset(valid_phases):
            raise ValueError(f"invalid allowed phases for {self.activity_id}")
        if len(set(self.allowed_phases)) != len(self.allowed_phases):
            raise ValueError(f"duplicate allowed phase for {self.activity_id}")
        _integer_deltas(self.need_deltas, allowed=NEED_NAMES, field_name="need_deltas")
        _integer_deltas(self.emotion_deltas, allowed=EMOTION_NAMES, field_name="emotion_deltas")
        if isinstance(self.knowledge_gain, bool) or not isinstance(self.knowledge_gain, int):
            raise ValueError("knowledge_gain must be an integer")
        if self.knowledge_gain < 0 or (self.knowledge_gain > 0 and not self.knowledge_topic):
            raise ValueError("positive knowledge gain requires a topic")
        if isinstance(self.wealth_delta, bool) or not isinstance(self.wealth_delta, int):
            raise ValueError("wealth_delta must be an integer")


def parse_activity_definition(
    payload: Mapping[str, Any],
    profiles: Mapping[str, Mapping[str, Any]],
) -> CampusActivityDefinition:
    profile_id = str(payload.get("profile_id", ""))
    if profile_id not in profiles:
        raise ValueError(f"unknown campus activity profile: {profile_id}")
    profile = profiles[profile_id]
    return CampusActivityDefinition(
        activity_id=str(payload.get("id", "")),
        profile_id=profile_id,
        category=str(profile.get("category", "")),
        action_class=str(payload.get("action_class", "")),
        allowed_phases=tuple(str(value) for value in payload.get("allowed_phases", ())),
        need_deltas=_integer_deltas(
            profile.get("need_deltas", {}), allowed=NEED_NAMES, field_name="need_deltas"
        ),
        emotion_deltas=_integer_deltas(
            profile.get("emotion_deltas", {}), allowed=EMOTION_NAMES,
            field_name="emotion_deltas",
        ),
        knowledge_topic=str(profile.get("knowledge_topic", "")),
        knowledge_gain=int(profile.get("knowledge_gain", 0)),
        wealth_delta=int(profile.get("wealth_delta", 0)),
    )


__all__ = [
    "ACTIVITY_CATEGORIES",
    "EMOTION_NAMES",
    "NEED_NAMES",
    "CampusActivityDefinition",
    "parse_activity_definition",
]
