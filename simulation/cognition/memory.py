"""NPC memory-write boundary."""


def write_memories_from_events(*args, **kwargs):
    from simulation.runtime import write_memories_from_events as implementation
    return implementation(*args, **kwargs)


__all__ = ["write_memories_from_events"]
