"""Observation-system boundary for perception and reportable facts."""


def create_observations(*args, **kwargs):
    from simulation.runtime import create_observations as implementation
    return implementation(*args, **kwargs)


def pending_report_observations(*args, **kwargs):
    from simulation.runtime import pending_report_observations as implementation
    return implementation(*args, **kwargs)


__all__ = ["create_observations", "pending_report_observations"]
