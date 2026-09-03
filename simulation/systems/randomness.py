"""Deterministic named RNG streams with JSON-safe checkpoint state."""
from __future__ import annotations

import hashlib
import random
from copy import deepcopy
from typing import Any, Dict


def _lists_to_tuples(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(_lists_to_tuples(item) for item in value)
    return value


def _tuples_to_lists(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_tuples_to_lists(item) for item in value]
    return value


class DeterministicRngPool:
    """Keeps unrelated systems from perturbing each other's random sequence."""

    def __init__(self, master_seed: int, *, namespace: str = "campus-demo") -> None:
        if isinstance(master_seed, bool) or not isinstance(master_seed, int):
            raise TypeError("master_seed must be an integer")
        self.master_seed = master_seed
        self.namespace = namespace
        self._streams: Dict[str, random.Random] = {}

    def _seed_for(self, name: str) -> int:
        if not name:
            raise ValueError("RNG stream name must not be empty")
        digest = hashlib.sha256(
            f"{self.namespace}:{self.master_seed}:{name}".encode("utf-8")
        ).digest()
        return int.from_bytes(digest[:16], "big")

    def stream(self, name: str) -> random.Random:
        if name not in self._streams:
            self._streams[name] = random.Random(self._seed_for(name))
        return self._streams[name]

    def clone(self) -> "DeterministicRngPool":
        return self.from_snapshot(self.snapshot())

    def snapshot(self) -> Dict[str, Any]:
        return {
            "master_seed": self.master_seed,
            "namespace": self.namespace,
            "streams": {
                name: _tuples_to_lists(generator.getstate())
                for name, generator in sorted(self._streams.items())
            },
        }

    @classmethod
    def from_snapshot(cls, payload: Dict[str, Any]) -> "DeterministicRngPool":
        pool = cls(int(payload["master_seed"]), namespace=str(payload["namespace"]))
        for name, state in deepcopy(payload.get("streams", {})).items():
            generator = pool.stream(name)
            generator.setstate(_lists_to_tuples(state))
        return pool


__all__ = ["DeterministicRngPool"]
