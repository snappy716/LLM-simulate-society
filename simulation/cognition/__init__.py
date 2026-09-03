"""NPC cognition boundary: planning contracts and future model adapters."""

from simulation.cognition.contracts import build_plan_schema
from simulation.cognition.dialogue import information_share_score, resolve_interaction
from simulation.cognition.memory import write_memories_from_events
from simulation.cognition.observation import create_observations, pending_report_observations
from simulation.cognition.reflection import update_beliefs_from_events
from simulation.cognition.focus_slots import FocusCandidate, FocusSlotAllocator

__all__ = [
    "build_plan_schema",
    "FocusCandidate",
    "FocusSlotAllocator",
    "create_observations",
    "information_share_score",
    "pending_report_observations",
    "resolve_interaction",
    "update_beliefs_from_events",
    "write_memories_from_events",
]
