"""Dialogue and information-exchange boundary."""


def resolve_interaction(*args, **kwargs):
    from simulation.runtime import resolve_interaction as implementation
    return implementation(*args, **kwargs)


def information_share_score(*args, **kwargs):
    from simulation.runtime import legacy_information_share_score as implementation
    return implementation(*args, **kwargs)


__all__ = ["information_share_score", "resolve_interaction"]
