"""Validated policy values for persistent campus parties."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Dict, Mapping


@dataclass(frozen=True)
class CampusPartyPolicy:
    max_members: int
    invitation_score_threshold: int
    withdrawal_score_threshold: int
    minimum_commitment_days: int
    same_college_bonus: int
    shared_club_bonus: int
    night_access_modifiers: Mapping[str, int]
    relationship_skills: Mapping[str, Mapping[str, Any]]

    def __post_init__(self) -> None:
        for name in (
            "max_members", "invitation_score_threshold", "withdrawal_score_threshold",
            "minimum_commitment_days", "same_college_bonus", "shared_club_bonus",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"party policy {name} must be a non-negative integer")
        if self.max_members < 2:
            raise ValueError("party max_members must include a leader and companion")
        if set(self.night_access_modifiers) != {"unaware", "sensitive", "capable", "willing"}:
            raise ValueError("party policy requires all night access modifiers")
        if not self.relationship_skills:
            raise ValueError("party policy requires relationship skill definitions")
        for skill_id, definition in self.relationship_skills.items():
            if not skill_id or not isinstance(definition, Mapping):
                raise ValueError("party relationship skills must be named mappings")
            if not definition.get("name") or not definition.get("description"):
                raise ValueError(f"party relationship skill {skill_id} requires display text")
            bonus = definition.get("stability_bonus")
            if isinstance(bonus, bool) or not isinstance(bonus, int) or bonus < 0:
                raise ValueError(f"party relationship skill {skill_id} has invalid stability bonus")
            effect = definition.get("battle_effect")
            if not isinstance(effect, Mapping) or not effect.get("effect_id"):
                raise ValueError(f"party relationship skill {skill_id} requires a battle effect")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_members": self.max_members,
            "invitation_score_threshold": self.invitation_score_threshold,
            "withdrawal_score_threshold": self.withdrawal_score_threshold,
            "minimum_commitment_days": self.minimum_commitment_days,
            "same_college_bonus": self.same_college_bonus,
            "shared_club_bonus": self.shared_club_bonus,
            "night_access_modifiers": dict(self.night_access_modifiers),
            "relationship_skills": deepcopy(dict(self.relationship_skills)),
        }


def parse_party_policy(document: Mapping[str, Any]) -> CampusPartyPolicy:
    return CampusPartyPolicy(
        max_members=int(document.get("max_members", 3)),
        invitation_score_threshold=int(document.get("invitation_score_threshold", 38)),
        withdrawal_score_threshold=int(document.get("withdrawal_score_threshold", 25)),
        minimum_commitment_days=int(document.get("minimum_commitment_days", 1)),
        same_college_bonus=int(document.get("same_college_bonus", 5)),
        shared_club_bonus=int(document.get("shared_club_bonus", 8)),
        night_access_modifiers=dict(document.get("night_access_modifiers", {})),
        relationship_skills=deepcopy(dict(document.get("relationship_skills", {}))),
    )


__all__ = ["CampusPartyPolicy", "parse_party_policy"]
