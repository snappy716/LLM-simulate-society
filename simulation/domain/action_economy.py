"""Domain values for broad phases and their major-action allowance."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping

from simulation.domain.entities import PHASES


@dataclass(frozen=True)
class PhaseActionRule:
    phase: str
    major_actions: int
    optional: bool = False

    def __post_init__(self) -> None:
        if self.phase not in {item.value for item in PHASES}:
            raise ValueError(f"unsupported phase action rule: {self.phase}")
        if (
            isinstance(self.major_actions, bool)
            or not isinstance(self.major_actions, int)
            or self.major_actions < 0
        ):
            raise ValueError("major_actions must be a non-negative integer")


@dataclass(frozen=True)
class ActionEconomyPolicy:
    phase_rules: Mapping[str, PhaseActionRule]

    def __post_init__(self) -> None:
        expected = {item.value for item in PHASES}
        if set(self.phase_rules) != expected:
            raise ValueError("action economy must define every phase exactly once")
        for phase, rule in self.phase_rules.items():
            if phase != rule.phase:
                raise ValueError(f"phase rule key does not match rule: {phase}")

    def rule(self, phase: str) -> PhaseActionRule:
        try:
            return self.phase_rules[phase]
        except KeyError as exc:
            raise ValueError(f"unsupported phase: {phase}") from exc

    def to_dict(self) -> Dict[str, Any]:
        return {
            "phases": {
                phase: {
                    "major_actions": rule.major_actions,
                    "optional": rule.optional,
                }
                for phase, rule in self.phase_rules.items()
            }
        }


def build_action_economy_policy(entries: Iterable[Mapping[str, Any]]) -> ActionEconomyPolicy:
    rules: Dict[str, PhaseActionRule] = {}
    for entry in entries:
        rule = PhaseActionRule(
            phase=str(entry.get("id", "")),
            major_actions=entry.get("major_actions"),
            optional=entry.get("optional", False),
        )
        if rule.phase in rules:
            raise ValueError(f"duplicate phase action rule: {rule.phase}")
        rules[rule.phase] = rule
    return ActionEconomyPolicy(rules)


__all__ = ["ActionEconomyPolicy", "PhaseActionRule", "build_action_economy_policy"]
