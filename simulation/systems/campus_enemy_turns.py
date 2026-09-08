"""Telegraphed row attacks, shared vitals, and non-permanent defeat recovery."""
from __future__ import annotations

from simulation.systems.campus_vitals import change_vital

ROWS = ("front", "middle", "back")


def plan_enemy_intents(battle):
    deployed = [c for c in battle["character_cards"].values() if c.get("deployment_state") == "deployed"]
    target_row = next((row for row in ROWS if any(c.get("row") == row for c in deployed)), "front")
    intents = {}
    for enemy_id, enemy in sorted(battle["enemy_units"].items()):
        if battle["enemy_health"].get(enemy_id, 0) <= 0:
            continue
        intents[enemy_id] = {
            "round": battle["round"], "action_type": "physical_attack", "target_row": target_row,
            "power": 12 + int(enemy["speed"]) // 2 + int(enemy["defense"]) // 2,
            "pollution_power": int(enemy.get("pollution_power", 0)),
            "speed": int(enemy["speed"]),
        }
    return intents


def publish_enemy_intents(context, battle):
    intents = plan_enemy_intents(battle)
    battle["enemy_intents"] = intents
    context.emit("COMBAT_ENEMY_INTENTS", "异常显露了下一步攻击意图。",
                 actor_ids=battle["participant_ids"], payload={"battle_id": battle["battle_id"], "intents": intents},
                 scene_id=battle["scene_id"], visibility="private", knowledge_tags=["combat", "intent"])
    return intents


def _finish_defeat(context, battle):
    state = context.state
    battle["phase"] = "resolved"
    battle["result"] = "defeat"
    battle["revision"] += 1
    battle["consequences"]["rescue"] = {
        "recover_day": state.clock.day + 1, "actor_ids": list(battle["participant_ids"]), "recovered": False,
    }
    mapping = state.metadata["campus_combat"]["active_battle_by_actor"]
    night = state.situations["night_world"]
    for actor_id in battle["participant_ids"]:
        mapping.pop(actor_id, None)
        actor = state.population[actor_id]
        actor["current_location_id"] = actor["home_location_id"]
        actor.pop("current_decision", None)
        actor.pop("current_activity", None)
        layer = night["actor_states"][actor_id]
        layer.update(layer="surface", last_transition_day=state.clock.day, last_transition_phase=state.clock.phase)
        night["transition_sequence"] += 1
        if actor_id in night.get("active_actor_ids", []):
            night["active_actor_ids"].remove(actor_id)
    task = state.tasks.get(battle["situation_id"], {})
    if task.get("state") in {"locked", "in_progress"}:
        from simulation.systems.campus_tasks import _history, _settle_task_support_hooks, _settle_origin_hook
        task["state"] = "failed"
        task["lock_revision"] += 1
        owner = state.population.get(task.get("assignee_id"), {})
        if owner.get("active_forum_task_id") == task.get("task_id"):
            owner.pop("active_forum_task_id")
        task.setdefault("history", []).append(_history(state.clock.day, state.clock.phase, "failed", "小队败北，任务失败。"))
        _settle_task_support_hooks(state, task, "failed")
        _settle_origin_hook(state, task, "failed")
    context.emit("COMBAT_DEFEAT_RESCUE", "小队全员倒下，本次任务失败；被救回宿舍休息，已消耗物资不返还。",
                 actor_ids=battle["participant_ids"], payload={"battle_id": battle["battle_id"], "task_id": battle["situation_id"], "recover_day": state.clock.day + 1},
                 visibility="private", severity=5, knowledge_tags=["combat", "defeat", "recovery", "task"])


def recovering_from_defeat(state, actor_id):
    for battle in state.battles.values():
        rescue = battle.get("consequences", {}).get("rescue", {})
        if actor_id in rescue.get("actor_ids", []) and (
            not rescue.get("recovered") or rescue.get("recovery_marker") == [state.clock.day, state.clock.phase]
        ):
            return True
    return False


