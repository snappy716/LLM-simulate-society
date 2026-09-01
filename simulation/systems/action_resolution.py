"""Fixed-difficulty checks and shared physical/legal consequences."""
from __future__ import annotations

import uuid

from simulation.domain.entities import ActionConsequences, EnvironmentCheckResult
from simulation.domain.planning import TraceEvidence


def outcome_for_margin(margin: int) -> str:
    if margin>=40:
        return "complete_success"
    if margin>=15:
        return "success"
    if margin>-15:
        return "partial"
    if margin>-40:
        return "failure"
    return "critical_failure"


class EnvironmentCheckSystem:
    def resolve(self,world,*,actor_id: str,check_type: str,skill: str,difficulty: int,
                target_id: str | None = None,context_modifier: int = 0,
                sequence_modifier: int = 0,item_effect_names: list[str] | None = None,
                direct_item_modifiers: dict[str,int] | None = None):
        if actor_id!="player" and actor_id not in world.npcs:
            raise KeyError(f"unknown actor: {actor_id}")
        if not 1<=difficulty<=200:
            raise ValueError("difficulty must be between 1 and 200")
        skills=world.player_skills if actor_id=="player" else world.npcs[actor_id].skills
        health=world.player_health if actor_id=="player" else world.npcs[actor_id].health
        skill_value=int(skills.get(skill,0))
        if actor_id!="player" and skill not in skills:
            npc=world.npcs[actor_id]; ability=npc.abilities
            composites={
                "lockpicking":npc.skills.get("stealth",0)+ability.get("dexterity",0)*2,
                "force_entry":npc.skills.get("combat",0)+ability.get("strength",0)*2,
                "climbing":npc.skills.get("stealth",0)+ability.get("dexterity",0)+ability.get("strength",0),
            }
            skill_value=int(composites.get(skill,0))
        effects=world.player_item_effects if actor_id=="player" else world.npcs[actor_id].item_effects
        direct_item_modifiers=direct_item_modifiers or {}
        values=sorted((max(0,int(max(effects.get(name,0),direct_item_modifiers.get(name,0))))
                       for name in (item_effect_names or [])),reverse=True)
        item_bonus=min(40,(values[0] if values else 0)+(values[1]//2 if len(values)>1 else 0))
        health_modifier=0 if health>=70 else -10 if health>=35 else -25
        modifiers={
            "skill":skill_value,"sequence":int(sequence_modifier),
            "items":item_bonus,"context":int(context_modifier),"health":health_modifier,
        }
        roll=world.rng.randint(1,100); total=roll+sum(modifiers.values())
        margin=total-difficulty
        result=EnvironmentCheckResult(
            check_type,actor_id,target_id,skill,difficulty,roll,modifiers,
            total,margin,outcome_for_margin(margin))
        world.ledger.emit(
            day=world.day,phase=world.phase.value,system="environment_check",
            event_type="ENVIRONMENT_CHECK_RESOLVED",
            message=f"{actor_id} 的{check_type}检定为 {result.outcome}（差值 {margin}）。",
            actor_ids=[actor_id],scene_id=self._scene(world,actor_id),payload=result.__dict__)
        return result

    @staticmethod
    def _scene(world,actor_id):
        return world.player_scene if actor_id=="player" else world.npcs[actor_id].current_scene


class ActionConsequenceSystem:
    MULTIPLIERS={
        "complete_success":0.0,"success":0.35,"partial":1.0,
        "failure":1.5,"critical_failure":2.0,
    }
    TOOL_DAMAGE={
        "complete_success":0,"success":0,"partial":-5,
        "failure":-15,"critical_failure":-30,
    }

    def apply(self,world,*,check: EnvironmentCheckResult,scene_id: str,
              base_legal_risk: int = 0,base_noise: int = 0,
              trace_type: str | None = None,trace_discoverability: int = 45,
              tool_instance_id: str | None = None,always_trace: bool = False):
        multiplier=self.MULTIPLIERS[check.outcome]
        risk=max(0,round(base_legal_risk*multiplier))
        noise=max(0,min(100,round(base_noise*(0.6+multiplier))))
        states=world.player_states if check.actor_id=="player" else world.npcs[check.actor_id].states
        if risk:
            states["legal_risk"]=min(100,states.get("legal_risk",0)+risk)
        trace_ids=[]
        if trace_type and (always_trace or check.outcome in {"partial","failure","critical_failure"}):
            discoverability=max(5,min(95,trace_discoverability+round(multiplier*12)))
            trace=TraceEvidence(
                id=f"trace_evidence_{uuid.uuid4().hex[:10]}",trace_type=trace_type,
                scene_id=scene_id,created_day=world.day,created_phase=world.phase.value,
                source_action_id=check.check_type,source_actor_ids=[check.actor_id],
                discoverability=discoverability,occult=False,
                payload={"target_id":check.target_id,"outcome":check.outcome})
            world.ritual_engine.traces[trace.id]=trace; trace_ids.append(trace.id)
        condition_delta=0
        if tool_instance_id:
            instance=world.item_instances.instances.get(tool_instance_id)
            if instance:
                condition_delta=self.TOOL_DAMAGE[check.outcome]
                instance.condition=max(0,min(100,instance.condition+condition_delta))
                if instance.condition==0:
                    instance.evidence_tags.append("broken")
        result=ActionConsequences(
            check.actor_id,scene_id,check.outcome,risk,noise,trace_ids,
            condition_delta,detected=noise>=45 or check.outcome=="critical_failure")
        world.ledger.emit(
            day=world.day,phase=world.phase.value,system="action_consequence",
            event_type="ACTION_CONSEQUENCES_APPLIED",
            message=f"{check.check_type}产生噪声 {noise}、法律风险 {risk}、痕迹 {len(trace_ids)}。",
            actor_ids=[check.actor_id],scene_id=scene_id,payload=result.__dict__)
        return result


__all__=["ActionConsequenceSystem","EnvironmentCheckSystem","outcome_for_margin"]
