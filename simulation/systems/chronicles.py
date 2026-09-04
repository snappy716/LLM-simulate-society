"""Project committed simulation events into per-actor objective chronicles."""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from typing import Any, Dict, Iterable, Sequence

from simulation.domain.chronicles import NpcChronicleEntry
from simulation.domain.events import SimulationEvent
from simulation.domain.world_state import WorldState


CHRONICLE_SCHEMA_VERSION = 1
CHRONICLE_CERTAINTIES = {"reliable", "reported", "doubtful"}
_SKIPPED_EVENT_TYPES = {"NPC_DECISION_MADE", "WORLD_PHASE_ADVANCED"}
_TASK_IMPORTANCE = {
    "FORUM_TASK_VIEWED": 0,
    "FORUM_TASK_CLAIMED": 2,
    "FORUM_TASK_COMPLETED": 4,
    "FORUM_TASK_ABANDONED": 3,
    "FORUM_TASK_EXPIRED": 3,
}


def install_chronicles(state: WorldState) -> None:
    state.chronicles.clear()
    state.chronicles.update({
        "schema_version": CHRONICLE_SCHEMA_VERSION,
        "entries": {},
        "by_actor": {actor_id: [] for actor_id in state.population},
        "known_by": {"player": {}} if "player" in state.population else {},
        "entry_count": 0,
        "last_batch_entry_ids": [],
    })


def _category(event: SimulationEvent) -> str:
    event_type = event.event_type
    tags = set(event.knowledge_tags)
    if event_type.startswith("FORUM_TASK_") or "task" in tags:
        return "task"
    if "trade" in tags or "TRADE" in event_type:
        return "trade"
    if "organization" in tags or "club" in tags or "CLUB" in event_type:
        return "organization"
    if "combat" in tags or "COMBAT" in event_type or "ATTACK" in event_type:
        return "combat"
    if "injury" in tags or "INJUR" in event_type or "HEAL" in event_type:
        return "injury"
    if "night" in tags or "pollution" in tags or "NIGHT" in event_type:
        return "night"
    if "discovery" in tags or "evidence" in tags or "DISCOVER" in event_type:
        return "discovery"
    if "story" in tags or "narrative" in tags:
        return "story"
    if "social" in tags or "relationship" in tags:
        return "social"
    return "routine"


