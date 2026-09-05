"""Campus simulation package; old prototype imports are explicit and lazy."""

def __getattr__(name):
    if name in {"Config", "Phase", "World"}:
        from simulation import runtime
        return getattr(runtime, name)
    raise AttributeError(name)
