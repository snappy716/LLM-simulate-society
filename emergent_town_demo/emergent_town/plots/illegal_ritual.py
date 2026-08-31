from __future__ import annotations

import uuid
from typing import Dict, List, Optional

from ..models import OperationPlan, OperationStage, TraceEvidence


class IllegalRitualEngine:
    STAGES = [
        ("select_target", ["SELECT_RITUAL_TARGET"]),
        ("collect_materials", ["COLLECT_RITUAL_MATERIALS"]),
        ("prepare_site", ["PREPARE_RITUAL_SITE"]),
        ("perform_ritual", ["PERFORM_SECRET_RITUAL"]),
        ("cleanup_or_escape", ["CLEAN_TRACE_OR_ESCAPE"]),
    ]

    def __init__(self):
        self.operations: Dict[str, OperationPlan] = {}
        self.traces: Dict[str, TraceEvidence] = {}

    def create_operation(self, *, faction_id: str, leader_id: str,
                         participant_ids: List[str], scene_id: str,
                         scheduled_day: int, scheduled_phase: str = "late_night") -> OperationPlan:
        operation = OperationPlan(
            id=f"operation_{uuid.uuid4().hex[:10]}", module_id="illegal_ritual",
            owner_faction_id=faction_id, objective="perform_illegal_ritual",
            leader_id=leader_id, participant_ids=list(dict.fromkeys(participant_ids)),
            scene_id=scene_id, scheduled_day=scheduled_day, scheduled_phase=scheduled_phase,
            stages=[OperationStage(stage_id, required) for stage_id, required in self.STAGES])
        self.operations[operation.id] = operation
        return operation

    def active(self) -> List[OperationPlan]:
        return [operation for operation in self.operations.values() if operation.status == "active"]

    def advance(self, operation: OperationPlan, *, day: int, phase: str,
                action_id: str, actor_ids: List[str], outcome: str) -> Optional[TraceEvidence]:
        stage = operation.current_stage
        if not stage or action_id not in stage.required_actions:
            return None
        if outcome in ("complete_success", "success"):
            stage.completed_actions.append(action_id)
        operation.exposure = min(100, operation.exposure + {
            "complete_success": 4, "success": 10, "partial": 22,
            "failure": 35, "critical_failure": 55}.get(outcome, 20))
        trace = TraceEvidence(
            id=f"trace_evidence_{uuid.uuid4().hex[:10]}",
            trace_type={
                "select_target":"suspicious_inquiry", "collect_materials":"ritual_purchase_record",
                "prepare_site":"ritual_marking", "perform_ritual":"spiritual_residue",
                "cleanup_or_escape":"disturbed_scene"}.get(stage.id, "suspicious_trace"),
            scene_id=operation.scene_id, created_day=day, created_phase=phase,
            source_action_id=action_id, source_actor_ids=actor_ids,
            discoverability=min(95, 20 + operation.exposure),
            occult=stage.id in ("prepare_site", "perform_ritual"),
            payload={"operation_id":operation.id, "stage":stage.id})
        self.traces[trace.id] = trace
        if stage.complete:
            stage.status = "completed"
            operation.current_stage_index += 1
            operation.last_progress_day = day
            if operation.current_stage is None:
                operation.status = "completed"
                operation.completed_day = day
            else:
                operation.current_stage.status = "active"
        return trace

    def discoverable_at(self, scene_id: str):
        return [trace for trace in self.traces.values()
                if trace.scene_id == scene_id and not trace.destroyed]
