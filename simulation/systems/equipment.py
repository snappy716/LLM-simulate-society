"""Text-first equipment slots backed by stable item instances."""
from __future__ import annotations

from simulation.domain.item_use import EquipmentReceipt


SLOT_BY_ITEM={
    "walking_cane":"main_hand", "rusted_knife":"main_hand",
    "police_revolver":"main_hand", "padded_coat":"body",
    "leather_gloves":"hands", "silver_charm":"accessory",
    "blackthorn_badge":"identity",
}


class EquipmentSystem:
    def equip(self,world,*,actor_id: str,item_id: str,instance_id: str | None = None):
        action_id="EQUIP_ITEM"
        if not self._actor_exists(world,actor_id):
            return self._failure(action_id,actor_id,"unknown_actor","行动者不存在。",item_id)
        definition=world.item_catalog.get(item_id)
        use_definition=world.item_uses.definition(item_id)
        if definition is None or use_definition is None:
            return self._failure(action_id,actor_id,"unknown_item","没有找到这种物品。",item_id)
        if use_definition.mode!="equip" or item_id not in SLOT_BY_ITEM:
            return self._failure(action_id,actor_id,"not_equippable","这种物品不能装备。",item_id)
        inventory=world.economy.actor_inventory(actor_id)
        if inventory.quantity(item_id)<1:
            return self._failure(action_id,actor_id,"item_missing","行动者没有这件物品。",item_id)
        candidates=world.item_instances.instances_for(actor_id,item_id,world.day)
        instance=next((candidate for candidate in candidates
                       if instance_id in {None,candidate.id} and candidate.equipped_slot is None),None)
        if instance is None:
            return self._failure(action_id,actor_id,"instance_unavailable","没有可装备的物品实例。",item_id)
        slot=SLOT_BY_ITEM[item_id]; slots=self._slots(world,actor_id)
        if slot in slots:
            return self._failure(action_id,actor_id,"slot_occupied",f"{slot} 槽位已有装备，必须先卸下。",item_id,instance.id,slot)
        slots[slot]=instance.id; instance.equipped_slot=slot
        equipped=self._equipped_ids(world,actor_id)
        if item_id not in equipped:
            equipped.append(item_id)
        state_changes=self._apply_state_effects(world,actor_id,use_definition.state_effects)
        world.item_effect_system.grant(
            world,actor_id=actor_id,source_item_id=item_id,
            source_instance_id=instance.id,effects=use_definition.grants_effects,
            requires_equipped=True)
        return EquipmentReceipt(
            True,"success",f"{self._actor_name(world,actor_id)}装备了 {definition.name}。",
            action_id,actor_id,item_id,instance.id,slot,state_changes,
            dict(use_definition.grants_effects))

    def unequip(self,world,*,actor_id: str,item_id: str | None = None,
                instance_id: str | None = None,slot: str | None = None):
        action_id="UNEQUIP_ITEM"
        if not self._actor_exists(world,actor_id):
            return self._failure(action_id,actor_id,"unknown_actor","行动者不存在。",item_id or "")
        slots=self._slots(world,actor_id)
        selected_slot=slot
        if selected_slot is None and instance_id:
            selected_slot=next((name for name,value in slots.items() if value==instance_id),None)
        if selected_slot is None and item_id:
            selected_slot=next((name for name,value in slots.items()
                                if world.item_instances.instances.get(value)
                                and world.item_instances.instances[value].item_id==item_id),None)
        if selected_slot not in slots:
            return self._failure(action_id,actor_id,"not_equipped","没有找到要卸下的装备。",item_id or "",instance_id or "",slot or "")
        selected_id=slots.pop(selected_slot)
        instance=world.item_instances.instances[selected_id]
        instance.equipped_slot=None
        world.item_effect_system.remove_source(world,actor_id,selected_id)
        equipped=self._equipped_ids(world,actor_id)
        if not any(world.item_instances.instances[value].item_id==instance.item_id
                   for value in slots.values()):
            equipped[:]=[value for value in equipped if value!=instance.item_id]
        definition=world.item_catalog[instance.item_id]
        return EquipmentReceipt(
            True,"success",f"{self._actor_name(world,actor_id)}卸下了 {definition.name}。",
            action_id,actor_id,instance.item_id,selected_id,selected_slot)

    def validate(self,world):
        errors=[]; equipped_instances=set()
        for actor_id in ["player",*world.npcs.keys()]:
            slots=self._slots(world,actor_id)
            for slot,instance_id in slots.items():
                instance=world.item_instances.instances.get(instance_id)
                if instance_id in equipped_instances:
                    errors.append(f"item instance equipped twice: {instance_id}")
                equipped_instances.add(instance_id)
                if instance is None:
                    errors.append(f"missing equipped item instance: {instance_id}")
                elif instance.inventory_id!=actor_id or instance.equipped_slot!=slot:
                    errors.append(f"equipped item location mismatch: {instance_id}")
        for instance_id,instance in world.item_instances.instances.items():
            if instance.equipped_slot and instance_id not in equipped_instances:
                errors.append(f"orphan equipped item: {instance_id}")
        return errors

    @staticmethod
    def _apply_state_effects(world,actor_id,effects):
        states=world.player_states if actor_id=="player" else world.npcs[actor_id].states
        changes={}
        for name,delta in effects.items():
            old=states.get(name,0); states[name]=max(0,min(100,old+int(delta)))
            changes[name]=states[name]-old
        return changes

    @staticmethod
    def _slots(world,actor_id):
        return world.player_equipment_slots if actor_id=="player" else world.npcs[actor_id].equipment_slots

    @staticmethod
    def _equipped_ids(world,actor_id):
        return world.player_equipped_item_ids if actor_id=="player" else world.npcs[actor_id].equipped_item_ids

    @staticmethod
    def _actor_exists(world,actor_id):
        return actor_id=="player" or actor_id in world.npcs

    @staticmethod
    def _actor_name(world,actor_id):
        return "玩家" if actor_id=="player" else world.npcs[actor_id].name

    @staticmethod
    def _failure(action_id,actor_id,code,message,item_id="",instance_id="",slot=""):
        return EquipmentReceipt(False,code,message,action_id,actor_id,item_id,instance_id,slot)


__all__=["EquipmentSystem","SLOT_BY_ITEM"]
