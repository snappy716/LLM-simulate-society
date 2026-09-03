"""Fixed 28-day story anchors; participants and paths remain dynamic."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DemoStage:
    stage_id: str
    title: str
    start_day: int
    end_day: int
    reading_id: str
    fixed_truth_ids: tuple[str, ...]


DEMO_STAGES = (
    DemoStage("misnaming", "错名", 1, 7, "freud_everyday_life", ("truth:lin_mo_name",)),
    DemoStage("substitute_dream", "代梦", 8, 14, "freud_dreams", ("truth:death_scene",)),
    DemoStage("mirror_person", "镜中之人", 15, 21, "lacan_mirror", ("truth:identity_substitution",)),
    DemoStage("who_remembers", "谁在记得我", 22, 28, "james_self_memory", ("truth:professor_dead",)),
)


def stage_for_day(day: int) -> DemoStage:
    if not 1 <= day <= 28:
        raise ValueError("the demo calendar contains days 1 through 28")
    return next(stage for stage in DEMO_STAGES if stage.start_day <= day <= stage.end_day)


def day_role(day: int) -> str:
    stage = stage_for_day(day)
    offset = day - stage.start_day + 1
    return {
        1: "opening",
        2: "investigation",
        3: "investigation",
        4: "midpoint",
        5: "escalation",
        6: "preparation",
        7: "deadline",
    }[offset]


__all__ = ["DemoStage", "DEMO_STAGES", "stage_for_day", "day_role"]
