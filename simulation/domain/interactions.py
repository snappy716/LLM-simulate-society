"""Interactable passages and their text-first action receipts."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional


@dataclass
class Passage:
    id: str
    name: str
    scene_a: str
    scene_b: str
    state: str
    allowed_methods: List[str]
    key_item_id: Optional[str] = None
    lock_difficulty: int = 0
    force_difficulty: int = 0
    climb_difficulty: int = 0
    force_noise: int = 0
    legal_risk: int = 0
    owner_id: Optional[str] = None
    authorized_actor_ids: List[str] = field(default_factory=list)
    authorized_occupations: List[str] = field(default_factory=list)
    condition: int = 100

    def other_scene(self,scene_id: str) -> Optional[str]:
        if scene_id==self.scene_a:
            return self.scene_b
        if scene_id==self.scene_b:
            return self.scene_a
        return None


@dataclass
class PassageActionReceipt:
    success: bool
    code: str
    message: str
    action_id: str
    actor_id: str
    passage_id: str
    item_id: str = ""
    instance_id: str = ""
    from_scene: str = ""
    to_scene: str = ""
    state_before: str = ""
    state_after: str = ""
    moved: bool = False
    check: Any = None
    consequences: Any = None
    event_id: Optional[str] = None


@dataclass
class IdentityCheckReceipt:
    success: bool
    code: str
    message: str
    actor_id: str
    inspector_id: str
    item_id: str
    instance_id: str = ""
    accepted: bool = False
    suspicion_delta: int = 0
    check: Any = None
    consequences: Any = None
    event_id: Optional[str] = None


@dataclass
class IntelRecordReceipt:
    success: bool
    code: str
    message: str
    actor_id: str
    fact_id: str
    item_id: str = "blank_notebook"
    instance_id: str = ""
    confidence_before: float = 0.0
    confidence_after: float = 0.0
    distortion_before: float = 0.0
    distortion_after: float = 0.0
    event_id: Optional[str] = None


@dataclass
class WeaponThreatReceipt:
    success: bool
    code: str
    message: str
    actor_id: str
    target_id: str
    item_id: str = ""
    instance_id: str = ""
    target_yielded: bool = False
    fear_delta: int = 0
    check: Any = None
    consequences: Any = None
    event_id: Optional[str] = None


@dataclass
class RitualActionReceipt:
    success: bool
    code: str
    message: str
    actor_id: str
    illegal: bool
    consumed_items: dict[str, int] = field(default_factory=dict)
    missing_items: dict[str, int] = field(default_factory=dict)
    material_bonus: int = 0
    ritual_succeeded: bool = False
    sanity_delta: int = 0
    legal_risk_delta: int = 0
    check: Any = None
    consequences: Any = None
    event_id: Optional[str] = None


__all__=[
    "IdentityCheckReceipt","IntelRecordReceipt","Passage","PassageActionReceipt",
    "RitualActionReceipt","WeaponThreatReceipt",
]
