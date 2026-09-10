"""Allowlisted content-only migration; never repairs or rewrites player saves."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path


def migrate_campus_content(loaded, expected_version):
    from simulation.persistence.kernel_checkpoint import CheckpointError, LoadedCheckpoint

    event_spec = json.loads(Path(__file__).with_name("campus_events_content.json").read_text(encoding="utf-8"))
    if expected_version == event_spec["target_version"]:
        if loaded.state.content_version != event_spec["source_version"]:
            loaded = migrate_campus_content(loaded, event_spec["source_version"])
        if loaded.content_manifest != event_spec["source_manifest"]:
            raise CheckpointError("campus events migration manifest mismatch")
        migrated = loaded.state.clone()
        life = migrated.situations.get("campus_life", {})
        if life.get("definitions") != event_spec["source_definitions"]:
            raise CheckpointError("campus events source definitions mismatch")
        if any(sid.split(":")[-1] not in event_spec["source_definitions"] for sid in life.get("records", {})):
            raise CheckpointError("legacy save unexpectedly contains event participation")
        life["definitions"] = deepcopy(event_spec["definitions"])
        life["events_available_from"] = {"day": migrated.clock.day, "phase": migrated.clock.phase}
        from simulation.systems.campus_life import life_invariant
        if list(life_invariant(migrated)):
            raise CheckpointError("invalid migrated campus events ledger")
        migrated.content_version = expected_version
        migrated.require_valid()
        return LoadedCheckpoint(migrated, loaded.rng.clone(), deepcopy(event_spec["target_manifest"]),
                                loaded.migrations + (event_spec["migration_id"],))

    study_spec = json.loads(Path(__file__).with_name("campus_courses_jobs_content.json").read_text(encoding="utf-8"))
    if expected_version == study_spec["target_version"]:
        if loaded.state.content_version != study_spec["source_version"]:
            loaded = migrate_campus_content(loaded, study_spec["source_version"])
        if loaded.content_manifest != study_spec["source_manifest"]:
            raise CheckpointError("campus courses/jobs migration manifest mismatch")
        migrated = loaded.state.clone()
        life = migrated.situations.get("campus_life", {})
        if life.get("definitions") != study_spec["source_definitions"]:
            raise CheckpointError("campus courses/jobs source definitions mismatch")
        if any(sid.split(":")[-1] not in study_spec["source_definitions"] for sid in life.get("records", {})):
            raise CheckpointError("legacy save unexpectedly contains course/job attendance")
        life["definitions"] = deepcopy(study_spec["definitions"])
        from simulation.systems.campus_life import life_invariant
        if list(life_invariant(migrated)):
            raise CheckpointError("invalid migrated campus courses/jobs ledger")
        migrated.content_version = expected_version
        migrated.require_valid()
        return LoadedCheckpoint(migrated, loaded.rng.clone(), deepcopy(study_spec["target_manifest"]),
                                loaded.migrations + (study_spec["migration_id"],))

    life_spec = json.loads(Path(__file__).with_name("campus_life_content.json").read_text(encoding="utf-8"))
    if expected_version == life_spec["target_version"]:
        if loaded.state.content_version != life_spec["source_version"]:
            loaded = migrate_campus_content(loaded, life_spec["source_version"])
        if loaded.content_manifest != life_spec["source_manifest"]:
            raise CheckpointError("campus life migration manifest mismatch")
        migrated = loaded.state.clone()
        if "campus_life" in migrated.situations:
            raise CheckpointError("legacy save unexpectedly contains campus life ledger")
        from simulation.systems.campus_life import install_life
        install_life(migrated, life_spec["definitions"])
        migrated.content_version = expected_version
        migrated.require_valid()
        return LoadedCheckpoint(migrated, loaded.rng.clone(), deepcopy(life_spec["target_manifest"]),
                                loaded.migrations + (life_spec["migration_id"],))

    field_spec = json.loads(Path(__file__).with_name("campus_field_content.json").read_text(encoding="utf-8"))
    sites_spec = json.loads(Path(__file__).with_name("campus_night_sites_content.json").read_text(encoding="utf-8"))
    friend_spec = json.loads(Path(__file__).with_name("campus_friend_content.json").read_text(encoding="utf-8"))
    if expected_version == friend_spec["target_version"]:
        if loaded.state.content_version != friend_spec["source_version"]:
            loaded = migrate_campus_content(loaded, friend_spec["source_version"])
        if loaded.content_manifest != friend_spec["source_manifest"]:
            raise CheckpointError("friend cognition content migration manifest mismatch")
        migrated = loaded.state.clone()
        migrated.content_version = expected_version
        migrated.require_valid()
        return LoadedCheckpoint(migrated, loaded.rng.clone(), deepcopy(friend_spec["target_manifest"]),
                                loaded.migrations + (friend_spec["migration_id"],))
    if expected_version == sites_spec["target_version"]:
        # Traverse only the explicit frozen previous edge, not an arbitrary old
        # version or a moving alias. Existing victims/sites are never invented.
        if loaded.state.content_version == field_spec["source_version"]:
            loaded = migrate_campus_content(loaded, field_spec["target_version"])
        if (loaded.state.content_version == sites_spec["source_version"]
                and loaded.content_manifest == sites_spec["source_manifest"]):
            if (len(loaded.state.population) != 201 or "player" not in loaded.state.population
                    or loaded.state.inventories.get("schema_version") != 1):
                raise CheckpointError("night site migration requires a full campus save")
            migrated = loaded.state.clone()
            migrated.content_version = expected_version
            migrated.require_valid()
            return LoadedCheckpoint(migrated, loaded.rng.clone(), deepcopy(sites_spec["target_manifest"]),
                                    loaded.migrations + (sites_spec["migration_id"],))
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