def _importance(event: SimulationEvent, category: str) -> int:
    if event.event_type in _TASK_IMPORTANCE:
        return _TASK_IMPORTANCE[event.event_type]
    minimum = {
        "story": 5, "combat": 4, "injury": 4, "night": 4,
        "discovery": 3, "organization": 2, "social": 2,
        "trade": 1, "task": 2, "routine": 0,
    }[category]
    return min(5, max(minimum, (event.severity + 1) // 2))


def _visibility(event: SimulationEvent, category: str) -> str:
    if event.visibility == "secret":
        return "secret"
    if event.visibility == "public":
        return "public"
    if category == "routine":
        return "observable"
    return "private"


def _summary_key(event: SimulationEvent) -> str:
    return {
        "NPC_ACTIVITY_COMPLETED": "activity_completed",
        "CAMPUS_ACTIVITY_EFFECT_APPLIED": "activity_completed",
        "NPC_ROUTINE_ACTION_COMPLETED": "routine_actions_completed",
        "ACTOR_LOCATION_CHANGED": "location_changed",
    }.get(event.event_type, event.event_type.lower())


def _outcome(event: SimulationEvent) -> str:
    if event.event_type.endswith("_BLOCKED"):
        return "blocked"
    if event.event_type.endswith("_ABANDONED"):
        return "abandoned"
    if event.event_type.endswith("_EXPIRED"):
        return "expired"
    return str(event.payload.get("outcome", "completed"))


def _subject_ids(state: WorldState, event: SimulationEvent) -> tuple[str, ...]:
    return tuple(dict.fromkeys(
        actor_id for actor_id in (*event.actor_ids, *event.target_ids)
        if actor_id in state.population
    ))


def _entry_for(
    actor_id: str,
    event: SimulationEvent,
    *,
    source_events: Sequence[SimulationEvent] | None = None,
) -> NpcChronicleEntry:
    sources = tuple(source_events or (event,))
    category = _category(event)
    related = tuple(dict.fromkeys(
        participant
        for source in sources
        for participant in (*source.actor_ids, *source.target_ids)
        if participant != actor_id
    ))
    parameters = deepcopy(event.payload)
    parameters.setdefault("public_summary", event.public_summary)
    return NpcChronicleEntry(
        entry_id=f"chron:{event.event_id}:{actor_id}",
        actor_id=actor_id,
        day=event.day,
        phase=event.phase,
        minute=event.minute,
        category=category,
        event_type=event.event_type,
        scene_id=event.scene_id,
        related_actor_ids=related,
        importance=max(_importance(source, _category(source)) for source in sources),
        outcome=_outcome(event),
        visibility=_visibility(event, category),
        summary_key=_summary_key(event),
        parameters=parameters,
        source_event_ids=tuple(source.event_id for source in sources),
        knowledge_tags=tuple(dict.fromkeys(
            tag for source in sources for tag in source.knowledge_tags
        )),
    )


def _project_actor_events(
    actor_id: str,
    events: Sequence[SimulationEvent],
) -> list[NpcChronicleEntry]:
    relevant = [
        event for event in events
        if event.event_type not in _SKIPPED_EVENT_TYPES
    ]
    activity_events: Dict[str, list[SimulationEvent]] = defaultdict(list)
    movement_events: list[SimulationEvent] = []
    standalone: list[SimulationEvent] = []
    for event in relevant:
        activity_id = event.payload.get("activity_id")
        if event.event_type == "ACTOR_LOCATION_CHANGED":
            movement_events.append(event)
        elif event.event_type in {"CAMPUS_ACTIVITY_EFFECT_APPLIED", "NPC_ACTIVITY_COMPLETED"} and isinstance(activity_id, str):
            activity_events[activity_id].append(event)
        else:
            standalone.append(event)

    entries: list[NpcChronicleEntry] = []
    for activity_id, grouped in activity_events.items():
        completion = next(
            (event for event in reversed(grouped) if event.event_type == "NPC_ACTIVITY_COMPLETED"),
            grouped[-1],
        )
        matching_movement = [
            event for event in movement_events
            if event.day == completion.day and event.phase == completion.phase
        ]
        entry = _entry_for(actor_id, completion, source_events=[*matching_movement, *grouped])
        payload = entry.to_dict()
        payload["parameters"]["activity_id"] = activity_id
        if matching_movement:
            payload["parameters"].update({
                "from_id": matching_movement[0].payload.get("from_id"),
                "to_id": matching_movement[-1].payload.get("to_id"),
                "route_step_count": len(matching_movement),
            })
        entries.append(NpcChronicleEntry.from_dict(payload))
    if not activity_events and movement_events:
        entries.append(_entry_for(actor_id, movement_events[-1], source_events=movement_events))
    entries.extend(_entry_for(actor_id, event) for event in standalone)
    return sorted(entries, key=lambda entry: entry.source_event_ids[0])


def project_chronicle_events(state: WorldState, events: Iterable[SimulationEvent]) -> None:
    """Mutate only the transaction-local chronicle aggregate."""
    if not state.chronicles:
        install_chronicles(state)
    elif state.chronicles.get("schema_version") != CHRONICLE_SCHEMA_VERSION:
        raise ValueError("cannot project events into an unsupported chronicle schema")
    batch = tuple(events)
    events_by_actor: Dict[str, list[SimulationEvent]] = defaultdict(list)
    for event in batch:
        for actor_id in _subject_ids(state, event):
            events_by_actor[actor_id].append(event)
    entries = state.chronicles.setdefault("entries", {})
    by_actor = state.chronicles.setdefault("by_actor", {})
    new_entry_ids: list[str] = []
    for actor_id, actor_events in events_by_actor.items():
        actor_index = by_actor.setdefault(actor_id, [])
        for entry in _project_actor_events(actor_id, actor_events):
            entries[entry.entry_id] = entry.to_dict()
            actor_index.append(entry.entry_id)
            new_entry_ids.append(entry.entry_id)
            player = state.population.get("player", {})
            if actor_id != "player" and isinstance(player, dict):
                if "player" in entry.related_actor_ids:
                    grant_chronicle_knowledge(
                        state, "player", entry.entry_id,
                        source="participant", certainty="reliable",
                    )
                elif entry.scene_id and player.get("current_location_id") == entry.scene_id:
                    grant_chronicle_knowledge(
                        state, "player", entry.entry_id,
                        source="witnessed", certainty="reliable",
                    )
    state.chronicles["entry_count"] = len(entries)
    state.chronicles["last_batch_entry_ids"] = new_entry_ids


def grant_chronicle_knowledge(
    state: WorldState,
    viewer_id: str,
    entry_id: str,
    *,
    source: str,
    certainty: str = "reported",
) -> None:
    """Record that a viewer learned an objective entry through an explicit source."""
    if viewer_id not in state.population:
        raise ValueError(f"unknown chronicle viewer: {viewer_id}")
    if entry_id not in state.chronicles.get("entries", {}):
        raise ValueError(f"unknown chronicle entry: {entry_id}")
    if not source:
        raise ValueError("chronicle knowledge source is required")
    if certainty not in CHRONICLE_CERTAINTIES:
        raise ValueError(f"unsupported chronicle certainty: {certainty}")
    state.chronicles.setdefault("known_by", {}).setdefault(viewer_id, {})[entry_id] = {
        "source": source,
        "certainty": certainty,
    }


def _validate_chronicles(state: WorldState, *, deep: bool) -> list[str]:
    aggregate = state.chronicles
    if not aggregate:
        return []
    errors: list[str] = []
    if aggregate.get("schema_version") != CHRONICLE_SCHEMA_VERSION:
        errors.append("chronicles schema_version is unsupported")
    entries = aggregate.get("entries")
    by_actor = aggregate.get("by_actor")
    known_by = aggregate.get("known_by")
    if not isinstance(entries, dict) or not isinstance(by_actor, dict) or not isinstance(known_by, dict):
        return [*errors, "chronicles entries, by_actor, and known_by must be mappings"]
    indexed_count = 0
    last_batch = aggregate.get("last_batch_entry_ids", [])
    if not isinstance(last_batch, list):
        errors.append("chronicles last_batch_entry_ids must be a list")
        last_batch = []
    ids_to_validate = set(entries) if deep else set(last_batch)
    for actor_id, entry_ids in by_actor.items():
        if actor_id not in state.population:
            errors.append(f"chronicle index references unknown actor {actor_id}")
        if not isinstance(entry_ids, list) or len(entry_ids) != len(set(entry_ids)):
            errors.append(f"chronicle index for {actor_id} must be a unique list")
            continue
        indexed_count += len(entry_ids)
        for entry_id in entry_ids:
            payload = entries.get(entry_id)
            if not isinstance(payload, dict):
                errors.append(f"chronicle index references missing entry {entry_id}")
                continue
            if entry_id not in ids_to_validate:
                continue
            try:
                entry = NpcChronicleEntry.from_dict(payload)
            except (TypeError, ValueError) as exc:
                errors.append(f"invalid chronicle entry {entry_id}: {exc}")
                continue
            if entry.entry_id != entry_id or entry.actor_id != actor_id:
                errors.append(f"chronicle entry {entry_id} index identity mismatch")
    declared_count = aggregate.get("entry_count")
    if declared_count != len(entries) or indexed_count != len(entries):
        errors.append("chronicle entry count does not match indexes")
    if any(entry_id not in entries for entry_id in last_batch):
        errors.append("chronicle last batch references missing entries")
    for viewer_id, records in known_by.items():
        if viewer_id not in state.population:
            errors.append(f"chronicle knowledge references unknown viewer {viewer_id}")
        if not isinstance(records, dict):
            errors.append(f"chronicle knowledge for {viewer_id} must be a mapping")
            continue
        for entry_id, record in records.items():
            if entry_id not in entries:
                errors.append(f"chronicle knowledge references missing entry {entry_id}")
            if not isinstance(record, dict) or record.get("certainty") not in CHRONICLE_CERTAINTIES or not record.get("source"):
                errors.append(f"chronicle knowledge record {viewer_id}:{entry_id} is invalid")
    return errors


def chronicle_invariant(state: WorldState) -> Iterable[str]:
    return _validate_chronicles(state, deep=False)


def validate_all_chronicles(state: WorldState) -> Iterable[str]:
    """Deep validation used at save/load and release boundaries."""
    return _validate_chronicles(state, deep=True)


__all__ = [
    "CHRONICLE_CERTAINTIES", "CHRONICLE_SCHEMA_VERSION", "chronicle_invariant",
    "grant_chronicle_knowledge", "install_chronicles", "project_chronicle_events",
    "validate_all_chronicles",
]
