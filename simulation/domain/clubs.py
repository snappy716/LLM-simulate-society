"""Validated value objects for the campus club runtime."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping


CLUB_RANKS = ("member", "core_member", "leader")


@dataclass(frozen=True)
class CampusClubPolicy:
    rank_thresholds: Mapping[str, int]
    activity_contribution: int
    activity_resource_gain: int
    task_contribution: int
    task_resource_gain: int
    daily_resource_cost: int
    resource_capacity: int
    initial_resource: int
    core_member_limit: int
    tactic_resource_cost: int
    recruitment_score_threshold: int
    existing_membership_penalty: int

    def __post_init__(self) -> None:
        if tuple(self.rank_thresholds) != CLUB_RANKS:
            raise ValueError("club rank thresholds must follow member/core_member/leader")
        values = tuple(int(self.rank_thresholds[rank]) for rank in CLUB_RANKS)
        if values[0] != 0 or values != tuple(sorted(values)):
            raise ValueError("club rank thresholds must start at zero and increase")
        for name in (
            "activity_contribution", "activity_resource_gain", "daily_resource_cost",
            "task_contribution", "task_resource_gain",
            "resource_capacity", "initial_resource", "core_member_limit",
            "tactic_resource_cost", "recruitment_score_threshold",
            "existing_membership_penalty",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"club policy {name} must be a non-negative integer")
        if self.initial_resource > self.resource_capacity:
            raise ValueError("initial club resources cannot exceed capacity")
        if self.core_member_limit < 1:
            raise ValueError("club core-member limit must be positive")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rank_thresholds": dict(self.rank_thresholds),
            "activity_contribution": self.activity_contribution,
            "activity_resource_gain": self.activity_resource_gain,
            "task_contribution": self.task_contribution,
            "task_resource_gain": self.task_resource_gain,
            "daily_resource_cost": self.daily_resource_cost,
            "resource_capacity": self.resource_capacity,
            "initial_resource": self.initial_resource,
            "core_member_limit": self.core_member_limit,
            "tactic_resource_cost": self.tactic_resource_cost,
            "recruitment_score_threshold": self.recruitment_score_threshold,
            "existing_membership_penalty": self.existing_membership_penalty,
        }


def parse_club_policy(document: Mapping[str, Any]) -> CampusClubPolicy:
    raw = document.get("runtime_policy", {})
    if not isinstance(raw, dict):
        raise ValueError("club runtime_policy must be a mapping")
    return CampusClubPolicy(
        rank_thresholds=dict(raw.get("rank_thresholds", {})),
        activity_contribution=int(raw.get("activity_contribution", 4)),
        activity_resource_gain=int(raw.get("activity_resource_gain", 1)),
        task_contribution=int(raw.get("task_contribution", 6)),
        task_resource_gain=int(raw.get("task_resource_gain", 3)),
        daily_resource_cost=int(raw.get("daily_resource_cost", 4)),
        resource_capacity=int(raw.get("resource_capacity", 100)),
        initial_resource=int(raw.get("initial_resource", 40)),
        core_member_limit=int(raw.get("core_member_limit", 3)),
        tactic_resource_cost=int(raw.get("tactic_resource_cost", 8)),
        recruitment_score_threshold=int(raw.get("recruitment_score_threshold", 175)),
        existing_membership_penalty=int(raw.get("existing_membership_penalty", 25)),
    )


__all__ = ["CLUB_RANKS", "CampusClubPolicy", "parse_club_policy"]
