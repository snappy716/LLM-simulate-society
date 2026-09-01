"""Lifecycle and aggregation for temporary and equipment-bound item effects."""
from __future__ import annotations

import uuid

from simulation.domain.item_use import ActiveItemEffect


PHASE_INDEX={"morning":0,"afternoon":1,"evening":2,"late_night":3}


class ItemEffectSystem:
    @staticmethod
    def time_index(world) -> int:
        return (world.day-1)*4+PHASE_INDEX[world.phase.value]

    @staticmethod
    def records(world,actor_id):
        return world.player_item_effect_records if actor_id=="player" else world.npcs[actor_id].item_effect_records

    @staticmethod
    def aggregate(world,actor_id):
        return world.player_item_effects if actor_id=="player" else world.npcs[actor_id].item_effects

    def grant(self,world,*,actor_id: str,source_item_id: str,effects: dict[str,int],
              source_instance_id: str | None = None,duration_phases: int = 0,
              remaining_uses: int = 0,requires_equipped: bool = False):
        records=self.records(world,actor_id)
        now=self.time_index(world)
        expires_at=now+duration_phases if duration_phases>0 else None
        granted=[]
        for effect,value in effects.items():
            # Reusing the same preparation refreshes it instead of stacking it.
            records[:]=[
                record for record in records
                if not (record.effect==effect and record.source_item_id==source_item_id
                        and record.source_instance_id==source_instance_id)
            ]
            record=ActiveItemEffect(
                id=f"effect_{uuid.uuid4().hex[:10]}",actor_id=actor_id,
                effect=effect,value=int(value),source_item_id=source_item_id,
                source_instance_id=source_instance_id,started_at=now,
                expires_at=expires_at,remaining_uses=max(0,int(remaining_uses)),
                requires_equipped=requires_equipped)
            records.append(record); granted.append(record)
        self.recompute(world,actor_id)
        return granted

    def remove_source(self,world,actor_id: str,source_instance_id: str):
        records=self.records(world,actor_id)
        removed=[record for record in records if record.source_instance_id==source_instance_id]
        records[:]=[record for record in records if record.source_instance_id!=source_instance_id]
        self.recompute(world,actor_id)
        return removed

    def expire(self,world):
        now=self.time_index(world); expired=[]
        for actor_id in ["player",*world.npcs.keys()]:
            records=self.records(world,actor_id)
            removed=[record for record in records
                     if record.expires_at is not None and now>=record.expires_at]
            if removed:
                records[:]=[record for record in records if record not in removed]
                expired.extend(removed)
                self.recompute(world,actor_id)
        return expired

    def consume_charge(self,world,actor_id: str,effect_names: list[str]):
        records=self.records(world,actor_id)
        candidates=[record for record in records
                    if record.effect in effect_names and record.remaining_uses>0]
        if not candidates:
            return []
        strongest=max(candidates,key=lambda record:record.value)
        strongest.remaining_uses-=1
        if strongest.remaining_uses<=0:
            records.remove(strongest)
        self.recompute(world,actor_id)
        return [strongest.id]

    def recompute(self,world,actor_id: str):
        aggregate=self.aggregate(world,actor_id)
        aggregate.clear()
        for record in self.records(world,actor_id):
            aggregate[record.effect]=max(aggregate.get(record.effect,0),record.value)


__all__=["ItemEffectSystem","PHASE_INDEX"]
