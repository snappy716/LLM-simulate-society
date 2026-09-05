"""Append-only event and trace logging."""
from __future__ import annotations

import json
import os
from pathlib import Path
import threading
from typing import Iterable

from simulation.domain.events import SimulationEvent


class KernelEventJournal:
    """Append-only event batches used by ``WorldKernel``.

    One committed transaction is stored as one JSON line.  Reopening a journal
    validates event ordering instead of truncating the previous session.
    """

    JOURNAL_VERSION = 1

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        self._lock = threading.RLock()
        existing = self.read_events()
        self._last_sequence = self._event_sequence(existing[-1]) if existing else 0

    def append_batch(self, events: Iterable[SimulationEvent]) -> None:
        batch = tuple(events)
        if not batch:
            return
        with self._lock:
            sequences = [self._event_sequence(event) for event in batch]
            if sequences != list(range(sequences[0], sequences[0] + len(sequences))):
                raise ValueError("event batch sequence is not contiguous")
            if self._last_sequence and sequences[0] != self._last_sequence + 1:
                raise ValueError("event journal sequence is not contiguous")
            record = {
                "journal_version": self.JOURNAL_VERSION,
                "first_sequence": sequences[0],
                "last_sequence": sequences[-1],
                "events": [event.to_dict() for event in batch],
            }
            encoded = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(encoded + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            self._last_sequence = sequences[-1]

    def read_events(self) -> list[SimulationEvent]:
        events: list[SimulationEvent] = []
        last_sequence = 0
        with self._lock:
            for line_number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                    if record.get("journal_version") != self.JOURNAL_VERSION:
                        raise ValueError("unsupported journal version")
                    batch = [SimulationEvent.from_dict(item) for item in record["events"]]
                except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise ValueError(f"invalid event journal line {line_number}: {exc}") from exc
                sequences = [self._event_sequence(event) for event in batch]
                if not sequences or sequences[0] != record.get("first_sequence") or sequences[-1] != record.get("last_sequence"):
                    raise ValueError(f"invalid event journal bounds on line {line_number}")
                if sequences != list(range(sequences[0], sequences[0] + len(sequences))):
                    raise ValueError(f"non-contiguous event batch on line {line_number}")
                if last_sequence and sequences[0] != last_sequence + 1:
                    raise ValueError(f"non-contiguous event journal on line {line_number}")
                events.extend(batch)
                last_sequence = sequences[-1]
        return events

    @staticmethod
    def _event_sequence(event: SimulationEvent) -> int:
        prefix, separator, raw = event.event_id.partition(":")
        if prefix != "evt" or separator != ":" or not raw.isdigit():
            raise ValueError(f"invalid kernel event id: {event.event_id}")
        return int(raw)


__all__ = ["KernelEventJournal"]