def recover_defeated_parties(context):
    state = context.state
    if state.clock.phase != "morning":
        return
    for battle in state.battles.values():
        rescue = battle.get("consequences", {}).get("rescue", {})
        if not rescue or rescue.get("recovered") or state.clock.day < rescue["recover_day"]:
            continue
        for actor_id in rescue["actor_ids"]:
            actor = state.population[actor_id]
            actor["current_location_id"] = actor["home_location_id"]
            for meter in ("health", "focus"):
                change_vital(state, actor_id, meter, actor["vitals"]["max_" + meter])
        rescue["recovered"] = True
        rescue["recovery_marker"] = [state.clock.day, state.clock.phase]
        context.emit("COMBAT_OVERNIGHT_RECOVERY", "次日清晨，小队在宿舍休息后生命与专注全部恢复。",
                     actor_ids=rescue["actor_ids"], payload={"battle_id": battle["battle_id"], "major_action_cost": 0},
                     visibility="private", knowledge_tags=["combat", "recovery", "rest"])


def resolve_enemy_turn(context, battle):
    from simulation.systems.campus_combat import (
        incapacitate_character, sync_combat_pollution_status,
    )

    intents = battle.get("enemy_intents")
    if not intents:
        # Older in-progress saves did not yet store intentions.
        intents = publish_enemy_intents(context, battle)
    results = []
    for enemy_id, intent in sorted(intents.items(), key=lambda entry: (-entry[1]["speed"], entry[0])):
        if battle["enemy_health"].get(enemy_id, 0) <= 0:
            continue
        enemy = battle["enemy_units"][enemy_id]
        if "knowledge_interrupted" in enemy["statuses"]:
            enemy["statuses"].remove("knowledge_interrupted")
            result = {"enemy_id": enemy_id, "target_row": intent["target_row"], "interrupted": True, "damage": 0}
            results.append(result)
            context.emit("COMBAT_ENEMY_ACTION", "洞察打断了异常本次攻击。", actor_ids=battle["participant_ids"],
                         payload={"battle_id": battle["battle_id"], **result}, scene_id=battle["scene_id"],
                         visibility="private", knowledge_tags=["combat", "knowledge", "interrupt"])
            continue
        targets = sorted((c for c in battle["character_cards"].values()
                          if c.get("deployment_state") == "deployed" and c.get("row") == intent["target_row"]),
                         key=lambda c: c["actor_id"])
        enemy = battle["enemy_units"][enemy_id]
        disrupted = "disrupted" in enemy["statuses"]
        if disrupted:
            enemy["statuses"].remove("disrupted")
        result = {"enemy_id": enemy_id, "target_row": intent["target_row"], "disrupted": disrupted, "missed": not targets}
        if targets:
            target = targets[0]
            actor_id = target["actor_id"]
            power = int(intent["power"]) // 2 if disrupted else int(intent["power"])
            pollution_before = int(battle["pollution"].get(actor_id, 0))
            pollution_damage_bonus = 6 if pollution_before >= 85 else 3 if pollution_before >= 60 else 1 if pollution_before >= 30 else 0
            damage = max(1, power - int(target["defense"]) + pollution_damage_bonus)
            absorbed = min(damage, int(battle["barriers"].get(actor_id, 0)))
            battle["barriers"][actor_id] = int(battle["barriers"].get(actor_id, 0)) - absorbed
            unabsorbed = damage - absorbed
            change = change_vital(context.state, actor_id, "health", -unabsorbed)
            pollution_gain = 0
            if unabsorbed > 0:
                pollution_gain = int(intent.get("pollution_power", 0))
                if disrupted:
                    pollution_gain //= 2
                pollution_gain = max(
                    0, pollution_gain - int(target.get("resistance", 0)) // 10
                )
            pollution_after = min(100, pollution_before + pollution_gain)
            battle["pollution"][actor_id] = pollution_after
            context.state.situations["night_world"]["actor_states"][actor_id][
                "pollution"
            ] = pollution_after
            stage = sync_combat_pollution_status(battle, actor_id)
            result.update(
                target_id=actor_id, damage=-change["delta"], absorbed=absorbed,
                health=change["after"], pollution_before=pollution_before,
                pollution_after=pollution_after, pollution_gain=pollution_after - pollution_before,
                pollution_stage=stage, pollution_damage_bonus=pollution_damage_bonus,
            )
            if change["after"] <= 0:
                incapacitate_character(context, battle, target["character_card_instance_id"])
        results.append(result)
        context.emit("COMBAT_ENEMY_ACTION", "敌方按预告排位发动攻击。" if targets else "预告排位已无人，敌方攻击落空。",
                     actor_ids=battle["participant_ids"], payload={"battle_id": battle["battle_id"], **result},
                     scene_id=battle["scene_id"], visibility="private", knowledge_tags=["combat", "damage", "intent"])
    for actor_id in battle["barriers"]:
        battle["barriers"][actor_id] = 0
    if not any(c.get("deployment_state") == "deployed" for c in battle["character_cards"].values()):
        _finish_defeat(context, battle)
    return results


