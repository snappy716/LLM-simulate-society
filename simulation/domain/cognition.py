"""Serializable contracts for bounded NPC cognition and LLM choice."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple


@dataclass(frozen=True)
class CognitionPolicy:
    total_focus_slots: int = 20
    player_awakened_slots: int = 6
    candidate_limit: int = 5
    memory_limit_per_actor: int = 48
    persistent_memory_limit_per_actor: int = 8
    observation_limit_per_actor: int = 8
    reflection_memory_limit: int = 8
    daily_call_limit: int = 12
    phase_call_limit: int = 4
    interaction_reserved_phase_calls: int = 1
    interaction_phase_call_limit: int = 1
    max_concurrent_requests: int = 1
    daily_estimated_token_limit: int = 24000
    max_output_tokens: int = 160
    request_timeout_seconds: float = 8.0
    cache_limit: int = 96

    def __post_init__(self) -> None:
        integer_values = {
            "total_focus_slots": self.total_focus_slots,
            "player_awakened_slots": self.player_awakened_slots,
            "candidate_limit": self.candidate_limit,
            "memory_limit_per_actor": self.memory_limit_per_actor,
            "persistent_memory_limit_per_actor": self.persistent_memory_limit_per_actor,
            "observation_limit_per_actor": self.observation_limit_per_actor,
            "reflection_memory_limit": self.reflection_memory_limit,
            "daily_call_limit": self.daily_call_limit,
            "phase_call_limit": self.phase_call_limit,
            "interaction_reserved_phase_calls": self.interaction_reserved_phase_calls,
            "interaction_phase_call_limit": self.interaction_phase_call_limit,
            "max_concurrent_requests": self.max_concurrent_requests,
            "daily_estimated_token_limit": self.daily_estimated_token_limit,
            "max_output_tokens": self.max_output_tokens,
            "cache_limit": self.cache_limit,
        }
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in integer_values.values()):
            raise ValueError("cognition policy integer limits must be positive")
        if self.player_awakened_slots > self.total_focus_slots:
            raise ValueError("player awakened slots cannot exceed total focus slots")
        if not 1 <= self.interaction_phase_call_limit <= self.interaction_reserved_phase_calls <= self.phase_call_limit:
            raise ValueError("interaction calls must fit inside the reserved phase budget")
        if self.request_timeout_seconds <= 0:
            raise ValueError("cognition request timeout must be positive")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_focus_slots": self.total_focus_slots,
            "player_awakened_slots": self.player_awakened_slots,
            "candidate_limit": self.candidate_limit,
            "memory_limit_per_actor": self.memory_limit_per_actor,
            "persistent_memory_limit_per_actor": self.persistent_memory_limit_per_actor,
            "observation_limit_per_actor": self.observation_limit_per_actor,
            "reflection_memory_limit": self.reflection_memory_limit,
            "daily_call_limit": self.daily_call_limit,
            "phase_call_limit": self.phase_call_limit,
            "interaction_reserved_phase_calls": self.interaction_reserved_phase_calls,
            "interaction_phase_call_limit": self.interaction_phase_call_limit,
            "max_concurrent_requests": self.max_concurrent_requests,
            "daily_estimated_token_limit": self.daily_estimated_token_limit,
            "max_output_tokens": self.max_output_tokens,
            "request_timeout_seconds": self.request_timeout_seconds,
            "cache_limit": self.cache_limit,
        }


@dataclass(frozen=True)
class BoundedDecisionRequest:
    npc_id: str
    candidate_revision: int
    day: int
    phase: str
    identity: Mapping[str, Any]
    state: Mapping[str, Any]
    reflection: str
    memories: Tuple[Mapping[str, Any], ...]
    candidates: Tuple[Mapping[str, Any], ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "npc_id": self.npc_id,
            "candidate_revision": self.candidate_revision,
            "day": self.day,
            "phase": self.phase,
            "identity": dict(self.identity),
            "state": dict(self.state),
            "reflection": self.reflection,
            "memories": [dict(item) for item in self.memories],
            "candidates": [dict(item) for item in self.candidates],
        }


@dataclass(frozen=True)
class BoundedDecisionResponse:
    npc_id: str
    candidate_revision: int
    selected_action_id: Optional[str]
    reason: str

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "BoundedDecisionResponse":
        selected = payload.get("selected_action_id")
        if selected is not None and not isinstance(selected, str):
            raise ValueError("selected_action_id must be a string or null")
        npc_id = payload.get("npc_id")
        revision = payload.get("candidate_revision")
        reason = payload.get("reason")
        if not isinstance(npc_id, str) or not npc_id:
            raise ValueError("npc_id is required")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise ValueError("candidate_revision must be a positive integer")
        if not isinstance(reason, str) or len(reason) > 500:
            raise ValueError("reason must be a string of at most 500 characters")
        return cls(npc_id, revision, selected, reason)


__all__ = [
    "BoundedDecisionRequest", "BoundedDecisionResponse", "CognitionPolicy",
]
