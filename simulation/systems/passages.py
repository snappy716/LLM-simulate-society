"""Data-driven doors and special entrances using items as action enablers."""
from __future__ import annotations

import json
from pathlib import Path

from simulation.domain.interactions import Passage, PassageActionReceipt


PASSAGE_ACTION_ITEMS={
    "PICK_LOCK":"lockpick_set",
    "FORCE_OPEN":"crowbar",
    "CLIMB_WITH_ROPE":"hemp_rope",
}


class PassageSystem:
    def __init__(self,passages: dict[str,Passage]):
        self.passages=passages

    def act(self,world,*,action_id: str,actor_id: str,passage_id: str,resolver):
        passage=self.passages.get(passage_id)
        if passage is None:
            return self._failure(action_id,actor_id,passage_id,"unknown_passage","没有找到这个入口。")
        if actor_id!="player" and actor_id not in world.npcs:
            return self._failure(action_id,actor_id,passage_id,"unknown_actor","行动者不存在。")
        scene=self._actor_scene(world,actor_id); destination=passage.other_scene(scene)
        if destination is None:
            return self._failure(action_id,actor_id,passage_id,"passage_absent","行动者不在这个入口旁。")
        before=passage.state
        if action_id=="UNLOCK_WITH_KEY":
            return self._use_key(world,actor_id,passage,scene,destination,before)
        if action_id=="TRAVERSE_PASSAGE":
            if passage.state not in {"open","broken"}:
                return self._failure(action_id,actor_id,passage_id,"passage_closed","入口尚未打开。",scene,destination,before)
            self._move_actor(world,actor_id,destination)
            return PassageActionReceipt(
                True,"success",f"{self._actor_name(world,actor_id)}通过了{passage.name}。",
                action_id,actor_id,passage.id,from_scene=scene,to_scene=destination,
                state_before=before,state_after=passage.state,moved=True)
        item_id=PASSAGE_ACTION_ITEMS.get(action_id)
        if item_id is None:
            return self._failure(action_id,actor_id,passage_id,"invalid_action","这个入口不支持该行动。",scene,destination,before)
        method={"PICK_LOCK":"lockpick","FORCE_OPEN":"force","CLIMB_WITH_ROPE":"rope"}[action_id]
        if method not in passage.allowed_methods:
            return self._failure(action_id,actor_id,passage_id,"method_forbidden","这个入口不能用该方式处理。",scene,destination,before,item_id)
        if action_id in {"PICK_LOCK","FORCE_OPEN"} and passage.state!="locked":
            return self._failure(action_id,actor_id,passage_id,"not_locked","入口当前不需要这样打开。",scene,destination,before,item_id)
        instance=self._usable_instance(world,actor_id,item_id)
        if instance is None:
            return self._failure(action_id,actor_id,passage_id,"tool_missing_or_broken","缺少可用工具，或工具已经损坏。",scene,destination,before,item_id)
        return self._checked_action(
            world,action_id,actor_id,passage,scene,destination,before,item_id,instance,resolver)

    def _checked_action(self,world,action_id,actor_id,passage,scene,destination,before,
                        item_id,instance,resolver):
        definitions={
            "PICK_LOCK":("技巧开锁","lockpicking",passage.lock_difficulty,
                         ["lockpicking_bonus"],10,"lockpick_marks",55,False),
            "FORCE_OPEN":("暴力开门","force_entry",passage.force_difficulty,
                          ["force_entry_bonus"],passage.force_noise,"forced_entry_damage",85,True),
            "CLIMB_WITH_ROPE":("绳索攀爬","climbing",passage.climb_difficulty,
                               ["climbing_bonus"],passage.force_noise,"rope_fibers",40,False),
        }
        label,skill,difficulty,effect_names,noise,trace_type,discoverability,always_trace=definitions[action_id]
        use_definition=world.item_uses.definition(item_id)
        authorized=self._authorized(world,actor_id,passage)
        check,consequences,event=resolver(
            actor_id=actor_id,target_id=passage.id,check_type=label,skill=skill,
            difficulty=difficulty,item_effect_names=effect_names,
            direct_item_modifiers=use_definition.grants_effects,
            base_legal_risk=0 if authorized else passage.legal_risk,
            base_noise=noise,trace_type=trace_type,
            trace_discoverability=discoverability,tool_instance_id=instance.id,
            always_trace=always_trace)
        succeeded=check.outcome in {"complete_success","success","partial"}
        moved=False
        if action_id=="PICK_LOCK" and succeeded:
            passage.state="open"
        elif action_id=="FORCE_OPEN" and succeeded:
            passage.state="broken"; passage.condition=max(0,passage.condition-45)
        elif action_id=="CLIMB_WITH_ROPE" and succeeded:
            self._move_actor(world,actor_id,destination); moved=True
        elif action_id=="CLIMB_WITH_ROPE" and check.outcome=="critical_failure":
            if actor_id=="player":
                world.player_health=max(0,world.player_health-10)
                world.player_states["pain"]=min(100,world.player_states.get("pain",0)+20)
            else:
                npc=world.npcs[actor_id]; npc.health=max(0,npc.health-10)
                npc.states["pain"]=min(100,npc.states.get("pain",0)+20)
        outcome_name={"complete_success":"完全成功","success":"成功","partial":"部分成功",
                      "failure":"失败","critical_failure":"严重失败"}[check.outcome]
        return PassageActionReceipt(
            succeeded,"success" if succeeded else check.outcome,
            f"{self._actor_name(world,actor_id)}对{passage.name}执行{label}：{outcome_name}。",
            action_id,actor_id,passage.id,item_id,instance.id,scene,destination,
            before,passage.state,moved,check,consequences,event.event_id)

    def _use_key(self,world,actor_id,passage,scene,destination,before):
        action_id="UNLOCK_WITH_KEY"
        if "key" not in passage.allowed_methods or not passage.key_item_id:
            return self._failure(action_id,actor_id,passage.id,"key_not_supported","这个入口没有可用钥匙。",scene,destination,before)
        if passage.state!="locked":
            return self._failure(action_id,actor_id,passage.id,"not_locked","入口当前没有上锁。",scene,destination,before,passage.key_item_id)
        if world.economy.actor_inventory(actor_id).quantity(passage.key_item_id)<1:
            return self._failure(action_id,actor_id,passage.id,"key_missing","行动者没有对应钥匙。",scene,destination,before,passage.key_item_id)
        instances=world.item_instances.instances_for(actor_id,passage.key_item_id,world.day)
        passage.state="open"
        return PassageActionReceipt(
            True,"success",f"{self._actor_name(world,actor_id)}用钥匙打开了{passage.name}，无需检定。",
            action_id,actor_id,passage.id,passage.key_item_id,
            instances[0].id if instances else "",scene,destination,before,passage.state)

    @staticmethod
    def _usable_instance(world,actor_id,item_id):
        if world.economy.actor_inventory(actor_id).quantity(item_id)<1:
            return None
        return next((instance for instance in world.item_instances.instances_for(actor_id,item_id,world.day)
                     if instance.condition>0),None)

    @staticmethod
    def _authorized(world,actor_id,passage):
        if actor_id in passage.authorized_actor_ids:
            return True
        if actor_id=="player":
            return False
        npc=world.npcs[actor_id]
        return (npc.occupation in passage.authorized_occupations
                or passage.owner_id in npc.faction_ids
                or npc.organization==passage.owner_id)

    @staticmethod
    def _move_actor(world,actor_id,destination):
        if actor_id=="player":
            world.player_scene=destination
        else:
            world.npcs[actor_id].current_scene=destination

    @staticmethod
    def _actor_scene(world,actor_id):
        return world.player_scene if actor_id=="player" else world.npcs[actor_id].current_scene

    @staticmethod
    def _actor_name(world,actor_id):
        return "玩家" if actor_id=="player" else world.npcs[actor_id].name

    @staticmethod
    def _failure(action_id,actor_id,passage_id,code,message,from_scene="",to_scene="",
                 state_before="",item_id=""):
        return PassageActionReceipt(
            False,code,message,action_id,actor_id,passage_id,item_id,
            from_scene=from_scene,to_scene=to_scene,
            state_before=state_before,state_after=state_before)


def initialize_passages(world,content_dir: Path):
    payload=json.loads((content_dir/"locations"/"passages.json").read_text(encoding="utf-8"))
    if payload.get("schema_version")!=1:
        raise ValueError("unsupported passage content schema")
    passages={}
    for raw in payload.get("passages",[]):
        passage=Passage(**raw)
        if passage.id in passages:
            raise ValueError(f"duplicate passage: {passage.id}")
        if passage.scene_a not in world.scenes or passage.scene_b not in world.scenes:
            raise ValueError(f"passage references unknown scene: {passage.id}")
        if passage.state not in {"open","closed","locked","broken","inaccessible"}:
            raise ValueError(f"invalid passage state: {passage.id}")
        if passage.key_item_id and passage.key_item_id not in world.item_catalog:
            raise ValueError(f"passage references unknown key: {passage.id}")
        passages[passage.id]=passage
    return PassageSystem(passages)


__all__=["PASSAGE_ACTION_ITEMS","PassageSystem","initialize_passages"]
