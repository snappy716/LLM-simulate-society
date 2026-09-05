"""Persistent expedition resources; battle ledgers are checked projections.

New encounters and layer transitions never heal. Only actual recovery actions
write actor vitals. Resolved battle records keep their historical values.
"""
from __future__ import annotations

from copy import deepcopy
from simulation.domain.campus import BaseAttributes, derive_stats
from simulation.systems.transactions import TransactionOutcome


def install_campus_vitals(state):
    state.metadata["campus_vitals"] = {"schema_version": 1}
    for actor in state.population.values():
        if "vitals" in actor:
            raise ValueError("campus vitals already installed")
        derived = derive_stats(BaseAttributes(**actor.get("attributes", {})),
                               identity_anchor_count=len(actor.get("identity_anchor_ids", [])))
        actor["vitals"] = {
            "health": derived.max_health, "max_health": derived.max_health,
            "focus": derived.max_focus, "max_focus": derived.max_focus,
        }


def actor_layer(state, actor_id):
    return state.situations.get("night_world", {}).get("actor_states", {}).get(actor_id, {}).get("layer", "surface")


def battle_locked(state, actor_id):
    return bool(state.metadata.get("campus_combat", {}).get("active_battle_by_actor", {}).get(actor_id))


def change_vital(state, actor_id, meter, amount):
    if meter not in {"health", "focus"} or type(amount) is not int:
        raise ValueError("invalid vital change")
    vitals = state.population[actor_id]["vitals"]
    before = vitals[meter]
    after = min(vitals["max_" + meter], max(0, before + amount))
    vitals[meter] = after
    battle_id = state.metadata.get("campus_combat", {}).get("active_battle_by_actor", {}).get(actor_id)
    if battle_id in state.battles:
        state.battles[battle_id][meter][actor_id] = after
    return {"before": before, "after": after, "delta": after - before}


def needs_recovery(actor):
    vitals = actor.get("vitals", {})
    return bool(vitals) and any(vitals[key] < vitals["max_" + key] for key in ("health", "focus"))


def rest_recovery_allowed(state, actor_id):
    actor = state.population[actor_id]
    location = actor.get("current_location_id")
    place = state.places.get(location, {})
    # Existing pooled rooms remain pooled; no simulation of every dorm room.
    return (actor_layer(state, actor_id) == "surface" and not battle_locked(state, actor_id)
            and location == actor.get("home_location_id")
            and (not place.get("open_phases") or state.clock.phase in place["open_phases"]))


def recover_by_rest(context, actor_id):
    state = context.state
    if not rest_recovery_allowed(state, actor_id):
        raise ValueError("rest recovery requires surface home and no active battle")
    vitals = state.population[actor_id]["vitals"]
    changes = {key: change_vital(state, actor_id, key, vitals["max_" + key])
               for key in ("health", "focus")}
    context.emit("CAMPUS_REST_RECOVERY", "充分休息后，生命值与专注全部恢复。",
                 actor_ids=[actor_id], scene_id=state.population[actor_id]["current_location_id"],
                 payload={"changes": changes, "major_action_cost": 1},
                 visibility="private", knowledge_tags=["rest", "recovery"])
    return changes


def recovery_skills(state, actor_id):
    blueprints = state.metadata.get("campus_abilities", {}).get("card_blueprints", {})
    return [deepcopy(blueprints[key]) for key in state.population[actor_id].get("card_pool_ids", [])
            if key in blueprints and "restore_health" in blueprints[key].get("effect_ids", [])]


def recovery_options(state, actor_id="player"):
    from simulation.systems.campus_parties import party_for_actor
    if actor_id not in state.population:
        return []
    party = party_for_actor(state, actor_id) or {}
    members = party.get("member_ids", []) if party.get("leader_id") == actor_id else []
    options = []
    for caster_id in dict.fromkeys([actor_id, *members]):
        actor = state.population[caster_id]
        if actor["current_location_id"] != state.population[actor_id]["current_location_id"] or actor_layer(state, caster_id) != actor_layer(state, actor_id):
            continue
        for skill in recovery_skills(state, caster_id):
            options.append({"caster_id": caster_id, "caster_name": actor.get("display_name", caster_id),
                            "skill_id": skill["card_id"], "name": skill["name"],
                            "focus_cost": max(1, int(skill["command_cost"])) * 10,
                            "focus": actor.get("vitals", {}).get("focus", 0)})
    return options


