"""Story-thread compatibility boundary."""

from simulation.runtime import (
    find_related_thread,
    narrative_score,
    update_story_threads_from_events,
)

__all__ = ["find_related_thread", "narrative_score", "update_story_threads_from_events"]
