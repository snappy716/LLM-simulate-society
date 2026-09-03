"""Task-board entities for fair player/NPC competition."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class ForumKind(str, Enum):
    SURFACE = "surface"
    NIGHT = "night"


class TaskState(str, Enum):
    OPEN = "open"
    VIEWED = "viewed"
    CONSIDERING = "considering"
    LOCKED = "locked"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    ABANDONED = "abandoned"
    EXPIRED = "expired"


TERMINAL_TASK_STATES = {
    TaskState.COMPLETED, TaskState.FAILED, TaskState.ABANDONED, TaskState.EXPIRED,
}


@dataclass
class CampusTask:
    task_id: str
    forum: ForumKind
    issuer_id: str
    title: str
    action_id: str
    scene_id: str
    created_day: int
    expires_day: int
    state: TaskState = TaskState.OPEN
    assignee_id: Optional[str] = None
    lock_revision: int = 0
    viewer_ids: List[str] = field(default_factory=list)
    considering_ids: List[str] = field(default_factory=list)
    helper_ids: List[str] = field(default_factory=list)
    required_skill_ids: List[str] = field(default_factory=list)
    required_item_ids: List[str] = field(default_factory=list)
    reward: Dict[str, int] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.task_id or not self.issuer_id or not self.action_id or not self.scene_id:
            raise ValueError("task_id, issuer_id, action_id, and scene_id are required")
        if self.created_day < 1 or self.expires_day < self.created_day:
            raise ValueError("invalid task date range")
        if self.state in {TaskState.LOCKED, TaskState.IN_PROGRESS} and not self.assignee_id:
            raise ValueError("locked and active tasks require an assignee")


__all__ = ["ForumKind", "TaskState", "TERMINAL_TASK_STATES", "CampusTask"]
