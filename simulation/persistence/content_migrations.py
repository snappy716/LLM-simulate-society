"""Allowlisted content-only migration; never repairs or rewrites player saves."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path


def migrate_campus_content(loaded, expected_version):
    from simulation.persistence.kernel_checkpoint import CheckpointError, LoadedCheckpoint

    field_spec = json.loads(Path(__file__).with_name("campus_field_content.json").read_text(encoding="utf-8"))
    if (loaded.state.content_version == field_spec["source_version"]
            and expected_version == field_spec["target_version"]
            and loaded.content_manifest == field_spec["source_manifest"]):
        if (len(loaded.state.population) != 201 or "player" not in loaded.state.population
                or loaded.state.inventories.get("schema_version") != 1):
            raise CheckpointError("field content migration requires a full campus save")
        # Existing task contracts and ongoing battles remain exactly as saved.
        # Only subsequently published recon jobs create physical sites. Never
        # fabricate readings, reports, rewards or RNG draws for earlier jobs.
        migrated = loaded.state.clone()
        migrated.content_version = expected_version
        migrated.require_valid()
        return LoadedCheckpoint(migrated, loaded.rng.clone(), deepcopy(field_spec["target_manifest"]),
                                loaded.migrations + (field_spec["migration_id"],))

    # Historical content-only split, not a moving alias to current content.
    # Later gameplay/schema changes need their own explicit transformations.
    spec = json.loads(Path(__file__).with_name("campus_content_split.json").read_text(encoding="utf-8"))
    if (loaded.state.content_version != spec["source_version"]
            or expected_version != spec["target_version"]
            or loaded.content_manifest != spec["source_manifest"]):
        raise CheckpointError(
            "content version mismatch: no approved migration for this save and current content"
        )
    state = loaded.state
    inventory = state.inventories
    if ("player" not in state.population or len(state.population) != 201
            or inventory.get("schema_version") != 1
            or sorted(inventory.get("catalog", {})) != spec["item_ids"]
            or not inventory.get("trade") or not inventory.get("supply")):
        raise CheckpointError("content migration requires an existing full campus resource save")
    # Only the content identity changes. NPCs, stock, wallet, events, intentions,
    # journals, health, clock, RNG and idempotency records stay exactly as saved.
    migrated = state.clone()
    migrated.content_version = expected_version
    migrated.require_valid()
    return LoadedCheckpoint(
        migrated, loaded.rng.clone(), deepcopy(spec["target_manifest"]),
        loaded.migrations + (spec["migration_id"],),
    )
