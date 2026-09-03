"""Campus regions, enterable locations, reusable interiors, and routes."""
from __future__ import annotations

import heapq
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Dict, Iterable, List, Optional, Tuple

from simulation.domain.entities import PHASES


class LocationKind(str, Enum):
    BUILDING = "building"
    FIXED_INTERIOR = "fixed_interior"
    ROOM_GROUP = "room_group"
    OUTDOOR_POINT = "outdoor_point"


class InstancePolicy(str, Enum):
    FIXED = "fixed"
    POOLED = "pooled"


class TransitionKind(str, Enum):
    CONTINUOUS_BOUNDARY = "continuous_boundary"
    BUILDING_ENTRANCE = "building_entrance"
    INTERIOR_DOOR = "interior_door"


class EntranceStyle(str, Enum):
    LEVEL = "level"
    STAIRS = "stairs"
    RAMP = "ramp"
    SECURED = "secured"


@dataclass(frozen=True)
class CampusRegion:
    region_id: str
    name: str
    map_cell: Tuple[int, int]
    tags: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.region_id or not self.name:
            raise ValueError("campus region requires id and name")
        if len(self.map_cell) != 2 or any(not 0 <= value < 400 for value in self.map_cell):
            raise ValueError(f"region map cell is outside 400x400 map: {self.region_id}")
        object.__setattr__(self, "map_cell", tuple(self.map_cell))
        object.__setattr__(self, "tags", tuple(self.tags))


@dataclass(frozen=True)
class InteriorTemplate:
    template_id: str
    name: str
    presentation_key: str
    interaction_slots: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.template_id or not self.presentation_key:
            raise ValueError("interior template requires id and presentation_key")
        object.__setattr__(self, "interaction_slots", tuple(self.interaction_slots))


@dataclass(frozen=True)
class CampusLocation:
    location_id: str
    name: str
    kind: str
    region_id: str
    parent_id: str
    capacity: int
    entry_minutes: int
    open_phases: Tuple[str, ...]
    tags: Tuple[str, ...] = ()
    access_tags: Tuple[str, ...] = ()
    interior_template_id: Optional[str] = None
    instance_policy: str = InstancePolicy.FIXED.value
    pool_size: int = 1
    supports_night_layer: bool = True
    map_cell: Optional[Tuple[int, int]] = None
    entrance_style: str = EntranceStyle.LEVEL.value

    def __post_init__(self) -> None:
        if not self.location_id or not self.name or not self.region_id or not self.parent_id:
            raise ValueError("campus location requires id, name, region_id, and parent_id")
        if self.kind not in {item.value for item in LocationKind}:
            raise ValueError(f"unsupported location kind: {self.kind}")
        if self.instance_policy not in {item.value for item in InstancePolicy}:
            raise ValueError(f"unsupported instance policy: {self.instance_policy}")
        if self.entrance_style not in {item.value for item in EntranceStyle}:
            raise ValueError(f"unsupported entrance style: {self.entrance_style}")
        if self.capacity < 1 or self.entry_minutes < 0:
            raise ValueError(f"invalid capacity or entry time: {self.location_id}")
        if self.instance_policy == InstancePolicy.POOLED.value and self.pool_size < 1:
            raise ValueError(f"pooled location requires pool_size: {self.location_id}")
        if self.instance_policy == InstancePolicy.FIXED.value and self.pool_size != 1:
            raise ValueError(f"fixed location must have pool_size 1: {self.location_id}")
        phases = {phase.value for phase in PHASES}
        if not self.open_phases or any(phase not in phases for phase in self.open_phases):
            raise ValueError(f"invalid opening phases: {self.location_id}")
        if self.kind in {LocationKind.FIXED_INTERIOR.value, LocationKind.ROOM_GROUP.value} and not self.interior_template_id:
            raise ValueError(f"interior location requires a template: {self.location_id}")
        if self.kind == LocationKind.BUILDING.value and self.map_cell is None:
            raise ValueError(f"building requires a map cell: {self.location_id}")
        if self.map_cell is not None:
            if len(self.map_cell) != 2 or any(not 0 <= value < 400 for value in self.map_cell):
                raise ValueError(f"location map cell is outside 400x400 map: {self.location_id}")
            object.__setattr__(self, "map_cell", tuple(self.map_cell))
        object.__setattr__(self, "open_phases", tuple(self.open_phases))
        object.__setattr__(self, "tags", tuple(self.tags))
        object.__setattr__(self, "access_tags", tuple(self.access_tags))