def retreat_from_combat(context, battle):
    """Resolve the telegraphed pursuit before releasing a surviving party."""
    results = resolve_enemy_turn(context, battle)
    if battle.get("result") == "defeat":
        return {"enemy_results": results, "battle_resolved": True}
    state = context.state
    battle["phase"] = "resolved"
    battle["result"] = "escaped"
    battle["revision"] += 1
    mapping = state.metadata["campus_combat"]["active_battle_by_actor"]
    night = state.situations["night_world"]
    for actor_id in battle["participant_ids"]:
        if mapping.get(actor_id) == battle["battle_id"]:
            del mapping[actor_id]
        actor_state = night["actor_states"][actor_id]
        actor_state.update(
            layer="surface",
            last_transition_day=state.clock.day,
            last_transition_phase=state.clock.phase,
        )
        night["transition_sequence"] += 1
        if actor_id in night.get("active_actor_ids", []):
            night["active_actor_ids"].remove(actor_id)
    task = state.tasks.get(battle["situation_id"], {})
    task_reopened = False
    if task.get("state") in {"locked", "in_progress"}:
        from simulation.systems.campus_social import apply_task_social_consequence
        from simulation.systems.campus_tasks import (
            _history, _settle_origin_hook, _settle_task_support_hooks,
        )
        owner_id = str(task.get("assignee_id", ""))
        task["assignee_id"] = None
        task.pop("situation_choice", None)
        task["state"] = (
            "open" if state.clock.day <= int(task.get("expires_day", 0)) else "expired"
        )
        task_reopened = task["state"] == "open"
        task["lock_revision"] = int(task.get("lock_revision", 0)) + 1
        owner = state.population.get(owner_id, {})
        if owner.get("active_forum_task_id") == task.get("task_id"):
            owner.pop("active_forum_task_id")
        _settle_task_support_hooks(state, task, "abandoned")
        _settle_origin_hook(state, task, "abandoned")
        task["social_result"] = apply_task_social_consequence(
            state, owner_id, task, "abandoned"
        )
        task.setdefault("history", []).append(_history(
            state.clock.day, state.clock.phase, "retreated",
            "行动小队从现场撤退，任务锁定解除。",
        ))
    context.emit(
        "COMBAT_PARTY_RETREATED",
        "行动小队承受追击后撤回表世界，伤势与物资消耗保留。",
        actor_ids=battle["participant_ids"], scene_id=battle["scene_id"],
        payload={
            "battle_id": battle["battle_id"], "task_id": battle["situation_id"],
            "task_reopened": task_reopened, "enemy_results": results,
        },
        visibility="private", severity=4,
        knowledge_tags=["combat", "retreat", "task", "consequence"],
    )
    return {
        "enemy_results": results, "battle_resolved": True,
        "task_reopened": task_reopened,
    }
