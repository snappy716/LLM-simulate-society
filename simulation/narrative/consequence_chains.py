from __future__ import annotations

import uuid
from typing import Dict, List, Optional

from simulation.domain.planning import FollowupPlan, OperationStage


class ConsequenceChainEngine:
    """Stores durable plans caused by the outcome of another plan."""

    TEMPLATES = {
        "hunt_ritual_leader": ["gather_escape_leads", "track_fugitive", "confront_fugitive"],
        "cleanse_occult_scene": ["secure_scene", "analyze_contamination", "cleanse_scene"],
        "collect_ritual_result": ["inspect_ritual_site", "recover_ritual_result", "erase_remaining_traces"],
        "rescue_arrested_member": ["gather_custody_intel", "infiltrate_custody", "free_prisoner"],
        "reinforce_ritual_case": ["review_failed_intervention", "prepare_second_assault", "stop_active_ritual"],
    }

    def __init__(self):
        self.plans: Dict[str, FollowupPlan] = {}

    def create(self, *, template_id: str, goal_id: str, owner_id: str,
               scene_id: str, target_id: Optional[str], created_day: int) -> FollowupPlan:
        stage_ids=self.TEMPLATES[template_id]
        plan=FollowupPlan(
            id=f"followup_{uuid.uuid4().hex[:10]}",template_id=template_id,
            goal_id=goal_id,owner_id=owner_id,scene_id=scene_id,target_id=target_id,
            stages=[OperationStage(stage_id,[stage_id.upper()]) for stage_id in stage_ids],
            created_day=created_day)
        if plan.current_stage:
            plan.current_stage.status="active"
        self.plans[plan.id]=plan
        return plan

    def active(self) -> List[FollowupPlan]:
        return [plan for plan in self.plans.values() if plan.status=="active"]

    def advance(self, plan: FollowupPlan, *, day: int, success: bool) -> None:
        plan.attempts += 1
        if not success:
            return
        stage=plan.current_stage
        if not stage:
            return
        stage.completed_actions=list(stage.required_actions)
        stage.status="completed"
        plan.current_stage_index += 1
        plan.last_progress_day=day
        if plan.current_stage is None:
            plan.status="completed"
        else:
            plan.current_stage.status="active"
