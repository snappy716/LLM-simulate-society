"""Shared four-phase clock. Retired town entity classes are not exported."""
from enum import Enum


class Phase(str, Enum):
    MORNING = "morning"
    AFTERNOON = "afternoon"
    EVENING = "evening"
    LATE_NIGHT = "late_night"


PHASES = [Phase.MORNING, Phase.AFTERNOON, Phase.EVENING, Phase.LATE_NIGHT]