@dataclass(frozen=True)
class CampusPassage:
    passage_id: str
    from_id: str
    to_id: str
    travel_minutes: int
    bidirectional: bool = True
    open_phases: Tuple[str, ...] = tuple(phase.value for phase in PHASES)
    required_access_tags: Tuple[str, ...] = ()
    tags: Tuple[str, ...] = ()
    transition_kind: str = TransitionKind.CONTINUOUS_BOUNDARY.value
    exit_always_allowed: bool = False
    from_anchor_id: str = ""
    to_anchor_id: str = ""

    def __post_init__(self) -> None:
        if not self.passage_id or not self.from_id or not self.to_id:
            raise ValueError("campus passage requires id and endpoints")
        if self.from_id == self.to_id or self.travel_minutes < 0:
            raise ValueError(f"invalid campus passage: {self.passage_id}")
        if self.transition_kind not in {item.value for item in TransitionKind}:
            raise ValueError(f"invalid transition kind: {self.passage_id}")
        if not self.from_anchor_id or not self.to_anchor_id:
            raise ValueError(f"campus passage requires stable arrival anchors: {self.passage_id}")
        phases = {phase.value for phase in PHASES}
        if not self.open_phases or any(phase not in phases for phase in self.open_phases):
            raise ValueError(f"invalid passage phases: {self.passage_id}")
        object.__setattr__(self, "open_phases", tuple(self.open_phases))
        object.__setattr__(self, "required_access_tags", tuple(self.required_access_tags))
        object.__setattr__(self, "tags", tuple(self.tags))


@dataclass(frozen=True)
class RouteStep:
    passage_id: str
    from_id: str
    to_id: str
    travel_minutes: int


@dataclass(frozen=True)
class CampusRoute:
    start_id: str
    destination_id: str
    total_minutes: int
    steps: Tuple[RouteStep, ...]


