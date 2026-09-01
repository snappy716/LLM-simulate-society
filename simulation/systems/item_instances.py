"""Stable identity and location for durable or story-bearing inventory items."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
from typing import Dict

from simulation.domain.inventory import Inventory, ItemDefinition, ItemInstance


INSTANCE_CATEGORIES = {
    "tool", "key", "weapon", "equipment", "identity", "sealed_artifact",
}
INSTANCE_ITEM_IDS={"blank_notebook","silver_charm"}


class ItemInstanceSystem:
    def __init__(self, world) -> None:
        self.catalog: Dict[str, ItemDefinition] = world.item_catalog
        self.inventories: Dict[str, Inventory] = world.inventories
        self.instances: Dict[str, ItemInstance] = {}
        self._next_instance = 1
        self._create_location_inventories(world)
        self.reconcile(world.day)

    @staticmethod
    def inventory_id_for_scene(scene_id: str) -> str:
        return f"scene:{scene_id}"

    @staticmethod
    def inventory_id_for_container(object_id: str) -> str:
        return f"container:{object_id}"

    def _create_location_inventories(self, world) -> None:
        for scene_id in world.scenes:
            inventory_id=self.inventory_id_for_scene(scene_id)
            self.inventories.setdefault(inventory_id,Inventory(inventory_id,max_weight=100000.0))
        for object_id,obj in world.objects.items():
            if obj.object_type!="container":
                continue
            inventory_id=self.inventory_id_for_container(object_id)
            self.inventories.setdefault(inventory_id,Inventory(inventory_id,max_weight=100000.0))

    def requires_instance(self,item_id: str) -> bool:
        definition=self.catalog[item_id]
        return bool(
            definition.unique or definition.stack_limit==1
            or definition.category in INSTANCE_CATEGORIES or item_id in INSTANCE_ITEM_IDS
        )

    def _new_instance(self,item_id: str,inventory_id: str,day: int) -> ItemInstance:
        instance_id=f"iteminst_{self._next_instance:08d}"
        self._next_instance+=1
        legal_owner=None if inventory_id.startswith(("scene:","container:")) else inventory_id
        instance=ItemInstance(
            instance_id,item_id,inventory_id,created_day=day,legal_owner_id=legal_owner)
        self.instances[instance_id]=instance
        return instance

    def reconcile_inventory(self,inventory_id: str,day: int) -> None:
        inventory=self.inventories[inventory_id]
        for item_id in list(inventory.instance_ids):
            if item_id not in self.catalog or not self.requires_instance(item_id):
                for instance_id in inventory.instance_ids.pop(item_id,[]):
                    self.instances.pop(instance_id,None)
        for item_id in set(inventory.quantities)|set(inventory.instance_ids):
            if item_id not in self.catalog or not self.requires_instance(item_id):
                continue
            desired=inventory.quantity(item_id)
            ids=inventory.instance_ids.setdefault(item_id,[])
            while len(ids)<desired:
                ids.append(self._new_instance(item_id,inventory_id,day).id)
            while len(ids)>desired:
                instance_id=ids.pop()
                self.instances.pop(instance_id,None)
            if not ids:
                inventory.instance_ids.pop(item_id,None)
            for instance_id in ids:
                instance=self.instances.get(instance_id)
                if instance is None:
                    instance=ItemInstance(instance_id,item_id,inventory_id,created_day=day)
                    self.instances[instance_id]=instance
                instance.inventory_id=inventory_id

    def reconcile(self,day: int) -> None:
        for inventory_id in list(self.inventories):
            self.reconcile_inventory(inventory_id,day)

    def instances_for(self,inventory_id: str,item_id: str,day: int) -> list[ItemInstance]:
        self.reconcile_inventory(inventory_id,day)
        inventory=self.inventories[inventory_id]
        return [self.instances[instance_id]
                for instance_id in inventory.instance_ids.get(item_id,[])]

    def transfer(self,world,source_id: str,destination_id: str,item_id: str,quantity: int,
                 *,change_legal_owner: bool = False) -> list[str]:
        """Atomically move quantity and stable instances between two inventories."""
        if source_id==destination_id:
            raise ValueError("source and destination inventories are identical")
        if source_id not in self.inventories or destination_id not in self.inventories:
            raise KeyError("unknown inventory")
        definition=self.catalog[item_id]
        source=self.inventories[source_id]; destination=self.inventories[destination_id]
        if source.quantity(item_id)<quantity:
            raise ValueError(f"inventory lacks {quantity} x {item_id}")
        if not destination.can_add(definition,quantity,self.catalog):
            raise ValueError(f"inventory cannot accept {quantity} x {item_id}")
        self.reconcile_inventory(source_id,world.day)
        self.reconcile_inventory(destination_id,world.day)
        before=(dict(source.quantities),deepcopy(source.instance_ids),
                dict(destination.quantities),deepcopy(destination.instance_ids),
                deepcopy(self.instances))
        moved=[]
        try:
            if self.requires_instance(item_id):
                moved=list(source.instance_ids.get(item_id,[])[:quantity])
                if len(moved)!=quantity:
                    raise RuntimeError("instance quantity mismatch")
                if any(self.instances[instance_id].equipped_slot for instance_id in moved):
                    raise ValueError("equipped item cannot be transferred")
                source.instance_ids[item_id]=source.instance_ids[item_id][quantity:]
                if not source.instance_ids[item_id]:
                    source.instance_ids.pop(item_id,None)
                destination.instance_ids.setdefault(item_id,[]).extend(moved)
                for instance_id in moved:
                    self.instances[instance_id].inventory_id=destination_id
                    if change_legal_owner:
                        self.instances[instance_id].legal_owner_id=destination_id
            source.remove(item_id,quantity)
            destination.add(definition,quantity,self.catalog)
            errors=self.validate()
            if errors:
                raise RuntimeError("; ".join(errors))
        except Exception:
            source.quantities=before[0]; source.instance_ids=before[1]
            destination.quantities=before[2]; destination.instance_ids=before[3]
            self.instances=before[4]
            raise
        return moved

    def add_new(self,world,inventory_id: str,item_id: str,quantity: int,
                *,legal_owner_id: str | None = None) -> list[str]:
        definition=self.catalog[item_id]
        inventory=self.inventories[inventory_id]
        before=(dict(inventory.quantities),deepcopy(inventory.instance_ids),deepcopy(self.instances))
        try:
            before_ids=set(self.instances)
            inventory.add(definition,quantity,self.catalog)
            self.reconcile_inventory(inventory_id,world.day)
            if legal_owner_id is not None:
                for instance_id in set(self.instances)-before_ids:
                    self.instances[instance_id].legal_owner_id=legal_owner_id
            errors=self.validate()
            if errors:
                raise RuntimeError("; ".join(errors))
        except Exception:
            inventory.quantities=before[0]; inventory.instance_ids=before[1]
            self.instances=before[2]
            raise
        return [instance.id for instance in self.instances_for(inventory_id,item_id,world.day)][-quantity:]

    def validate(self) -> list[str]:
        errors=[]; seen=set()
        for inventory_id,inventory in self.inventories.items():
            for item_id,instance_ids in inventory.instance_ids.items():
                if item_id not in self.catalog:
                    errors.append(f"{inventory_id}: unknown instanced item: {item_id}")
                    continue
                if not self.requires_instance(item_id):
                    errors.append(f"{inventory_id}: untracked item has instances: {item_id}")
                if len(instance_ids)!=inventory.quantity(item_id):
                    errors.append(f"{inventory_id}: instance quantity mismatch: {item_id}")
                for instance_id in instance_ids:
                    if instance_id in seen:
                        errors.append(f"instance has multiple locations: {instance_id}")
                    seen.add(instance_id)
                    instance=self.instances.get(instance_id)
                    if not instance:
                        errors.append(f"missing item instance: {instance_id}")
                    elif instance.item_id!=item_id or instance.inventory_id!=inventory_id:
                        errors.append(f"item instance location mismatch: {instance_id}")
        for instance_id,instance in self.instances.items():
            if instance_id not in seen:
                errors.append(f"orphan item instance: {instance_id}")
            if not 0<=instance.condition<=100:
                errors.append(f"invalid item condition: {instance_id}")
        return errors

    def public_instances(self) -> dict:
        return {instance_id:asdict(instance)
                for instance_id,instance in self.instances.items()}


def initialize_item_instances(world,content_dir: Path | None = None) -> ItemInstanceSystem:
    system=ItemInstanceSystem(world)
    if content_dir is None:
        return system
    path=content_dir/"items"/"placements.json"
    payload=json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version")!=1:
        raise ValueError("unsupported item placement content schema")
    for raw in payload.get("placements",[]):
        inventory_id=str(raw.get("inventory_id",""))
        item_id=str(raw.get("item_id",""))
        quantity=raw.get("quantity",1)
        if inventory_id not in system.inventories:
            raise ValueError(f"unknown placement inventory: {inventory_id}")
        if item_id not in system.catalog:
            raise ValueError(f"unknown placement item: {item_id}")
        if isinstance(quantity,bool) or not isinstance(quantity,int) or quantity<=0:
            raise ValueError(f"invalid placement quantity: {item_id}")
        system.add_new(
            world,inventory_id,item_id,quantity,
            legal_owner_id=raw.get("legal_owner_id"))
    errors=world.economy.validate_invariants(world)
    if errors:
        raise ValueError("invalid initial item placement: "+"; ".join(errors))
    return system


__all__=["INSTANCE_CATEGORIES","INSTANCE_ITEM_IDS","ItemInstanceSystem","initialize_item_instances"]
