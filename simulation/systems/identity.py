"""Identity inspections driven by prepared disguises and physical credentials."""
from __future__ import annotations

from simulation.domain.entities import Relationship
from simulation.domain.interactions import IdentityCheckReceipt


IDENTITY_ITEMS={"makeup_kit","forged_identity_papers","blackthorn_badge"}
OUTCOME_SUSPICION={
    "complete_success":-4,
    "success":0,
    "partial":10,
    "failure":25,
    "critical_failure":40,
}


class IdentitySystem:
    def inspect(self,world,*,actor_id: str,inspector_id: str,item_id: str,resolver,
                difficulty_override: int | None = None):
        if actor_id!="player" and actor_id not in world.npcs:
            return self._failure(actor_id,inspector_id,item_id,"unknown_actor","行动者不存在。")
        inspector=world.npcs.get(inspector_id)
        if inspector is None:
            return self._failure(actor_id,inspector_id,item_id,"unknown_inspector","检查人员不存在。")
        if actor_id==inspector_id:
            return self._failure(actor_id,inspector_id,item_id,"invalid_target","行动者不能检查自己。")
        scene=self._scene(world,actor_id)
        if scene!=inspector.current_scene:
            return self._failure(actor_id,inspector_id,item_id,"target_absent","检查人员不在现场。")
        if item_id not in IDENTITY_ITEMS:
            return self._failure(actor_id,inspector_id,item_id,"unsupported_identity_method","该物品不能用于身份检查。")
        inventory=world.economy.actor_inventory(actor_id)
        if inventory.quantity(item_id)<1:
            return self._failure(actor_id,inspector_id,item_id,"item_missing","行动者没有所选身份物品。")
        instances=world.item_instances.instances_for(actor_id,item_id,world.day)
        instance=instances[0] if instances else None
        if instance is None:
            return self._failure(actor_id,inspector_id,item_id,"instance_unavailable","没有可用的物品实例。")

        effects=self._effects(world,actor_id)
        if item_id=="makeup_kit" and effects.get("disguise_bonus",0)<=0:
            return self._failure(
                actor_id,inspector_id,item_id,"disguise_not_prepared",
                "必须先通过 USE_ITEM 使用化妆盒完成伪装，才能接受身份检查。")
        if item_id=="blackthorn_badge" and instance.equipped_slot!="identity":
            return self._failure(
                actor_id,inspector_id,item_id,"credential_not_equipped",
                "黑荆棘徽章必须先通过 EQUIP_ITEM 装备到身份槽位。")

        relationship=inspector.relationships.setdefault(actor_id,Relationship(since_day=world.day))
        difficulty=(difficulty_override if difficulty_override is not None else
                    55+inspector.skills.get("observation",0)
                    +inspector.skills.get("insight",0)//2
                    +relationship.suspicion//5)
        difficulty=max(1,min(200,int(difficulty)))
        use_definition=world.item_uses.definition(item_id)
        effect_name={
            "makeup_kit":"disguise_bonus",
            "forged_identity_papers":"false_identity_bonus",
            "blackthorn_badge":"official_identity_bonus",
        }[item_id]
        # Makeup represents prior preparation and therefore only uses the active
        # effect. Credentials apply their printed/equipped quality directly.
        direct={} if item_id=="makeup_kit" else {
            effect_name:int(use_definition.grants_effects.get(effect_name,0))}
        forged=item_id=="forged_identity_papers"
        check,consequences,event=resolver(
            actor_id=actor_id,target_id=inspector_id,check_type="身份检查",
            skill="deception",difficulty=difficulty,item_effect_names=[effect_name],
            direct_item_modifiers=direct,base_legal_risk=16 if forged else 0,
            base_noise=0,trace_type="forged_identity_discrepancy" if forged else "identity_discrepancy",
            trace_discoverability=75 if forged else 45,tool_instance_id=None)
        accepted=check.outcome in {"complete_success","success","partial"}
        suspicion_delta=OUTCOME_SUSPICION[check.outcome]
        if forged and not accepted:
            suspicion_delta+=8
            if "exposed_forgery" not in instance.evidence_tags:
                instance.evidence_tags.append("exposed_forgery")
        before=relationship.suspicion
        relationship.suspicion=max(0,min(100,before+suspicion_delta))
        actual_delta=relationship.suspicion-before
        for trace_id in consequences.trace_ids:
            trace=world.ritual_engine.traces.get(trace_id)
            if trace:
                trace.payload.update({"inspector_id":inspector_id,"item_id":item_id,
                                      "instance_id":instance.id})
        outcome_name={
            "complete_success":"完全通过","success":"通过","partial":"带着疑虑通过",
            "failure":"未通过","critical_failure":"暴露",
        }[check.outcome]
        method_name=world.item_catalog[item_id].name
        return IdentityCheckReceipt(
            accepted,"accepted" if accepted else check.outcome,
            f"{self._name(world,actor_id)}使用{method_name}接受{inspector.name}检查：{outcome_name}。",
            actor_id,inspector_id,item_id,instance.id,accepted,actual_delta,
            check,consequences,event.event_id)

    @staticmethod
    def _effects(world,actor_id):
        return world.player_item_effects if actor_id=="player" else world.npcs[actor_id].item_effects

    @staticmethod
    def _scene(world,actor_id):
        return world.player_scene if actor_id=="player" else world.npcs[actor_id].current_scene

    @staticmethod
    def _name(world,actor_id):
        return "玩家" if actor_id=="player" else world.npcs[actor_id].name

    @staticmethod
    def _failure(actor_id,inspector_id,item_id,code,message):
        return IdentityCheckReceipt(False,code,message,actor_id,inspector_id,item_id)


__all__=["IDENTITY_ITEMS","IdentitySystem"]
