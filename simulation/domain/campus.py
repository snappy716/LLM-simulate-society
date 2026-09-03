"""Campus-demo domain values that do not depend on Godot or an LLM provider.

These types form the target model for the gradual migration away from legacy
town-specific fields.  They are intentionally side-by-side with ``NPC`` so the
existing playable prototype remains stable while systems migrate one at a time.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Dict, List, Optional


ATTRIBUTE_NAMES = ("physique", "dexterity", "focus", "insight", "empathy", "expression")
PERSONALITY_NAMES = (
    "extraversion", "agreeableness", "conscientiousness", "openness",
    "emotional_sensitivity", "risk_tolerance", "rule_alignment", "altruism",
)
RELATIONSHIP_NAMES = (
    "familiarity", "trust", "closeness", "respect",
    "suspicion", "fear", "obligation", "conflict",
)


def _validate_range(values: Dict[str, int], names: tuple[str, ...], low: int, high: int) -> None:
    missing = set(names) - set(values)
    extra = set(values) - set(names)
    if missing or extra:
        raise ValueError(f"invalid keys; missing={sorted(missing)}, extra={sorted(extra)}")
    for name, value in values.items():
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise ValueError(f"{name} must be an integer between {low} and {high}")


@dataclass(frozen=True)
class BaseAttributes:
    physique: int = 5
    dexterity: int = 5
    focus: int = 5
    insight: int = 5
    empathy: int = 5
    expression: int = 5

    def __post_init__(self) -> None:
        _validate_range(asdict(self), ATTRIBUTE_NAMES, 1, 10)


@dataclass(frozen=True)
class PersonalityTraits:
    extraversion: int = 50
    agreeableness: int = 50
    conscientiousness: int = 50
    openness: int = 50
    emotional_sensitivity: int = 50
    risk_tolerance: int = 50
    rule_alignment: int = 50
    altruism: int = 50

    def __post_init__(self) -> None:
        _validate_range(asdict(self), PERSONALITY_NAMES, 0, 100)


@dataclass
class RelationshipDimensions:
    familiarity: int = 0
    trust: int = 50
    closeness: int = 0
    respect: int = 0
    suspicion: int = 0
    fear: int = 0
    obligation: int = 0
    conflict: int = 0

    def __post_init__(self) -> None:
        _validate_range(asdict(self), RELATIONSHIP_NAMES, 0, 100)


@dataclass
class NeedState:
    rest: int = 0
    food: int = 0
    safety: int = 0
    social: int = 0
    money: int = 0
    achievement: int = 0
    curiosity: int = 0
    commitment_pressure: int = 0

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
                raise ValueError(f"{name} must be an integer between 0 and 100")


@dataclass
class EmotionState:
    joy: int = 0
    fear: int = 0
    anger: int = 0
    sadness: int = 0
    shame: int = 0

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
                raise ValueError(f"{name} must be an integer between 0 and 100")


@dataclass(frozen=True)
class DerivedStats:
    max_health: int
    max_focus: int
    stability_threshold: int
    speed: int
    physical_power: int
    technique_power: int
    cognitive_power: int
    support_power: int
    defense: float


def derive_stats(
    attributes: BaseAttributes,
    *,
    identity_anchor_count: int = 0,
    equipment: Optional[Dict[str, float]] = None,
) -> DerivedStats:
    """Apply the documented first-pass formulas without random turn-order noise."""
    if identity_anchor_count < 0:
        raise ValueError("identity_anchor_count cannot be negative")
    bonus = equipment or {}
    return DerivedStats(
        max_health=round(60 + attributes.physique * 8 + bonus.get("max_health", 0)),
        max_focus=round(35 + attributes.focus * 5 + attributes.insight * 2 + bonus.get("max_focus", 0)),
        stability_threshold=round(
            40 + attributes.focus * 4 + identity_anchor_count * 5 + bonus.get("stability", 0)
        ),
        speed=round(attributes.dexterity * 2 + attributes.insight + bonus.get("speed", 0)),
        physical_power=round(
            attributes.physique * 2 + attributes.dexterity + bonus.get("weapon_power", 0)
        ),
        technique_power=round(
            attributes.dexterity * 2 + attributes.insight + bonus.get("tool_power", 0)
        ),
        cognitive_power=round(
            attributes.insight * 2 + attributes.focus + bonus.get("knowledge_power", 0)
        ),
        support_power=round(
            attributes.empathy * 2 + attributes.expression + bonus.get("professional_power", 0)
        ),
        defense=round(
            attributes.physique * 1.2 + attributes.dexterity * 0.5 + bonus.get("armor", 0), 2
        ),
    )


class SimulationTier(str, Enum):
    BACKGROUND = "background"
    PERSISTENT = "persistent"
    FOCUSED = "focused"


class NightAccess(str, Enum):
    UNAWARE = "unaware"
    SENSITIVE = "sensitive"
    CAPABLE = "capable"
    WILLING = "willing"


@dataclass
class CampusNPCProfile:
    npc_id: str
    college_id: Optional[str]
    occupation_id: str
    attributes: BaseAttributes
    personality: PersonalityTraits
    needs: NeedState = field(default_factory=NeedState)
    emotions: EmotionState = field(default_factory=EmotionState)
    simulation_tier: SimulationTier = SimulationTier.PERSISTENT
    night_access: NightAccess = NightAccess.UNAWARE
    specialization_id: Optional[str] = None
    club_ids: List[str] = field(default_factory=list)
    personal_trait_id: Optional[str] = None
    relationship_skill_ids: List[str] = field(default_factory=list)
    lost_imprint_skill_id: Optional[str] = None
    core_values: List[str] = field(default_factory=list)
    moral_boundaries: List[str] = field(default_factory=list)
    fear_id: Optional[str] = None
    obsession_id: Optional[str] = None
    identity_anchor_ids: List[str] = field(default_factory=list)
    awakened_by_player: bool = False

    def __post_init__(self) -> None:
        if not self.npc_id:
            raise ValueError("npc_id is required")
        if len(self.core_values) > 3:
            raise ValueError("at most three ordered core values are allowed")
        if self.awakened_by_player and self.simulation_tier != SimulationTier.FOCUSED:
            raise ValueError("a player-awakened NPC must remain in the focused tier")


__all__ = [
    "ATTRIBUTE_NAMES", "PERSONALITY_NAMES", "RELATIONSHIP_NAMES",
    "BaseAttributes", "PersonalityTraits", "RelationshipDimensions",
    "NeedState", "EmotionState", "DerivedStats", "derive_stats",
    "SimulationTier", "NightAccess", "CampusNPCProfile",
]
