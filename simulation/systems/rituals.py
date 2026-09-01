"""Atomic ritual recipes and material-backed ritual checks."""
from __future__ import annotations

from simulation.domain.interactions import RitualActionReceipt


LEGAL_RECIPE={"ritual_chalk":1}
SECRET_RECIPE={"ritual_chalk":1,"gray_ritual_powder":1}


class RitualMaterialSystem:
    def requirements(self,illegal: bool):
        return dict(SECRET_RECIPE if illegal else LEGAL_RECIPE)

    def material_bonus(self,world,illegal: bool) -> int:
        values=[]
        for item_id in self.requirements(illegal):
            definition=world.item_uses.definition(item_id)
            values.extend(int(value) for value in definition.grants_effects.values())
        values.sort(reverse=True)
        return min(40,(values[0] if values else 0)+(values[1]//2 if len(values)>1 else 0))

    def consume_required(self,world,actor_id: str,illegal: bool):
        recipe=self.requirements(illegal)
        inventory=world.economy.actor_inventory(actor_id)
        missing={item_id:quantity-inventory.quantity(item_id)
                 for item_id,quantity in recipe.items()
                 if inventory.quantity(item_id)<quantity}
        if missing:
            return {},missing
        before=dict(inventory.quantities)
        try:
            for item_id,quantity in recipe.items():
                inventory.remove(item_id,quantity)
            errors=world.economy.validate_invariants(world)
            if errors:
                raise RuntimeError("; ".join(errors))
        except Exception:
            inventory.quantities=before
            raise
        return recipe,{}

    def apply_material_side_effects(self,world,actor_id: str,illegal: bool):
        if not illegal:
            return 0,0
        states=(world.player_states if actor_id=="player" else world.npcs[actor_id].states)
        old_risk=states.get("legal_risk",0)
        states["legal_risk"]=min(100,old_risk+8)
        if actor_id=="player":
            old_sanity=world.player_sanity; world.player_sanity=max(0,old_sanity-3)
            sanity_delta=world.player_sanity-old_sanity
        else:
            actor=world.npcs[actor_id]; old_sanity=actor.sanity
            actor.sanity=max(0,old_sanity-3); sanity_delta=actor.sanity-old_sanity
        return sanity_delta,states["legal_risk"]-old_risk

    def perform(self,world,*,actor_id: str,scene_id: str,illegal: bool,resolver,
                difficulty_override: int | None = None):
        if actor_id!="player" and actor_id not in world.npcs:
            return self._failure(actor_id,illegal,"unknown_actor","行动者不存在。")
        actual_scene=(world.player_scene if actor_id=="player"
                      else world.npcs[actor_id].current_scene)
        if actual_scene!=scene_id:
            return self._failure(actor_id,illegal,"location_mismatch","行动者不在仪式地点。")
        consumed,missing=self.consume_required(world,actor_id,illegal)
        if missing:
            names="、".join(
                f"{world.item_catalog[item_id].name}×{quantity}"
                for item_id,quantity in missing.items())
            return RitualActionReceipt(
                False,"missing_materials",f"仪式缺少材料：{names}。",actor_id,illegal,
                missing_items=missing)
        bonus=self.material_bonus(world,illegal)
        direct={
            "ritual_powder_bonus":22 if illegal else 0,
            "ritual_chalk_bonus":10,
        }
        check,consequences,event=resolver(
            actor_id=actor_id,target_id="secret_ritual" if illegal else "legal_ritual",
            check_type="秘密仪式" if illegal else "合法仪式",skill="ritual",
            difficulty=max(1,min(200,int(difficulty_override if difficulty_override is not None else 72))),
            item_effect_names=list(direct),direct_item_modifiers=direct,
            base_legal_risk=18 if illegal else 0,base_noise=4,
            trace_type="spiritual_residue",trace_discoverability=68 if illegal else 25,
            always_trace=True)
        sanity_delta,material_risk=self.apply_material_side_effects(world,actor_id,illegal)
        succeeded=check.outcome in {"complete_success","success","partial"}
        actor_name="玩家" if actor_id=="player" else world.npcs[actor_id].name
        return RitualActionReceipt(
            True,"success" if succeeded else check.outcome,
            f"{actor_name}消耗完整配方举行{'秘密' if illegal else '合法'}仪式：{check.outcome}。",
            actor_id,illegal,consumed_items=consumed,material_bonus=bonus,
            ritual_succeeded=succeeded,sanity_delta=sanity_delta,
            legal_risk_delta=material_risk+consequences.legal_risk_delta,
            check=check,consequences=consequences,event_id=event.event_id)

    @staticmethod
    def _failure(actor_id,illegal,code,message):
        return RitualActionReceipt(False,code,message,actor_id,illegal)


__all__=["LEGAL_RECIPE","SECRET_RECIPE","RitualMaterialSystem"]
