"""Version gate for persisted API snapshots."""
from __future__ import annotations

from copy import deepcopy


CURRENT_SCHEMA_VERSION = 2


def migrate_snapshot(payload: dict) -> dict:
    """Return an isolated current-version snapshot or reject unknown versions."""
    version = payload.get("schema_version", 1)
    if version not in {1,CURRENT_SCHEMA_VERSION}:
        raise ValueError(f"unsupported snapshot schema version: {version}")
    result = deepcopy(payload)
    if version==1:
        result.setdefault("item_instances",{})
        result.setdefault("scene_inventories",{})
        result.setdefault("container_inventories",{})
    result["schema_version"] = CURRENT_SCHEMA_VERSION
    return result


__all__ = ["CURRENT_SCHEMA_VERSION", "migrate_snapshot"]
