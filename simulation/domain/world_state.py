"""Authoritative state container for the campus simulation kernel.

The legacy prototype still owns its playable ``runtime.World``.  This module is
the side-by-side migration target: systems receive a transaction-local clone of
``WorldState`` and can never mutate the committed state directly.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable

from simulation.domain.entities import PHASES, Phase


AGGREGATE_NAMES = (
    "population",
    "places",
    "inventories",
    "relationships",
    "organizations",
    "forums",
    "tasks",
    "situations",
    "battles",
    "knowledge",
    "narrative",
    "cognition",
)


@dataclass
class ClockState:
    day: int = 1
    phase: str = Phase.MORNING.value
    minute: int = 0

    def validate(self) -> list[str]:
        errors: list[str] = []
        if isinstance(self.day, bool) or not isinstance(self.day, int) or self.day < 1:
            errors.append("clock.day must be an integer >= 1")
        if self.phase not in {phase.value for phase in PHASES}:
            errors.append(f"unsupported clock phase: {self.phase}")
        if isinstance(self.minute, bool) or not isinstance(self.minute, int):
            errors.append("clock.minute must be an integer")
        elif not 0 <= self.minute <= 359:
            errors.append("clock.minute must be between 0 and 359")
        return errors

    def advance_phase(self) -> None:
        phases = [phase.value for phase in PHASES]
        index = phases.index(self.phase)
        if index == len(phases) - 1:
            self.day += 1
            self.phase = phases[0]
        else:
            self.phase = phases[index + 1]
        self.minute = 0


@dataclass
class WorldState:
    """Composition root for authoritative gameplay aggregates.

    Values inside aggregates are deliberately plain serializable mappings while
    individual domain types are still being migrated.  The mapping boundary lets
    each system own one aggregate without forcing a second monolithic ``World``.
    """

    revision: int = 1
    clock: ClockState = field(default_factory=ClockState)
    content_version: str = "development"
    master_seed: int = 42
    event_sequence: int = 0
    population: Dict[str, Any] = field(default_factory=dict)
    places: Dict[str, Any] = field(default_factory=dict)
    inventories: Dict[str, Any] = field(default_factory=dict)
    relationships: Dict[str, Any] = field(default_factory=dict)
    organizations: Dict[str, Any] = field(default_factory=dict)
    forums: Dict[str, Any] = field(default_factory=dict)
    tasks: Dict[str, Any] = field(default_factory=dict)
    situations: Dict[str, Any] = field(default_factory=dict)
    battles: Dict[str, Any] = field(default_factory=dict)
    knowledge: Dict[str, Any] = field(default_factory=dict)
    narrative: Dict[str, Any] = field(default_factory=dict)
    cognition: Dict[str, Any] = field(default_factory=dict)
    processed_commands: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def clone(self) -> "WorldState":
        return deepcopy(self)

    def aggregate(self, name: str) -> Dict[str, Any]:
        if name not in AGGREGATE_NAMES:
            raise KeyError(f"unknown world aggregate: {name}")
        return getattr(self, name)

    def validate(self) -> list[str]:
        errors = self.clock.validate()
        if isinstance(self.revision, bool) or not isinstance(self.revision, int) or self.revision < 1:
            errors.append("world revision must be an integer >= 1")
        if isinstance(self.event_sequence, bool) or not isinstance(self.event_sequence, int) or self.event_sequence < 0:
            errors.append("event_sequence must be a non-negative integer")
        if isinstance(self.master_seed, bool) or not isinstance(self.master_seed, int):
            errors.append("master_seed must be an integer")
        if not isinstance(self.content_version, str) or not self.content_version:
            errors.append("content_version must be a non-empty string")
        for name in AGGREGATE_NAMES:
            value = getattr(self, name)
            if not isinstance(value, dict):
                errors.append(f"{name} aggregate must be a mapping")
            elif any(not isinstance(key, str) or not key for key in value):
                errors.append(f"{name} aggregate keys must be non-empty strings")
        if not isinstance(self.processed_commands, dict):
            errors.append("processed_commands must be a mapping")
        if not isinstance(self.metadata, dict):
            errors.append("metadata must be a mapping")
        return errors

    def require_valid(self, extra_errors: Iterable[str] = ()) -> None:
        errors = [*self.validate(), *extra_errors]
        if errors:
            raise ValueError("invalid world state: " + "; ".join(errors))

    def to_dict(self) -> Dict[str, Any]:
        return deepcopy(asdict(self))

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "WorldState":
        data = deepcopy(payload)
        clock_payload = data.pop("clock", {})
        state = cls(clock=ClockState(**clock_payload), **data)
        state.require_valid()
        return state


__all__ = ["AGGREGATE_NAMES", "ClockState", "WorldState"]
