"""Atomic inventory actions shared by player and NPCs."""
from __future__ import annotations

from simulation.domain.inventory import ItemTransferReceipt


class ItemActionSystem:
    def give(self,world,*,actor_id: str,target_id: str,item_id: str,quantity: int = 1):
        action_id="GIVE_ITEM"
        error=self._common_error(world,action_id,actor_id,item_id,quantity)
        if error:
            return error
        if actor_id==target_id:
            return self._failure(action_id,actor_id,item_id,quantity,"same_actor","不能把物品交给自己。")
        if not self._actor_exists(world,target_id):
            return self._failure(action_id,actor_id,item_id,quantity,"unknown_target","接收者不存在。")
        if self._actor_scene(world,actor_id)!=self._actor_scene(world,target_id):
            return self._failure(action_id,actor_id,item_id,quantity,"target_absent","双方不在同一地点。",target_id=target_id)
        if self._is_equipped(world,actor_id,item_id):
            return self._failure(action_id,actor_id,item_id,quantity,"item_equipped","必须先卸下物品。",target_id=target_id)
        moved,error=self._transfer(
            world,actor_id,target_id,item_id,quantity,change_legal_owner=True)
        if error:
            return self._failure(action_id,actor_id,item_id,quantity,error[0],error[1],target_id=target_id)
        item=world.item_catalog[item_id]
        return ItemTransferReceipt(
            True,"success",f"{self._actor_name(world,actor_id)}把 {quantity} × {item.name} 交给了{self._actor_name(world,target_id)}。",
            action_id,actor_id,item_id,quantity,actor_id,target_id,target_id,moved)

    def drop(self,world,*,actor_id: str,item_id: str,quantity: int = 1):
        action_id="DROP_ITEM"
        error=self._common_error(world,action_id,actor_id,item_id,quantity)
        if error:
            return error
        if self._is_equipped(world,actor_id,item_id):
            return self._failure(action_id,actor_id,item_id,quantity,"item_equipped","必须先卸下物品。")
        scene_id=self._actor_scene(world,actor_id)
        destination=world.item_instances.inventory_id_for_scene(scene_id)
        moved,error=self._transfer(world,actor_id,destination,item_id,quantity)
        if error:
            return self._failure(action_id,actor_id,item_id,quantity,error[0],error[1])
        item=world.item_catalog[item_id]
        return ItemTransferReceipt(
            True,"success",f"{self._actor_name(world,actor_id)}把 {quantity} × {item.name} 放在了{world.scenes[scene_id].name}。",
            action_id,actor_id,item_id,quantity,actor_id,destination,instance_ids=moved)

    def pick_up(self,world,*,actor_id: str,item_id: str,quantity: int = 1,
                container_id: str | None = None):
        action_id="PICK_UP_ITEM"
        error=self._common_error(world,action_id,actor_id,item_id,quantity,require_owned=False)
        if error:
            return error
        scene_id=self._actor_scene(world,actor_id)
        if container_id:
            obj=world.objects.get(container_id)
            if obj is None or obj.object_type!="container":
                return self._failure(action_id,actor_id,item_id,quantity,"unknown_container","没有找到这个容器。")
            if obj.scene_id!=scene_id:
                return self._failure(action_id,actor_id,item_id,quantity,"container_absent","容器不在使用者所在地点。")
            if "take" not in obj.affordances and "open" not in obj.affordances:
                return self._failure(action_id,actor_id,item_id,quantity,"container_closed","无法从这个容器取出物品。")
            source=world.item_instances.inventory_id_for_container(container_id)
        else:
            source=world.item_instances.inventory_id_for_scene(scene_id)
        if world.inventories[source].quantity(item_id)<quantity:
            return self._failure(action_id,actor_id,item_id,quantity,"item_missing","现场没有足够的这种物品。")
        world.item_instances.reconcile_inventory(source,world.day)
        candidates=world.item_instances.instances_for(source,item_id,world.day)[:quantity]
        unauthorized=any(instance.legal_owner_id not in {None,actor_id} for instance in candidates)
        moved,error=self._transfer(world,source,actor_id,item_id,quantity)
        if error:
            return self._failure(action_id,actor_id,item_id,quantity,error[0],error[1])
        item=world.item_catalog[item_id]
        risk=0
        if unauthorized:
            risk+=8
        if item.legality=="restricted":
            risk+=4
        elif item.legality=="contraband":
            risk+=10
        if risk:
            states=world.player_states if actor_id=="player" else world.npcs[actor_id].states
            states["legal_risk"]=min(100,states.get("legal_risk",0)+risk)
        return ItemTransferReceipt(
            True,"success",f"{self._actor_name(world,actor_id)}拾取了 {quantity} × {item.name}。",
            action_id,actor_id,item_id,quantity,source,actor_id,
            instance_ids=moved,legal_risk_delta=risk)

    def _common_error(self,world,action_id,actor_id,item_id,quantity,require_owned=True):
        if not self._actor_exists(world,actor_id):
            return self._failure(action_id,actor_id,item_id,quantity,"unknown_actor","行动者不存在。")
        if item_id not in world.item_catalog:
            return self._failure(action_id,actor_id,item_id,quantity,"unknown_item","没有找到这种物品。")
        if isinstance(quantity,bool) or not isinstance(quantity,int) or quantity<=0:
            return self._failure(action_id,actor_id,item_id,0,"invalid_quantity","数量必须是正整数。")
        if require_owned and world.economy.actor_inventory(actor_id).quantity(item_id)<quantity:
            return self._failure(action_id,actor_id,item_id,quantity,"item_missing","行动者没有足够的这种物品。")
        return None

    @staticmethod
    def _transfer(world,source,destination,item_id,quantity,change_legal_owner=False):
        try:
            moved=world.item_instances.transfer(
                world,source,destination,item_id,quantity,
                change_legal_owner=change_legal_owner)
            return moved,None
        except KeyError:
            return [],("unknown_inventory","物品来源或目的库存不存在。")
        except ValueError as exc:
            code="inventory_full" if "cannot accept" in str(exc) else "item_missing"
            message="目标库存容量不足或已持有该唯一物品。" if code=="inventory_full" else "来源库存没有足够物品。"
            return [],(code,message)

    @staticmethod
    def _actor_exists(world,actor_id):
        return actor_id=="player" or actor_id in world.npcs

    @staticmethod
    def _actor_scene(world,actor_id):
        return world.player_scene if actor_id=="player" else world.npcs[actor_id].current_scene

    @staticmethod
    def _actor_name(world,actor_id):
        return "玩家" if actor_id=="player" else world.npcs[actor_id].name

    @staticmethod
    def _is_equipped(world,actor_id,item_id):
        equipped=world.player_equipped_item_ids if actor_id=="player" else world.npcs[actor_id].equipped_item_ids
        return item_id in equipped

    @staticmethod
    def _failure(action_id,actor_id,item_id,quantity,code,message,target_id=None):
        return ItemTransferReceipt(
            False,code,message,action_id,actor_id,item_id,quantity,target_id=target_id)


__all__=["ItemActionSystem"]
