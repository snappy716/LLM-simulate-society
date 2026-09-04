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
    interaction_reserved_phase_calls: int = 2
    interaction_phase_call_limit: int = 1
    interaction_dialogue_phase_call_limit: int = 1
    max_concurrent_requests: int = 1
    daily_estimated_token_limit: int = 24000
    max_output_tokens: int = 160
    request_timeout_seconds: float = 8.0
    cache_limit: int = 96
    # Kept only so snapshots made before schema migration can still be loaded.
    # Player-initiated dialogue is intentionally not governed by these values.
    player_dialogue_daily_reserve: int = 0
    player_dialogue_phase_call_limit: int = 0

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
            "interaction_dialogue_phase_call_limit": self.interaction_dialogue_phase_call_limit,
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
        if (
            self.interaction_dialogue_phase_call_limit < 1
            or self.interaction_phase_call_limit + self.interaction_dialogue_phase_call_limit
            > self.interaction_reserved_phase_calls
        ):
            raise ValueError("interaction choice and dialogue calls must fit inside the reserved phase budget")
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
            "interaction_dialogue_phase_call_limit": self.interaction_dialogue_phase_call_limit,
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


@dataclass(frozen=True)
class BoundedDialogueRequest:
    npc_id: str
    target_id: str
    candidate_revision: int
    day: int
    phase: str
    identity: Mapping[str, Any]
    state: Mapping[str, Any]
    relationship: Mapping[str, Any]
    recent_messages: Tuple[Mapping[str, Any], ...]
    incoming_text: str
    allowed_facts: Tuple[Mapping[str, Any], ...]
    dialogue_kind: str
    interaction_context: Mapping[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "npc_id": self.npc_id,
            "target_id": self.target_id,
            "candidate_revision": self.candidate_revision,
            "day": self.day,
            "phase": self.phase,
            "identity": dict(self.identity),
            "state": dict(self.state),
            "relationship": dict(self.relationship),
            "recent_messages": [dict(item) for item in self.recent_messages],
            "incoming_text": self.incoming_text,
            "allowed_facts": [dict(item) for item in self.allowed_facts],
            "dialogue_kind": self.dialogue_kind,
            "interaction_context": dict(self.interaction_context),
        }


@dataclass(frozen=True)
class BoundedDialogueResponse:
    npc_id: str
    target_id: str
    candidate_revision: int
    utterance: str
    fact_ids_used: Tuple[str, ...]

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "BoundedDialogueResponse":
        npc_id = payload.get("npc_id")
        target_id = payload.get("target_id")
        revision = payload.get("candidate_revision")
        utterance = payload.get("utterance")
        facts = payload.get("fact_ids_used", ())
        if not isinstance(npc_id, str) or not npc_id or not isinstance(target_id, str) or not target_id:
            raise ValueError("dialogue actor ids are required")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise ValueError("dialogue candidate_revision must be a positive integer")
        if not isinstance(utterance, str) or not utterance.strip() or len(utterance) > 160:
            raise ValueError("utterance must contain at most 160 characters")
        if (
            not isinstance(facts, (list, tuple))
            or any(not isinstance(fact_id, str) or not fact_id for fact_id in facts)
            or len(facts) != len(set(facts))
        ):
            raise ValueError("fact_ids_used must contain unique fact identifiers")
        return cls(npc_id, target_id, revision, utterance.strip(), tuple(facts))


__all__ = [
    "BoundedDecisionRequest", "BoundedDecisionResponse",
    "BoundedDialogueRequest", "BoundedDialogueResponse", "CognitionPolicy",
]
