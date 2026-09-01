"""Append-only event and trace logging."""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from simulation.domain.entities import GAME_EVENT_TYPES


class TraceLedger:
    def __init__(self, log_dir: Path):
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        (self.log_dir / "npc_history").mkdir(exist_ok=True)
        (self.log_dir / "story_threads").mkdir(exist_ok=True)
        (self.log_dir / "llm").mkdir(exist_ok=True)
        self.trace_jsonl = self.log_dir / "trace.jsonl"
        self.world_log = self.log_dir / "world_history.log"
        self.game_events_jsonl = self.log_dir / "game_events.jsonl"
        self.trace_jsonl.write_text("", encoding="utf-8")
        self.world_log.write_text("", encoding="utf-8")
        self.game_events_jsonl.write_text("", encoding="utf-8")

    def emit(
        self,
        *,
        day,
        phase,
        system,
        event_type,
        message,
        actor_ids=None,
        scene_id=None,
        payload=None,
        trace_id=None,
        parent_id=None,
    ):
        event_id = f"evt_{uuid.uuid4().hex[:12]}"
        trace_id = trace_id or f"trace_{uuid.uuid4().hex[:10]}"
        record = {
            "event_id": event_id,
            "trace_id": trace_id,
            "parent_id": parent_id,
            "day": day,
            "phase": phase,
            "system": system,
            "event_type": event_type,
            "actor_ids": actor_ids or [],
            "scene_id": scene_id,
            "message": message,
            "payload": payload or {},
            "wall_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        with self.trace_jsonl.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        if event_type in GAME_EVENT_TYPES:
            game_record = {
                key: record[key]
                for key in (
                    "event_id", "parent_id", "day", "phase", "event_type",
                    "actor_ids", "scene_id", "message", "payload",
                )
            }
            with self.game_events_jsonl.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(game_record, ensure_ascii=False) + "\n")

        line = f"[Day {day:02d} | {phase:<16} | {system:<18} | {event_type:<24}] {message}"
        if scene_id:
            line += f" @ {scene_id}"
        if actor_ids:
            line += f" | actors={','.join(actor_ids)}"
        line += f" | event={event_id} trace={trace_id}"
        if parent_id:
            line += f" parent={parent_id}"
        line += "\n"

        with self.world_log.open("a", encoding="utf-8") as stream:
            stream.write(line)
        for npc_id in actor_ids or []:
            with (self.log_dir / "npc_history" / f"{npc_id}.log").open(
                "a", encoding="utf-8"
            ) as stream:
                stream.write(line)
        return record

    def log_story_line(self, thread_id: str, line: str) -> None:
        path = self.log_dir / "story_threads" / f"{thread_id}.log"
        with path.open("a", encoding="utf-8") as stream:
            stream.write(line.rstrip() + "\n")


__all__ = ["TraceLedger"]
