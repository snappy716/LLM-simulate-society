"""Versioned, checksummed checkpoints for the new simulation kernel."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from simulation.domain.world_state import WorldState
from simulation.persistence.snapshot import atomic_write_json
from simulation.systems.randomness import DeterministicRngPool


KERNEL_CHECKPOINT_VERSION = 1
KERNEL_CHECKPOINT_FORMAT = "campus-kernel"


class CheckpointError(ValueError):
    pass


@dataclass(frozen=True)
class LoadedCheckpoint:
    state: WorldState
    rng: DeterministicRngPool
    content_manifest: Dict[str, Dict[str, Any]]


def _canonical_bytes(payload: Dict[str, Any]) -> bytes:
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _checksum(payload: Dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def build_kernel_checkpoint(
    state: WorldState,
    rng: DeterministicRngPool,
    *,
    content_manifest: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    state.require_valid()
    if state.master_seed != rng.master_seed:
        raise CheckpointError("world state and RNG master seeds differ")
    body: Dict[str, Any] = {
        "checkpoint_format": KERNEL_CHECKPOINT_FORMAT,
        "kernel_checkpoint_version": KERNEL_CHECKPOINT_VERSION,
        "world": state.to_dict(),
        "rng": rng.snapshot(),
        "content": {
            "version": state.content_version,
            "manifest": deepcopy(content_manifest or {}),
        },
    }
    return {**body, "checksum": _checksum(body)}


def save_kernel_checkpoint(
    path: Path,
    state: WorldState,
    rng: DeterministicRngPool,
    *,
    content_manifest: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    payload = build_kernel_checkpoint(
        state, rng, content_manifest=content_manifest
    )
    atomic_write_json(path, payload)
    return payload


def load_kernel_checkpoint(
    path: Path,
    *,
    expected_content_version: Optional[str] = None,
) -> LoadedCheckpoint:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CheckpointError(f"cannot read checkpoint: {exc}") from exc
    if not isinstance(payload, dict):
        raise CheckpointError("checkpoint root must be an object")
    if payload.get("checkpoint_format") != KERNEL_CHECKPOINT_FORMAT:
        raise CheckpointError("unsupported checkpoint format")
    if payload.get("kernel_checkpoint_version") != KERNEL_CHECKPOINT_VERSION:
        raise CheckpointError(
            f"unsupported kernel checkpoint version: {payload.get('kernel_checkpoint_version')}"
        )
    stored_checksum = payload.get("checksum")
    body = {key: value for key, value in payload.items() if key != "checksum"}
    if not isinstance(stored_checksum, str) or stored_checksum != _checksum(body):
        raise CheckpointError("checkpoint checksum mismatch")
    try:
        state = WorldState.from_dict(payload["world"])
        rng = DeterministicRngPool.from_snapshot(payload["rng"])
        content = payload["content"]
        content_version = str(content["version"])
        manifest = deepcopy(content.get("manifest", {}))
    except (KeyError, TypeError, ValueError) as exc:
        raise CheckpointError(f"invalid checkpoint payload: {exc}") from exc
    if state.master_seed != rng.master_seed:
        raise CheckpointError("checkpoint world and RNG master seeds differ")
    if state.content_version != content_version:
        raise CheckpointError("checkpoint world and content versions differ")
    if expected_content_version is not None and content_version != expected_content_version:
        raise CheckpointError(
            f"content version mismatch: save={content_version}, current={expected_content_version}"
        )
    if not isinstance(manifest, dict):
        raise CheckpointError("content manifest must be an object")
    return LoadedCheckpoint(state=state, rng=rng, content_manifest=manifest)


__all__ = [
    "CheckpointError",
    "KERNEL_CHECKPOINT_FORMAT",
    "KERNEL_CHECKPOINT_VERSION",
    "LoadedCheckpoint",
    "build_kernel_checkpoint",
    "load_kernel_checkpoint",
    "save_kernel_checkpoint",
]
