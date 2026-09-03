"""Thread-safe task state transitions shared by surface and night forums."""
from __future__ import annotations

import threading
from copy import deepcopy
from typing import Dict, Iterable

from simulation.domain.tasks import CampusTask, TaskState, TERMINAL_TASK_STATES


class TaskConflictError(RuntimeError):
    pass


class TaskBoard:
    """In-memory reference service; persistence adapters store its event stream."""

    def __init__(self, tasks: Iterable[CampusTask] = ()) -> None:
        self._tasks: Dict[str, CampusTask] = {}
        self._lock = threading.RLock()
        for task in tasks:
            self.publish(task)

    def publish(self, task: CampusTask) -> CampusTask:
        with self._lock:
            if task.task_id in self._tasks:
                raise ValueError(f"duplicate task: {task.task_id}")
            self._tasks[task.task_id] = deepcopy(task)
            return deepcopy(self._tasks[task.task_id])

    def get(self, task_id: str) -> CampusTask:
        with self._lock:
            if task_id not in self._tasks:
                raise KeyError(task_id)
            return deepcopy(self._tasks[task_id])

    def view(self, task_id: str, actor_id: str) -> CampusTask:
        with self._lock:
            task = self._required(task_id)
            if actor_id not in task.viewer_ids:
                task.viewer_ids.append(actor_id)
            if task.state == TaskState.OPEN:
                task.state = TaskState.VIEWED
            return deepcopy(task)

    def consider(self, task_id: str, actor_id: str) -> CampusTask:
        with self._lock:
            task = self._required(task_id)
            if task.state in TERMINAL_TASK_STATES or task.assignee_id:
                raise TaskConflictError("task is no longer available")
            if actor_id not in task.considering_ids:
                task.considering_ids.append(actor_id)
            task.state = TaskState.CONSIDERING
            return deepcopy(task)

    def claim(self, task_id: str, actor_id: str, *, expected_revision: int) -> CampusTask:
        """Atomically claim only the exact version the caller evaluated."""
        with self._lock:
            task = self._required(task_id)
            if task.lock_revision != expected_revision:
                raise TaskConflictError("task changed while actor was deciding")
            if task.state in TERMINAL_TASK_STATES or task.assignee_id:
                raise TaskConflictError("task is no longer available")
            task.assignee_id = actor_id
            task.state = TaskState.LOCKED
            task.lock_revision += 1
            return deepcopy(task)

    def start(self, task_id: str, actor_id: str) -> CampusTask:
        with self._lock:
            task = self._required(task_id)
            self._require_assignee(task, actor_id)
            if task.state != TaskState.LOCKED:
                raise TaskConflictError("only a locked task can start")
            task.state = TaskState.IN_PROGRESS
            task.lock_revision += 1
            return deepcopy(task)

    def finish(self, task_id: str, actor_id: str, *, success: bool) -> CampusTask:
        with self._lock:
            task = self._required(task_id)
            self._require_assignee(task, actor_id)
            if task.state != TaskState.IN_PROGRESS:
                raise TaskConflictError("only an active task can finish")
            task.state = TaskState.COMPLETED if success else TaskState.FAILED
            task.lock_revision += 1
            return deepcopy(task)

    def abandon(self, task_id: str, actor_id: str, *, reopen: bool = True) -> CampusTask:
        with self._lock:
            task = self._required(task_id)
            self._require_assignee(task, actor_id)
            task.assignee_id = None
            task.state = TaskState.OPEN if reopen else TaskState.ABANDONED
            task.lock_revision += 1
            return deepcopy(task)

    def expire(self, current_day: int) -> list[CampusTask]:
        changed = []
        with self._lock:
            for task in self._tasks.values():
                if task.state not in TERMINAL_TASK_STATES and current_day > task.expires_day:
                    task.state = TaskState.EXPIRED
                    task.lock_revision += 1
                    changed.append(deepcopy(task))
        return changed

    def snapshot(self) -> Dict[str, CampusTask]:
        with self._lock:
            return {task_id: deepcopy(task) for task_id, task in self._tasks.items()}

    def _required(self, task_id: str) -> CampusTask:
        if task_id not in self._tasks:
            raise KeyError(task_id)
        return self._tasks[task_id]

    @staticmethod
    def _require_assignee(task: CampusTask, actor_id: str) -> None:
        if task.assignee_id != actor_id:
            raise TaskConflictError("actor does not own the task lock")


__all__ = ["TaskBoard", "TaskConflictError"]
