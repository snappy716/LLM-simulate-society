"""Domain contracts for deterministic item use."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class ItemUseDefinition:
    item_id: str
    mode: str
    consumes: bool = False
    required_scenes: List[str] = field(default_factory=list)
    state_effects: Dict[str, int] = field(default_factory=dict)
    attribute_effects: Dict[str, int] = field(default_factory=dict)
    grants_effects: Dict[str, int] = field(default_factory=dict)
    duration_phases: int = 0
    effect_charges: int = 0
    knowledge: str = ""
    protected_occupations: List[str] = field(default_factory=list)
    blocked_reason: str = ""


@dataclass
class ItemUseReceipt:
    success: bool
    code: str
    message: str
    actor_id: str
    item_id: str
    mode: str = ""
    consumed: bool = False
    equipped: bool = False
    state_changes: Dict[str, int] = field(default_factory=dict)
    granted_effects: Dict[str, int] = field(default_factory=dict)
    knowledge_added: Optional[str] = None
    event_id: Optional[str] = None


@dataclass
class ActiveItemEffect:
    id: str
    actor_id: str
    effect: str
    value: int
    source_item_id: str
    source_instance_id: Optional[str]
    started_at: int
    expires_at: Optional[int] = None
    remaining_uses: int = 0
    requires_equipped: bool = False


@dataclass
class EquipmentReceipt:
    success: bool
    code: str
    message: str
    action_id: str
    actor_id: str
    item_id: str = ""
    instance_id: str = ""
    slot: str = ""
    state_changes: Dict[str, int] = field(default_factory=dict)
    granted_effects: Dict[str, int] = field(default_factory=dict)
    event_id: Optional[str] = None


__all__ = ["ActiveItemEffect","EquipmentReceipt","ItemUseDefinition", "ItemUseReceipt"]
