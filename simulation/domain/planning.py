from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Desire:
    id: str
    strength: float
    reasons: List[str] = field(default_factory=list)
    target_id: Optional[str] = None
    expires_day: Optional[int] = None


@dataclass
class IntelFact:
    id: str
    subject_id: str
    predicate: str
    object_id: str
    day: int
    phase: str
    source_type: str
    source_id: Optional[str]
    confidence: float
    secrecy: int
    distortion: float = 0.0
    known_by: List[str] = field(default_factory=list)
    evidence_ids: List[str] = field(default_factory=list)
    contradicted_by: List[str] = field(default_factory=list)
    summary: str = ""
    recorded_by: List[str] = field(default_factory=list)
    record_source_instance_ids: Dict[str, str] = field(default_factory=dict)
    recall_confidence: Dict[str, float] = field(default_factory=dict)
    recall_distortion: Dict[str, float] = field(default_factory=dict)


@dataclass
class TraceEvidence:
    id: str
    trace_type: str
    scene_id: str
    created_day: int
    created_phase: str
    source_action_id: str
    source_actor_ids: List[str]
    discoverability: int
    occult: bool = False
    discovered_by: List[str] = field(default_factory=list)
    destroyed: bool = False
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LongTermGoal:
    id: str
    owner_id: str
    goal_type: str
    description: str
    priority: int
    status: str = "active"
    created_day: int = 1
    deadline_day: Optional[int] = None
    linked_plan_id: Optional[str] = None
    linked_case_id: Optional[str] = None
    progress: int = 0
    last_progress_day: int = 0
    outcome: Optional[str] = None


@dataclass
class OperationStage:
    id: str
    required_actions: List[str]
    completed_actions: List[str] = field(default_factory=list)
    status: str = "pending"

    @property
    def complete(self) -> bool:
        return all(action in self.completed_actions for action in self.required_actions)


@dataclass
class OperationPlan:
    id: str
    module_id: str
    owner_faction_id: str
    objective: str
    leader_id: str
    participant_ids: List[str]
    scene_id: str
    scheduled_day: int
    scheduled_phase: str
    stages: List[OperationStage]
    current_stage_index: int = 0
    exposure: int = 0
    status: str = "active"
    fallback_action: str = "FLEE_TO_SCENE"
    required_object_ids: List[str] = field(default_factory=list)
    result_event_ids: List[str] = field(default_factory=list)
    linked_goal_id: Optional[str] = None
    last_progress_day: int = 0
    completed_day: Optional[int] = None
    target_id: Optional[str] = None
    outcome_type: Optional[str] = None
    consequence_resolved: bool = False
    consequence_event_ids: List[str] = field(default_factory=list)
    spawned_character_ids: List[str] = field(default_factory=list)
    intervention_failures: int = 0

    @property
    def current_stage(self) -> Optional[OperationStage]:
        if 0 <= self.current_stage_index < len(self.stages):
            return self.stages[self.current_stage_index]
        return None


@dataclass
class PlannedAction:
    action_id: str
    scene_id: str
    target_id: Optional[str] = None
    object_id: Optional[str] = None
    condition: str = "always"
    intent: str = ""


@dataclass
class ShortPlan:
    goal: str
    desire_id: str
    steps: List[PlannedAction]
    created_day: int
    cursor: int = 0
    active: bool = True


@dataclass
class FollowupPlan:
    id: str
    template_id: str
    goal_id: str
    owner_id: str
    scene_id: str
    target_id: Optional[str]
    stages: List[OperationStage]
    current_stage_index: int = 0
    status: str = "active"
    created_day: int = 1
    last_progress_day: int = 0
    attempts: int = 0
    outcome_type: Optional[str] = None
    result_event_ids: List[str] = field(default_factory=list)

    @property
    def current_stage(self) -> Optional[OperationStage]:
        if 0 <= self.current_stage_index < len(self.stages):
            return self.stages[self.current_stage_index]
        return None
