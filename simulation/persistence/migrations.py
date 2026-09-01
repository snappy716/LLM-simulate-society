"""Version gate for persisted API snapshots."""
from __future__ import annotations

from copy import deepcopy


CURRENT_SCHEMA_VERSION = 1


def migrate_snapshot(payload: dict) -> dict:
    """Return an isolated current-version snapshot or reject unknown versions."""
    version = payload.get("schema_version", 1)
    if version != CURRENT_SCHEMA_VERSION:
        raise ValueError(f"unsupported snapshot schema version: {version}")
    result = deepcopy(payload)
    result["schema_version"] = CURRENT_SCHEMA_VERSION
    return result


__all__ = ["CURRENT_SCHEMA_VERSION", "migrate_snapshot"]
