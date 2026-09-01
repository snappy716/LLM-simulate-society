"""Long-term goal and main-story anchor boundary."""


def add_long_term_goal(*args, **kwargs):
    from simulation.runtime import add_long_term_goal as implementation
    return implementation(*args, **kwargs)


def sync_long_term_goals(*args, **kwargs):
    from simulation.runtime import sync_long_term_goals as implementation
    return implementation(*args, **kwargs)


__all__ = ["add_long_term_goal", "sync_long_term_goals"]
