"""Godot-facing API boundary with a lazy server import."""
from __future__ import annotations


def __getattr__(name: str):
    if name == "SimulationBridge":
        from simulation.api.server import SimulationBridge
        return SimulationBridge
    raise AttributeError(name)

__all__ = ["SimulationBridge"]
