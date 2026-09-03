"""Provider-independent scoring for autonomous NPC choices.

All inputs are normalized to 0..100.  The scorer only ranks already-legal
candidate actions; validation and state mutation remain responsibilities of the
action and transaction systems.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from simulation.domain.campus import PersonalityTraits


def _bounded(value: float) -> float:
    return max(0.0, min(100.0, float(value)))


@dataclass(frozen=True)
class DecisionFactors:
    goal_progress: float = 0
    need_satisfaction: float = 0
    value_alignment: float = 0
    relationship_pull: float = 0
    commitment_pull: float = 0
    habit_pull: float = 0
    curiosity: float = 0
    prosocial_value: float = 0
    risk: float = 0
    money_cost: float = 0
    time_cost: float = 0
    illegality: float = 0
    moral_conflict: float = 0
    opportunity_cost: float = 0
    fear_pressure: float = 0
    anger_pressure: float = 0

    def __post_init__(self) -> None:
        for name, value in self.__dict__.items():
            if not 0 <= value <= 100:
                raise ValueError(f"{name} must be between 0 and 100")


@dataclass(frozen=True)
class DecisionScore:
    total: float
    contributions: Dict[str, float]


def score_action(personality: PersonalityTraits, factors: DecisionFactors) -> DecisionScore:
    """Return an explainable score; higher means more likely, never guaranteed."""
    risk_aversion = (100 - personality.risk_tolerance) / 100
    rule_weight = personality.rule_alignment / 100
    altruism_weight = personality.altruism / 100
    openness_weight = personality.openness / 100
    discipline_weight = personality.conscientiousness / 100
    emotional_weight = personality.emotional_sensitivity / 100

    contributions = {
        "goal_progress": 1.3 * _bounded(factors.goal_progress),
        "need_satisfaction": 1.2 * _bounded(factors.need_satisfaction),
        "value_alignment": _bounded(factors.value_alignment),
        "relationship": 0.8 * _bounded(factors.relationship_pull),
        "commitment": 1.5 * discipline_weight * _bounded(factors.commitment_pull),
        "habit": 0.5 * _bounded(factors.habit_pull),
        "curiosity": 0.7 * openness_weight * _bounded(factors.curiosity),
        "prosocial": 0.7 * altruism_weight * _bounded(factors.prosocial_value),
        "risk": -1.2 * risk_aversion * _bounded(factors.risk),
        "money_cost": -0.9 * _bounded(factors.money_cost),
        "time_cost": -0.8 * _bounded(factors.time_cost),
        "illegality": -1.0 * rule_weight * _bounded(factors.illegality),
        "moral_conflict": -1.5 * _bounded(factors.moral_conflict),
        "opportunity_cost": -0.8 * _bounded(factors.opportunity_cost),
        "fear": -0.8 * emotional_weight * _bounded(factors.fear_pressure),
        # Anger can make confrontation more attractive, but its influence is bounded.
        "anger": 0.25 * emotional_weight * _bounded(factors.anger_pressure),
    }
    return DecisionScore(round(sum(contributions.values()), 3), contributions)


__all__ = ["DecisionFactors", "DecisionScore", "score_action"]
