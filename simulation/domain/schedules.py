"""Serializable weekly campus schedule values."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Mapping

from simulation.domain.entities import PHASES


@dataclass(frozen=True)
class ScheduleSlotTemplate:
    activity_id: str
    location: str
    action_class: str
    priority: int

    def __post_init__(self) -> None:
        if not self.activity_id or not self.location:
            raise ValueError("schedule slot requires activity_id and location")
        if self.action_class not in {"free", "major"}:
            raise ValueError(f"unsupported schedule action class: {self.action_class}")
        if isinstance(self.priority, bool) or not isinstance(self.priority, int) or not 0 <= self.priority <= 100:
            raise ValueError("schedule priority must be an integer between 0 and 100")


@dataclass(frozen=True)
class CampusScheduleTemplate:
    schedule_id: str
    weekday: Mapping[str, ScheduleSlotTemplate]
    weekend: Mapping[str, ScheduleSlotTemplate]

    def __post_init__(self) -> None:
        if not self.schedule_id:
            raise ValueError("schedule_id is required")
        expected = {phase.value for phase in PHASES}
        if set(self.weekday) != expected or set(self.weekend) != expected:
            raise ValueError(f"schedule {self.schedule_id} must define all phases")


@dataclass(frozen=True)
class PlannedScheduleSlot:
    activity_id: str
    action_class: str
    priority: int
    requested_location_id: str
    location_id: str
    capacity_redirected: bool = False
    redirect_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def parse_schedule_template(payload: Mapping[str, Any]) -> CampusScheduleTemplate:
    def parse_day(day: Mapping[str, Any]) -> Dict[str, ScheduleSlotTemplate]:
        return {
            phase: ScheduleSlotTemplate(
                activity_id=str(slot.get("activity_id", "")),
                location=str(slot.get("location", "")),
                action_class=str(slot.get("action_class", "")),
                priority=slot.get("priority"),
            )
            for phase, slot in day.items()
        }

    return CampusScheduleTemplate(
        schedule_id=str(payload.get("id", "")),
        weekday=parse_day(payload.get("weekday", {})),
        weekend=parse_day(payload.get("weekend", {})),
    )


__all__ = [
    "CampusScheduleTemplate",
    "PlannedScheduleSlot",
    "ScheduleSlotTemplate",
    "parse_schedule_template",
]
