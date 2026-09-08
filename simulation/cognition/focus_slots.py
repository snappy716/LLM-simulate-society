"""Budgeted LLM focus allocation without making an LLM authoritative state."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional


@dataclass(frozen=True)
class FocusCandidate:
    npc_id: str
    player_awakened: bool = False
    active_task_score: float = 0
    night_action_score: float = 0
    world_relevance_score: float = 0

    @property
    def priority(self) -> float:
        return (
            self.active_task_score * 1.2
            + self.night_action_score
            + self.world_relevance_score
        )


class FocusSlotAllocator:
    def __init__(self, total_slots: int = 20, permanent_player_slots: int = 0) -> None:
        if total_slots < 1 or permanent_player_slots < 0:
            raise ValueError("invalid focus slot budget")
        self.total_slots = total_slots
        self.permanent_player_slots = permanent_player_slots
        self._awakened_ids: List[str] = []

    @property
    def awakened_ids(self) -> tuple[str, ...]:
        return tuple(self._awakened_ids)

    def awaken(self, npc_id: str) -> None:
        if npc_id in self._awakened_ids:
            return
        if self.permanent_player_slots and len(self._awakened_ids) >= self.permanent_player_slots:
            raise ValueError("no permanent player focus slots remain")
        self._awakened_ids.append(npc_id)

    def allocate(self, candidates: Iterable[FocusCandidate], base_ids: Iterable[str] = ()) -> List[str]:
        by_id: Dict[str, FocusCandidate] = {candidate.npc_id: candidate for candidate in candidates}
        selected = list(self._awakened_ids)
        base = [npc_id for npc_id in dict.fromkeys(base_ids) if npc_id in by_id and npc_id not in selected][:self.total_slots]
        remaining = self.total_slots - len(base)
        ranked = sorted(
            (candidate for npc_id, candidate in by_id.items() if npc_id not in selected and npc_id not in base),
            key=lambda candidate: (-candidate.priority, candidate.npc_id),
        )
        selected.extend(base)
        selected.extend(candidate.npc_id for candidate in ranked[:remaining])
        return selected


__all__ = ["FocusCandidate", "FocusSlotAllocator"]
