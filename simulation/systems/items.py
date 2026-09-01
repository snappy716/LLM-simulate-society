"""Data-driven item-use validation and atomic state application."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Dict

from simulation.domain.item_use import ItemUseDefinition, ItemUseReceipt


class ItemUseSystem:
    VALID_MODES = {"consume", "prepare", "read", "contextual", "equip", "dangerous", "blocked"}

    def __init__(self, definitions: Dict[str, ItemUseDefinition]) -> None:
        self.definitions = definitions

    def definition(self, item_id: str) -> ItemUseDefinition | None:
        return self.definitions.get(item_id)

    def protected_quantity(self, npc, item_id: str) -> int:
        definition=self.definitions.get(item_id)
        if definition and npc.occupation in definition.protected_occupations:
            return 1
        return 0

    def use(self, world, *, actor_id: str, item_id: str, scene_id: str) -> ItemUseReceipt:
        item=world.item_catalog.get(item_id)
        definition=self.definitions.get(item_id)
        if item is None or definition is None:
            return self._failure("unknown_item","没有找到这种物品或对应使用规则。",actor_id,item_id)
        if actor_id!="player" and actor_id not in world.npcs:
            return self._failure("unknown_actor","使用者不存在。",actor_id,item_id)
        actor_scene=world.player_scene if actor_id=="player" else world.npcs[actor_id].current_scene
        if actor_scene!=scene_id:
            return self._failure("location_mismatch","使用者不在请求的地点。",actor_id,item_id,definition.mode)
        inventory=world.economy.actor_inventory(actor_id)
        if inventory.quantity(item_id)<1:
            return self._failure("item_missing",f"没有可使用的 {item.name}。",actor_id,item_id,definition.mode)
        if definition.mode=="blocked":
            return self._failure("requires_other_system",definition.blocked_reason,actor_id,item_id,definition.mode)
        if definition.mode=="equip":
            return self._failure(
                "requires_equip_action",f"{item.name} 必须通过 EQUIP_ITEM 行动装备。",
                actor_id,item_id,definition.mode)
        if definition.required_scenes and scene_id not in definition.required_scenes:
            return self._failure(
                "wrong_scene",f"{item.name} 只能在指定地点发挥作用。",actor_id,item_id,definition.mode)

        states,effects,equipped,knowledge,attributes=self._actor_state(world,actor_id)
        effect_records=world.item_effect_system.records(world,actor_id)
        before=(dict(inventory.quantities),deepcopy(states),deepcopy(effects),list(equipped),
                list(knowledge),dict(attributes),deepcopy(effect_records))
        state_changes={}
        knowledge_added=None
        try:
            for state_name,delta in definition.state_effects.items():
                old=int(states.get(state_name,0))
                new=max(0,min(100,old+int(delta)))
                states[state_name]=new
                state_changes[state_name]=new-old
            for attribute,delta in definition.attribute_effects.items():
                old=int(attributes.get(attribute,0))
                new=max(0,min(100,old+int(delta)))
                attributes[attribute]=new
                state_changes[attribute]=new-old
            if definition.grants_effects:
                source_instances=world.item_instances.instances_for(actor_id,item_id,world.day)
                source_instance_id=source_instances[0].id if source_instances else None
                world.item_effect_system.grant(
                    world,actor_id=actor_id,source_item_id=item_id,
                    source_instance_id=source_instance_id,effects=definition.grants_effects,
                    duration_phases=definition.duration_phases,
                    remaining_uses=definition.effect_charges)
            if definition.knowledge:
                rendered=definition.knowledge.format(day=world.day,scene_id=scene_id)
                if rendered not in knowledge:
                    knowledge.append(rendered)
                    knowledge_added=rendered
            if definition.consumes:
                inventory.remove(item_id,1)
            self._write_attributes(world,actor_id,attributes)
            errors=world.economy.validate_invariants(world)
            if errors:
                raise RuntimeError("; ".join(errors))
        except Exception:
            inventory.quantities=before[0]
            states.clear(); states.update(before[1])
            effects.clear(); effects.update(before[2])
            equipped[:]=before[3]
            knowledge[:]=before[4]
            self._write_attributes(world,actor_id,before[5])
            effect_records[:]=before[6]
            world.item_effect_system.recompute(world,actor_id)
            raise
        actor_name="玩家" if actor_id=="player" else world.npcs[actor_id].name
        verbs={"consume":"使用","prepare":"准备","read":"阅读","contextual":"使用",
               "equip":"装备","dangerous":"启动"}
        return ItemUseReceipt(
            True,"success",f"{actor_name}{verbs.get(definition.mode,'使用')}了 {item.name}。",
            actor_id,item_id,definition.mode,definition.consumes,
            False,state_changes,dict(definition.grants_effects),knowledge_added,
        )

    @staticmethod
    def _actor_state(world,actor_id):
        if actor_id=="player":
            return (world.player_states,world.player_item_effects,
                    world.player_equipped_item_ids,world.player_knowledge,
                    {"health":world.player_health,"sanity":world.player_sanity})
        npc=world.npcs[actor_id]
        return npc.states,npc.item_effects,npc.equipped_item_ids,npc.knowledge,{
            "health":npc.health,"sanity":npc.sanity,
        }

    @staticmethod
    def _write_attributes(world,actor_id,attributes):
        if actor_id=="player":
            world.player_health=int(attributes["health"])
            world.player_sanity=int(attributes["sanity"])
        else:
            world.npcs[actor_id].health=int(attributes["health"])
            world.npcs[actor_id].sanity=int(attributes["sanity"])

    @staticmethod
    def _failure(code,message,actor_id,item_id,mode=""):
        return ItemUseReceipt(False,code,message,actor_id,item_id,mode)


def load_item_uses(path: Path, catalog) -> Dict[str, ItemUseDefinition]:
    payload=json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version")!=1:
        raise ValueError("unsupported item-use content schema")
    definitions={}
    for raw in payload.get("uses",[]):
        definition=ItemUseDefinition(**raw)
        if definition.item_id in definitions:
            raise ValueError(f"duplicate item-use definition: {definition.item_id}")
        if definition.item_id not in catalog:
            raise ValueError(f"item-use definition references unknown item: {definition.item_id}")
        if definition.mode not in ItemUseSystem.VALID_MODES:
            raise ValueError(f"invalid item-use mode: {definition.item_id}")
        if definition.duration_phases<0 or definition.effect_charges<0:
            raise ValueError(f"invalid item-use duration or charges: {definition.item_id}")
        if definition.consumes and not catalog[definition.item_id].consumable:
            raise ValueError(f"non-consumable item configured for consumption: {definition.item_id}")
        definitions[definition.item_id]=definition
    missing=set(catalog)-set(definitions)
    extra=set(definitions)-set(catalog)
    if missing or extra:
        raise ValueError(f"item-use coverage mismatch: missing={sorted(missing)} extra={sorted(extra)}")
    return definitions


def initialize_item_uses(world,content_dir: Path) -> ItemUseSystem:
    definitions=load_item_uses(content_dir/"items"/"uses.json",world.item_catalog)
    return ItemUseSystem(definitions)


__all__=["ItemUseSystem","initialize_item_uses","load_item_uses"]