class CampusLocationGraph:
    def __init__(
        self,
        regions: Iterable[CampusRegion],
        locations: Iterable[CampusLocation],
        templates: Iterable[InteriorTemplate],
        passages: Iterable[CampusPassage],
    ) -> None:
        self.regions = self._unique(regions, "region_id", "region")
        self.locations = self._unique(locations, "location_id", "location")
        self.templates = self._unique(templates, "template_id", "interior template")
        explicit = list(passages)
        generated = [
            CampusPassage(
                passage_id=f"parent:{location.location_id}",
                from_id=location.parent_id,
                to_id=location.location_id,
                travel_minutes=location.entry_minutes,
                open_phases=location.open_phases,
                required_access_tags=location.access_tags,
                tags=("generated_parent",),
                transition_kind=self._parent_transition_kind(location),
                exit_always_allowed=True,
                from_anchor_id=f"outside:{location.location_id}:entrance",
                to_anchor_id=f"inside:{location.location_id}:entrance",
            )
            for location in self.locations.values()
        ]
        self.passages = self._unique([*explicit, *generated], "passage_id", "passage")
        self.require_valid()

    @property
    def node_ids(self) -> set[str]:
        return {*self.regions, *self.locations}

    def is_open(self, location_id: str, phase: str) -> bool:
        location = self.locations.get(location_id)
        return True if location is None else phase in location.open_phases

    def shortest_route(
        self,
        start_id: str,
        destination_id: str,
        *,
        phase: str,
        access_tags: Iterable[str] = (),
    ) -> Optional[CampusRoute]:
        if start_id not in self.node_ids or destination_id not in self.node_ids:
            return None
        if start_id == destination_id:
            return CampusRoute(start_id, destination_id, 0, ())
        actor_tags = set(access_tags)
        adjacency: Dict[str, List[RouteStep]] = {node_id: [] for node_id in self.node_ids}
        for passage in self.passages.values():
            normally_open = (
                phase in passage.open_phases
                and set(passage.required_access_tags).issubset(actor_tags)
            )
            if normally_open and self.is_open(passage.to_id, phase):
                adjacency[passage.from_id].append(RouteStep(
                    passage.passage_id, passage.from_id, passage.to_id, passage.travel_minutes
                ))
            if passage.bidirectional and (
                passage.exit_always_allowed
                or (normally_open and self.is_open(passage.from_id, phase))
            ):
                adjacency[passage.to_id].append(RouteStep(
                    passage.passage_id, passage.to_id, passage.from_id, passage.travel_minutes
                ))
        queue: list[tuple[int, str, Tuple[RouteStep, ...]]] = [(0, start_id, ())]
        best = {start_id: 0}
        while queue:
            minutes, node_id, steps = heapq.heappop(queue)
            if node_id == destination_id:
                return CampusRoute(start_id, destination_id, minutes, steps)
            if minutes != best.get(node_id):
                continue
            for step in adjacency[node_id]:
                candidate = minutes + step.travel_minutes
                if candidate < best.get(step.to_id, 10**9):
                    best[step.to_id] = candidate
                    heapq.heappush(queue, (candidate, step.to_id, (*steps, step)))
        return None

    def validate(self) -> list[str]:
        errors: list[str] = []
        nodes = self.node_ids
        for location in self.locations.values():
            if location.region_id not in self.regions:
                errors.append(f"{location.location_id}: unknown region {location.region_id}")
            if location.parent_id not in nodes:
                errors.append(f"{location.location_id}: unknown parent {location.parent_id}")
            if location.interior_template_id and location.interior_template_id not in self.templates:
                errors.append(
                    f"{location.location_id}: unknown interior template {location.interior_template_id}"
                )
            seen = {location.location_id}
            parent_id = location.parent_id
            while parent_id in self.locations:
                if parent_id in seen:
                    errors.append(f"{location.location_id}: parent cycle")
                    break
                seen.add(parent_id)
                parent_id = self.locations[parent_id].parent_id
        for passage in self.passages.values():
            if passage.from_id not in nodes or passage.to_id not in nodes:
                errors.append(f"{passage.passage_id}: unknown endpoint")
        return errors

    def require_valid(self) -> None:
        errors = self.validate()
        if errors:
            raise ValueError("invalid campus location graph: " + "; ".join(errors))

    def state_projection(self) -> Dict[str, dict]:
        projection = {
            region_id: {"node_type": "region", **asdict(region)}
            for region_id, region in self.regions.items()
        }
        projection.update({
            location_id: {"node_type": "location", **asdict(location)}
            for location_id, location in self.locations.items()
        })
        return projection

    @staticmethod
    def _unique(values, id_field: str, label: str):
        result = {}
        for value in values:
            content_id = getattr(value, id_field)
            if content_id in result:
                raise ValueError(f"duplicate {label}: {content_id}")
            result[content_id] = value
        return result

    @staticmethod
    def _parent_transition_kind(location: CampusLocation) -> str:
        if location.kind == LocationKind.OUTDOOR_POINT.value:
            return TransitionKind.CONTINUOUS_BOUNDARY.value
        if location.kind == LocationKind.BUILDING.value:
            return TransitionKind.BUILDING_ENTRANCE.value
        return TransitionKind.INTERIOR_DOOR.value


__all__ = [
    "CampusLocation",
    "CampusLocationGraph",
    "CampusPassage",
    "CampusRegion",
    "CampusRoute",
    "EntranceStyle",
    "InstancePolicy",
    "InteriorTemplate",
    "LocationKind",
    "RouteStep",
    "TransitionKind",
]
