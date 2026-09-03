"""Strict JSON adapter for the authoritative command boundary."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Dict

from simulation.actions.commands import CommandResult, SimulationCommand


COMMAND_CONTRACT_VERSION = 1
COMMAND_FIELDS = {
    "command_id",
    "actor_id",
    "action_id",
    "target_ids",
    "parameters",
    "expected_world_revision",
    "issued_day",
    "issued_phase",
    "issued_minute",
    "source",
}


@dataclass(frozen=True)
class CommandParseError(ValueError):
    code: str
    message: str

    def __str__(self) -> str:
        return self.message


def parse_simulation_command(payload: Dict[str, Any]) -> SimulationCommand:
    if not isinstance(payload, dict):
        raise CommandParseError("invalid_json_type", "command body must be an object")
    unknown = sorted(set(payload) - COMMAND_FIELDS)
    if unknown:
        raise CommandParseError(
            "unknown_fields", "command contains unknown fields: " + ", ".join(unknown)
        )
    missing = sorted(COMMAND_FIELDS - set(payload))
    if missing:
        raise CommandParseError(
            "missing_fields", "command is missing fields: " + ", ".join(missing)
        )
    try:
        return SimulationCommand.from_dict(deepcopy(payload))
    except (TypeError, ValueError) as exc:
        raise CommandParseError("invalid_command", str(exc)) from exc


def command_result_view(result: CommandResult) -> Dict[str, Any]:
    return {
        "contract_version": COMMAND_CONTRACT_VERSION,
        **result.to_dict(),
    }


__all__ = [
    "COMMAND_CONTRACT_VERSION",
    "CommandParseError",
    "command_result_view",
    "parse_simulation_command",
]
