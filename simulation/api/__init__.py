"""Godot-facing API boundary with a lazy server import."""
from __future__ import annotations

from simulation.api.commands import (
    COMMAND_CONTRACT_VERSION,
    CommandParseError,
    command_result_view,
    parse_simulation_command,
)
from simulation.api.views import (
    CAMPUS_WORLD_VIEW_VERSION,
    KERNEL_STATUS_VIEW_VERSION,
    campus_world_view,
    kernel_status_view,
)


def __getattr__(name: str):
    if name == "SimulationBridge":
        from simulation.api.server import SimulationBridge
        return SimulationBridge
    raise AttributeError(name)

__all__ = [
    "COMMAND_CONTRACT_VERSION",
    "CAMPUS_WORLD_VIEW_VERSION",
    "CommandParseError",
    "KERNEL_STATUS_VIEW_VERSION",
    "SimulationBridge",
    "command_result_view",
    "campus_world_view",
    "kernel_status_view",
    "parse_simulation_command",
]
