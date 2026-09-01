"""Scheduled situations and persistent-operation advancement boundary."""


def fire_scheduled_phase_events(*args, **kwargs):
    from simulation.runtime import fire_scheduled_phase_events as implementation
    return implementation(*args, **kwargs)


def advance_illegal_operations(*args, **kwargs):
    from simulation.runtime import advance_illegal_operations as implementation
    return implementation(*args, **kwargs)


__all__ = ["advance_illegal_operations", "fire_scheduled_phase_events"]
