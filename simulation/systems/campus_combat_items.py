"""Combat use of the existing inventory, within the kernel transaction.

No battle-only stock or free backpack shortcut. The actor applying a medicine
spends their own item and the team's command point; the target keeps the same
vitals after combat. This first version supports existing healing consumables,
not food, resurrection, or removal of unrelated persistent pollution.
"""
from simulation.systems.campus_vitals import change_vital
from simulation.systems.transactions import TransactionOutcome

COMBAT_ITEM_COST = 1
ROWS = ("front", "middle", "back")


def _character(battle, actor_id):
    return next((card for card in battle.get("character_cards", {}).values()
                 if card.get("actor_id") == actor_id), {})


def _active(battle, actor_id):
    card = _character(battle, actor_id)
    return (card.get("deployment_state") == "deployed"
            and battle.get("health", {}).get(actor_id, 0) > 0)


def _targets(state, battle, source_id):
    source = _character(battle, source_id)
    if not _active(battle, source_id) or source.get("row") not in ROWS:
        return []
    result = []
    for target_id in battle.get("participant_ids", []):
        target = _character(battle, target_id)
        vitals = state.population[target_id]["vitals"]
        if (_active(battle, target_id) and target.get("team_id") == source.get("team_id")
                and target.get("row") in ROWS
                and abs(ROWS.index(source["row"]) - ROWS.index(target["row"])) <= 1
                and vitals["health"] < vitals["max_health"]):
            result.append(target_id)
    return result


def combat_item_options(state, battle, viewer_id):
    """Only disclose the deployed, controlled team's relevant consumables."""
    if battle.get("phase") != "player_turn":
        return []
    team_id = _character(battle, viewer_id).get("team_id")
    if not team_id:
        return []
    options = []
    for source_id in battle.get("participant_ids", []):
        source = _character(battle, source_id)
        if not _active(battle, source_id) or source.get("team_id") != team_id:
            continue
        targets = _targets(state, battle, source_id)
        for item_id, quantity in sorted(state.inventories["actors"][source_id]["quantities"].items()):
            rule = state.inventories["rules"].get(item_id, {})
            percent = rule.get("heal_percent", 0)
            if quantity <= 0 or type(percent) is not int or percent <= 0:
                continue
            options.append({
                "source_actor_id": source_id,
                "source_name": state.population[source_id].get("display_name", source_id),
                "item_id": item_id, "name": rule.get("name", item_id),
                "quantity": quantity, "command_cost": COMBAT_ITEM_COST, "heal_percent": percent,
                "target_ids": targets,
                "targets": [{"actor_id": target_id,
                             "name": state.population[target_id].get("display_name", target_id),
                             "heal_amount": min(
                                 state.population[target_id]["vitals"]["max_health"] - state.population[target_id]["vitals"]["health"],
                                 max(1, (state.population[target_id]["vitals"]["max_health"] * percent + 99) // 100))}
                            for target_id in targets],
                "playable": bool(targets) and battle["command_points"].get(team_id, 0) >= COMBAT_ITEM_COST,
            })
    return options


def use_combat_item(context, command, battle):
    state, params = context.state, command.parameters
    def fail(code, message):
        return TransactionOutcome(False, False, code, message)

    if command.source == "player" and command.actor_id != "player":
        return fail("actor_not_authorized", "玩家不能冒充其他角色发出物品指令。")
    if command.issued_day != state.clock.day or command.issued_phase != state.clock.phase:
        return fail("command_clock_mismatch", "物品指令所属时段已过期。")
    if battle.get("phase") != "player_turn":
        return fail("wrong_battle_phase", "只能在己方回合使用战斗物品。")
    source_id = params.get("source_actor_id", command.actor_id)
    target_id = params.get("target_id", source_id)
    item_id = params.get("item_id")
    if not all(isinstance(value, str) for value in (source_id, target_id, item_id)):
        return fail("invalid_target", "请选择使用者、药品和目标。")
    quantity = params.get("quantity", 1)
    if type(quantity) is not int or quantity != 1:
        return fail("invalid_quantity", "每次指令只能使用一份药品。")
    team_id = _character(battle, command.actor_id).get("team_id")
    if (not team_id or not _active(battle, source_id)
            or _character(battle, source_id).get("team_id") != team_id):
        return fail("source_not_controlled", "使用者必须是本队已部署且仍可行动的角色。")
    if target_id not in _targets(state, battle, source_id):
        return fail("invalid_healing_target", "只能治疗同排或相邻排仍可行动的受伤队友；满血或倒下时不消耗药品。")
    rule = state.inventories["rules"].get(item_id, {})
    percent = rule.get("heal_percent", 0)
    if type(percent) is not int or percent <= 0:
        return fail("item_not_combat_usable", "这种物品不能作为战斗治疗药品使用。")
    quantities = state.inventories["actors"][source_id]["quantities"]
    if quantities.get(item_id, 0) < 1:
        return fail("item_missing", "使用者自己的库存中没有这种药品。")
    if battle["command_points"].get(team_id, 0) < COMBAT_ITEM_COST:
        return fail("insufficient_command_points", "小队指令点不足，未消耗药品。")

    # Preflight ends here. All three resource changes commit or roll back together.
    before_quantity = quantities[item_id]
    quantities[item_id] -= 1
    if quantities[item_id] == 0:
        del quantities[item_id]
    battle["command_points"][team_id] -= COMBAT_ITEM_COST
    vitals = state.population[target_id]["vitals"]
    health = change_vital(state, target_id, "health", max(1, (vitals["max_health"] * percent + 99) // 100))
    battle["revision"] += 1
    payload = {"battle_id": battle["battle_id"], "battle_revision": battle["revision"],
               "source_actor_id": source_id, "target_id": target_id, "item_id": item_id,
               "quantity_before": before_quantity, "quantity_after": before_quantity - 1,
               "command_cost": COMBAT_ITEM_COST, "health": health, "action_class": "combat"}
    message = f"{state.population[source_id].get('display_name', source_id)}使用{rule.get('name', item_id)}，恢复 {health['delta']} 点生命值，消耗 1 点指令。"
    context.emit("COMBAT_ITEM_USED", message,
                 actor_ids=list(dict.fromkeys([source_id, target_id])),
                 scene_id=battle.get("scene_id"), payload=payload, visibility="private",
                 knowledge_tags=["combat", "inventory", "recovery"])
    return TransactionOutcome(True, True, "success", message, commit=True, payload=payload)
