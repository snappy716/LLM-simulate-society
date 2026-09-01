"""Equipped weapon affordances and evidence-bearing intimidation."""
from __future__ import annotations

from simulation.domain.entities import Relationship
from simulation.domain.interactions import WeaponThreatReceipt


def equipped_weapon(world,actor_id: str):
    slots=(world.player_equipment_slots if actor_id=="player"
           else world.npcs[actor_id].equipment_slots)
    instance_id=slots.get("main_hand")
    instance=world.item_instances.instances.get(instance_id) if instance_id else None
    if instance is None or instance.condition<=0:
        return None
    definition=world.item_catalog.get(instance.item_id)
    return instance if definition and definition.category=="weapon" else None


class WeaponActionSystem:
    def threaten(self,world,*,actor_id: str,target_id: str,resolver,
                 difficulty_override: int | None = None):
        if actor_id!="player" and actor_id not in world.npcs:
            return self._failure(actor_id,target_id,"unknown_actor","行动者不存在。")
        target=world.npcs.get(target_id)
        if target is None:
            return self._failure(actor_id,target_id,"unknown_target","威慑目标不存在。")
        if actor_id==target_id:
            return self._failure(actor_id,target_id,"invalid_target","不能威慑自己。")
        scene=self._scene(world,actor_id)
        if target.current_scene!=scene:
            return self._failure(actor_id,target_id,"target_absent","威慑目标不在现场。")
        instance=equipped_weapon(world,actor_id)
        if instance is None:
            return self._failure(actor_id,target_id,"weapon_not_equipped","必须先在主手装备一件可用武器。")
        definition=world.item_catalog[instance.item_id]
        use_definition=world.item_uses.definition(instance.item_id)
        effect_name="firearm_bonus" if "firearm" in definition.tags else "melee_bonus"
        relation=target.relationships.setdefault(actor_id,Relationship(since_day=world.day))
        difficulty=(difficulty_override if difficulty_override is not None else
                    58+target.skills.get("willpower",0)+target.states.get("morale",50)//8
                    -target.states.get("fear",0)//10-relation.fear//10)
        difficulty=max(1,min(200,int(difficulty)))
        firearm="firearm" in definition.tags
        check,consequences,event=resolver(
            actor_id=actor_id,target_id=target_id,check_type="持械威慑",skill="combat",
            difficulty=difficulty,item_effect_names=[effect_name],
            direct_item_modifiers=use_definition.grants_effects,
            base_legal_risk=22,base_noise=20 if firearm else 6,
            trace_type="weapon_brandishing",trace_discoverability=78,
            tool_instance_id=None,always_trace=True)
        yielded=check.outcome in {"complete_success","success","partial"}
        desired_fear={"complete_success":30,"success":24,"partial":14,
                      "failure":7,"critical_failure":3}[check.outcome]
        old_fear=target.states.get("fear",0)
        target.states["fear"]=min(100,old_fear+desired_fear)
        fear_delta=target.states["fear"]-old_fear
        relation.fear=min(100,relation.fear+fear_delta)
        evidence_tag=f"brandished_day_{world.day}"
        if evidence_tag not in instance.evidence_tags:
            instance.evidence_tags.append(evidence_tag)
        for trace_id in consequences.trace_ids:
            trace=world.ritual_engine.traces.get(trace_id)
            if trace:
                trace.payload.update({"target_id":target_id,"item_id":instance.item_id,
                                      "instance_id":instance.id})
        outcome_name={"complete_success":"目标完全屈服","success":"目标退让",
                      "partial":"目标暂时退让但会记住此事","failure":"威慑失败",
                      "critical_failure":"威慑彻底失败并暴露破绽"}[check.outcome]
        return WeaponThreatReceipt(
            yielded,"yielded" if yielded else check.outcome,
            f"{self._name(world,actor_id)}用{definition.name}威慑{target.name}：{outcome_name}。",
            actor_id,target_id,instance.item_id,instance.id,yielded,fear_delta,
            check,consequences,event.event_id)

    @staticmethod
    def _scene(world,actor_id):
        return world.player_scene if actor_id=="player" else world.npcs[actor_id].current_scene

    @staticmethod
    def _name(world,actor_id):
        return "玩家" if actor_id=="player" else world.npcs[actor_id].name

    @staticmethod
    def _failure(actor_id,target_id,code,message):
        return WeaponThreatReceipt(False,code,message,actor_id,target_id)


__all__=["WeaponActionSystem","equipped_weapon"]
