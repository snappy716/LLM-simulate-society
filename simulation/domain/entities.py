"""Core domain entities shared by simulation systems and API adapters."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class Phase(str, Enum):
    MORNING = "morning"
    AFTERNOON = "afternoon"
    EVENING = "evening"
    LATE_NIGHT = "late_night"


PHASES = [Phase.MORNING, Phase.AFTERNOON, Phase.EVENING, Phase.LATE_NIGHT]


class EventLevel(str, Enum):
    BACKGROUND = "background"
    SIGNIFICANT = "significant"
    NARRATIVE = "narrative"


class NPCLayer(str, Enum):
    ORDINARY = "ordinary"
    OFFICIAL_BEYONDER = "official_beyonder"
    WILD_BEYONDER = "wild_beyonder"
    HOSTILE_BEYONDER = "hostile_beyonder"


GAME_EVENT_TYPES = {
    "CRIME_COMMITTED", "CRIME_ATTEMPT_EXPOSED", "PICKPOCKETED", "TAVERN_FIGHT",
    "INJURED_IN_ASSAULT", "DEATH_FROM_ASSAULT", "DEATH_FROM_UNTREATED_INJURY",
    "FRIEND_CRISIS_INTERVENTION", "NIGHT_OCCULT_INCIDENT",
    "INCIDENT_REPORT_FILED", "INCIDENT_SCENE_HANDLED", "CASE_STAGE_CHANGED",
    "ILLEGAL_OPERATION_STAGE", "ILLEGAL_RITUAL_STOPPED", "HOSTILE_LEADER_ARRESTED",
    "ARRESTED_MEMBER_RESCUED", "STORY_CHARACTER_ARRIVED", "RITUAL_PERFORMED",
    "OCCULT_ITEM_FOUND", "ARREST_AUTHORIZED", "SUSPECT_ARRESTED",
    "SUSPECT_ESCAPED_ARREST", "HOSTILE_CELL_REGROUPED", "FUGITIVE_CAPTURED",
    "SUPPLEMENTARY_TESTIMONY_ATTACHED", "CROSS_FACTION_DEBT_CREATED",
}


@dataclass
class Config:
    seed: int = 42
    days: int = 3
    core_npcs: int = 20
    simple_npcs: int = 180
    llm_mode: str = "auto"
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3:8b"
    deepseek_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"
    deepseek_api_key: Optional[str] = None
    max_llm_core_npcs: int = 20
    llm_concurrency: int = 5
    story_create_threshold: float = 38.0
    quest_threshold: float = 58.0
    max_interactions_per_scene: int = 5
    log_dir: str = "runs/latest"
    verbose: bool = True


@dataclass
class Scene:
    id: str
    name: str
    tags: List[str]
    danger: int
    security: int
    privacy: int
    event_tags: List[str]
    occult_contamination: int = 0


@dataclass
class WorldObject:
    id: str
    name: str
    object_type: str
    scene_id: Optional[str]
    owner_id: Optional[str] = None
    holder_id: Optional[str] = None
    container_id: Optional[str] = None
    quantity: int = 1
    condition: int = 100
    value: int = 0
    legality: str = "legal"
    tags: List[str] = field(default_factory=list)
    affordances: List[str] = field(default_factory=list)
    hidden: bool = False
    concealment: int = 0
    discovered_by: List[str] = field(default_factory=list)
    known_location_by: List[str] = field(default_factory=list)
    search_attempts: Dict[str, int] = field(default_factory=dict)
    custodian_id: Optional[str] = None
    hidden_event_id: Optional[str] = None
    destroyed: bool = False
    knowledge_id: Optional[str] = None


@dataclass
class Memory:
    day: int
    phase: str
    summary: str
    importance: int
    event_id: str
    tags: List[str] = field(default_factory=list)


@dataclass
class Relationship:
    trust: int = 50
    affection: int = 0
    suspicion: int = 0
    fear: int = 0
    kinds: List[str] = field(default_factory=list)
    since_day: int = 0


@dataclass
class SocialInvitation:
    id: str
    inviter_id: str
    invitee_id: str
    day: int
    phase: str
    scene_id: str
    activity: str
    required_relationship: str
    status: str = "pending"
    response_reason: str = ""


@dataclass
class PhasePlan:
    scene_id: str
    intent: str
    target_id: Optional[str] = None
    priority: int = 50
    behavior: str = "routine"
    fallback_scene_id: Optional[str] = None


@dataclass
class Commitment:
    execute_phase: str
    scene_id: str
    source_id: str
    priority: int
    promise: str
    active: bool = True


@dataclass
class StateDelta:
    npc_id: str
    state_name: str
    old_value: int
    delta: int
    new_value: int
    source_event_id: Optional[str]
    reason: str


@dataclass
class Observation:
    id: str
    observer_id: str
    source_event_id: str
    scene_id: str
    perceived_content: str
    accuracy: float
    severity: int
    conflict_ids: List[str] = field(default_factory=list)
    object_ids: List[str] = field(default_factory=list)
    reported: bool = False


@dataclass
class Report:
    id: str
    reporter_id: str
    listener_id: str
    observation_id: str
    source_event_id: str
    statement: str
    confidence: float
    day: int


@dataclass
class IncidentReport:
    id: str
    reporter_id: str
    source_event_id: str
    incident_type: str
    scene_id: str
    scene_name: str
    occurred_day: int
    occurred_phase: str
    full_account: str
    victim_ids: List[str]
    suspect_ids: List[str]
    witness_ids: List[str]
    status: str = "draft"
    assigned_officer_ids: List[str] = field(default_factory=list)
    case_id: Optional[str] = None
    handled_event_id: Optional[str] = None
    supplementary_reporter_ids: List[str] = field(default_factory=list)


@dataclass
class CaseFile:
    id: str
    case_type: str
    status: str
    assigned_officer_ids: List[str]
    report_ids: List[str]
    evidence_ids: List[str]
    suspect_ids: List[str]
    known_locations: List[str]
    conflict_ids: List[str]
    priority: int
    progress: int = 0
    stage: str = "reported"
    exposure_counts: Dict[str, int] = field(default_factory=dict)
    stage_history: List[str] = field(default_factory=lambda: ["reported"])
    linked_operation_id: Optional[str] = None
    linked_goal_id: Optional[str] = None
    last_progress_day: int = 0
    closed_day: Optional[int] = None
    created_day: int = 1


@dataclass
class Faction:
    id: str
    name: str
    alignment: str
    headquarters_scene_id: str
    member_ids: List[str] = field(default_factory=list)


@dataclass
class WorldConflict:
    id: str
    title: str
    official_faction_ids: List[str]
    hostile_faction_ids: List[str]
    pressure: int = 25
    stage: str = "hidden_struggle"
    event_ids: List[str] = field(default_factory=list)


@dataclass
class ResponseDrive:
    id: str
    source_event_id: str
    drive_type: str
    scene_id: str
    behavior: str
    intent: str
    priority: int
    execute_phase: str = "afternoon"
    expires_day: int = 0
    active: bool = True


@dataclass
class ActionCheckResult:
    check_type: str
    actor_id: str
    opponent_id: str
    actor_roll: int
    opponent_roll: int
    actor_modifiers: Dict[str, int]
    opponent_modifiers: Dict[str, int]
    actor_total: int
    opponent_total: int
    margin: int
    outcome: str


@dataclass
class NPC:
    id: str
    name: str
    tier: str
    occupation: str
    home_scene: str
    work_scene: str
    personality: Dict[str, int]
    needs: Dict[str, int]
    emotions: Dict[str, int]
    abilities: Dict[str, int]
    organization: Optional[str]
    work_days: List[int] = field(default_factory=list)
    work_phases: List[str] = field(default_factory=list)
    special_needs: Dict[str, int] = field(default_factory=dict)
    skills: Dict[str, int] = field(default_factory=dict)
    layer: str = NPCLayer.ORDINARY.value
    sequence_pathway: Optional[str] = None
    sequence_rank: Optional[int] = None
    faction_ids: List[str] = field(default_factory=list)
    duties: List[str] = field(default_factory=list)
    response_drives: List[ResponseDrive] = field(default_factory=list)
    current_scene: str = "home_quarter"
    goals: List[str] = field(default_factory=list)
    knowledge: List[str] = field(default_factory=list)
    beliefs: List[str] = field(default_factory=list)
    memories: List[Memory] = field(default_factory=list)
    relationships: Dict[str, Relationship] = field(default_factory=dict)
    commitments: List[Commitment] = field(default_factory=list)
    investigation_progress: Dict[str, int] = field(default_factory=dict)
    states: Dict[str, int] = field(default_factory=dict)
    daily_plan: Dict[str, PhasePlan] = field(default_factory=dict)
    action_chain: List[Dict[str, Any]] = field(default_factory=list)
    long_term_goal_ids: List[str] = field(default_factory=list)
    alive: bool = True
    wealth: int = 50
    sanity: int = 80
    health: int = 100
    disposition_status: str = "active"
    disposition_since_day: Optional[int] = None
    disposition_cause_event_id: Optional[str] = None

    def relevant_memories(self, limit: int = 8) -> List[str]:
        ranked = sorted(self.memories, key=lambda memory: (memory.importance, memory.day), reverse=True)
        return [memory.summary for memory in ranked[:limit]]


@dataclass
class SimEvent:
    event_id: str
    trace_id: str
    day: int
    phase: str
    event_type: str
    scene_id: Optional[str]
    actor_ids: List[str]
    description: str
    severity: int
    conflict: int
    danger: int
    secret: int
    emotion: int
    tags: List[str]
    parent_id: Optional[str] = None
    level: str = EventLevel.SIGNIFICANT.value
    object_ids: List[str] = field(default_factory=list)
    knowledge_ids: List[str] = field(default_factory=list)
    organization_ids: List[str] = field(default_factory=list)
    conflict_ids: List[str] = field(default_factory=list)


@dataclass
class StoryThread:
    id: str
    title: str
    event_ids: List[str]
    participants: List[str]
    scenes: List[str]
    tags: List[str]
    score: float
    pressure: int
    unresolved_questions: List[str]
    active: bool = True
    quest_published: bool = False
    object_ids: List[str] = field(default_factory=list)
    knowledge_ids: List[str] = field(default_factory=list)
    organization_ids: List[str] = field(default_factory=list)
    conflict_ids: List[str] = field(default_factory=list)
    specific_tags: List[str] = field(default_factory=list)
    stage: str = "emerging"
    escalation_level: int = 0
    repetition_count: int = 0
    last_major_event_day: int = 0
    event_type_counts: Dict[str, int] = field(default_factory=dict)


@dataclass
class Commission:
    id: str
    thread_id: str
    giver_id: str
    title: str
    description: str
    reward: int
    published_day: int
    active: bool = True


Task = Commission


__all__ = [
    "ActionCheckResult", "CaseFile", "Commission", "Commitment", "Config",
    "EventLevel", "Faction", "GAME_EVENT_TYPES", "IncidentReport", "Memory",
    "NPC", "NPCLayer", "Observation", "PHASES", "Phase", "PhasePlan",
    "Relationship", "Report", "ResponseDrive", "Scene", "SimEvent",
    "SocialInvitation", "StateDelta", "StoryThread", "Task", "WorldConflict",
    "WorldObject",
]
