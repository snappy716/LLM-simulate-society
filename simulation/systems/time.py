"""Time-system boundary."""

from simulation.domain.entities import PHASES, Phase


def next_phase(phase: Phase) -> tuple[Phase, bool]:
    """Return the next phase and whether the day rolled over."""
    index = PHASES.index(phase)
    if index == len(PHASES) - 1:
        return PHASES[0], True
    return PHASES[index + 1], False


__all__ = ["PHASES", "Phase", "next_phase"]