def make_field_recovery_handler():
    def handle(context, command):
        from simulation.systems.campus_parties import party_for_actor
        state, actor_id, params = context.state, command.actor_id, command.parameters
        if actor_id not in state.population or (command.source == "player" and actor_id != "player"):
            return TransactionOutcome(False, False, "unknown_actor", "不能替其他角色发出行动。")
        caster_id, target_id = params.get("caster_id", actor_id), params.get("target_id", actor_id)
        if not isinstance(caster_id, str) or not isinstance(target_id, str) or caster_id not in state.population or target_id not in state.population:
            return TransactionOutcome(False, False, "invalid_target", "施术者或目标不存在。")
        party = party_for_actor(state, actor_id) or {}
        if caster_id != actor_id and (party.get("leader_id") != actor_id or caster_id not in party.get("member_ids", [])):
            return TransactionOutcome(False, False, "caster_not_controlled", "只能指挥自己或已加入小队的成员。")
        if command.issued_day != state.clock.day or command.issued_phase != state.clock.phase:
            return TransactionOutcome(False, False, "command_clock_mismatch", "技能指令已过期。")
        for participant in {actor_id, caster_id, target_id}:
            if battle_locked(state, participant):
                return TransactionOutcome(False, False, "battle_locked", "战斗中请按战斗费用使用技能牌。")
            if (state.population[participant]["current_location_id"] != state.population[actor_id]["current_location_id"]
                    or actor_layer(state, participant) != actor_layer(state, actor_id)):
                return TransactionOutcome(False, False, "location_mismatch", "施术者和目标必须同地同层。")
        skill = next((entry for entry in recovery_skills(state, caster_id) if entry["card_id"] == params.get("skill_id")), None)
        if skill is None:
            return TransactionOutcome(False, False, "skill_unavailable", "施术者尚未拥有这项恢复技能。")
        cost = max(1, int(skill["command_cost"])) * 10
        caster, target = state.population[caster_id], state.population[target_id]
        if caster["vitals"]["health"] <= 0:
            return TransactionOutcome(False, False, "caster_incapacitated", "倒下的角色不能施术。")
        if caster["vitals"]["focus"] < cost:
            return TransactionOutcome(False, False, "insufficient_focus", "专注不足，无法使用恢复技能。")
        if target["vitals"]["health"] >= target["vitals"]["max_health"]:
            return TransactionOutcome(False, False, "no_effect", "目标生命值已满，不消耗专注。")
        derived = derive_stats(BaseAttributes(**caster.get("attributes", {})),
                               identity_anchor_count=len(caster.get("identity_anchor_ids", [])))
        amount = max(1, int(skill["base_power"]) + round(derived.support_power * .6) + round(derived.support_power * .2))
        spent = change_vital(state, caster_id, "focus", -cost)
        healed = change_vital(state, target_id, "health", amount)
        payload = {"caster_id": caster_id, "target_id": target_id, "skill_id": skill["card_id"], "focus": spent, "health": healed}
        context.emit("CAMPUS_FIELD_RECOVERY", f"{caster.get('display_name', caster_id)}使用{skill['name']}，恢复 {healed['delta']} 点生命值。",
                     actor_ids=list(dict.fromkeys([actor_id, caster_id, target_id])), payload=payload,
                     scene_id=target["current_location_id"], visibility="private", knowledge_tags=["recovery", "skill"])
        return TransactionOutcome(True, True, "success", f"恢复 {healed['delta']} 点生命值，消耗 {cost} 点专注。", commit=True, payload=payload)
    return handle


def campus_vitals_invariant(state):
    for actor_id, actor in state.population.items():
        vitals = actor.get("vitals")
        if vitals is None:
            if state.metadata.get("campus_vitals"):
                yield "missing campus vitals " + actor_id
            continue  # Generic pre-campus kernel fixtures.
        if not isinstance(vitals, dict):
            yield "invalid vitals " + actor_id
            continue
        for meter in ("health", "focus"):
            value, maximum = vitals.get(meter), vitals.get("max_" + meter)
            if type(value) is not int or type(maximum) is not int or maximum < 1 or not 0 <= value <= maximum:
                yield "invalid vital " + actor_id + ":" + meter
        battle_id = state.metadata.get("campus_combat", {}).get("active_battle_by_actor", {}).get(actor_id)
        if battle_id in state.battles:
            for meter in ("health", "focus"):
                if state.battles[battle_id].get(meter, {}).get(actor_id) != vitals.get(meter):
                    yield "battle vital projection differs " + actor_id + ":" + meter
