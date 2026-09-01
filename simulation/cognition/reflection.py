"""Belief-update and reflection boundary."""


def update_beliefs_from_events(*args, **kwargs):
    from simulation.runtime import update_beliefs_from_events as implementation
    return implementation(*args, **kwargs)


__all__ = ["update_beliefs_from_events"]
