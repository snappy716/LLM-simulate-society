"""Always-available knowledge tactics, independent from shuffled hand cards."""
from simulation.systems.campus_growth import mastery_by_topic
from simulation.systems.transactions import TransactionOutcome


def knowledge_insight_options(state, battle, viewer_id):
    viewer = next((card for card in battle["character_cards"].values() if card["actor_id"] == viewer_id), {})
    result = []
    for card in battle["character_cards"].values():
        if card.get("deployment_state") != "deployed" or card.get("team_id") != viewer.get("team_id"):
            continue
        actor_id = card["actor_id"]
        mastery = mastery_by_topic(state, actor_id)
        for enemy_id, enemy in battle.get("enemy_units", {}).items():
            level = mastery.get(enemy["archetype_id"], 0)
            if level < 25 or battle["enemy_health"].get(enemy_id, 0) <= 0:
                continue
            for tactic, threshold, cost, name in (("observe", 25, 1, "辨析规律"), ("expose", 50, 1, "标记弱点"), ("interrupt", 75, 2, "打断异常")):
                if level < threshold:
                    continue
                key = f"{actor_id}:{enemy_id}:{tactic}"
                used = key in battle.get("knowledge_insight_used", [])
                result.append({"source_actor_id": actor_id, "source_name": card["display_name"], "target_id": enemy_id,
                    "target_name": enemy["display_name"], "tactic": tactic, "name": name, "mastery": level,
                    "command_cost": cost, "used": used,
                    "playable": battle.get("phase") == "player_turn" and not used
                        and battle["health"].get(actor_id, 0) > 0
                        and battle["command_points"].get(card["team_id"], 0) >= cost
                        and not (tactic == "interrupt" and "knowledge_interrupted" in enemy["statuses"]),
                })
    from simulation.systems.campus_evidence_insight import options
    return result + options(state, battle, viewer_id)


def use_knowledge_insight(context, command, battle):
    params = command.parameters
    source, target, tactic = params.get("source_actor_id", command.actor_id), params.get("target_id"), params.get("tactic")
    option = next((item for item in knowledge_insight_options(context.state, battle, command.actor_id)
                   if item["source_actor_id"] == source and item["target_id"] == target and item["tactic"] == tactic), None)
    if not option or not option["playable"]:
        return TransactionOutcome(False, False, "insight_unavailable", "理解度、参战状态、目标、费用或已使用次数不满足条件。")
    card = next(card for card in battle["character_cards"].values() if card["actor_id"] == source)
    enemy = battle["enemy_units"][target]
    battle["command_points"][card["team_id"]] -= option["command_cost"]
    battle.setdefault("knowledge_insight_used", []).append(f"{source}:{target}:{tactic}")
    if tactic == "ground":
        from simulation.systems.campus_evidence_insight import record_use
        record_use(context.state, battle, source, target)
        enemy["statuses"].append("knowledge_interrupted")
        message = "以本人确认的共同经历和所学知识识破这处残像，阻止它下一次攻击；只争取战术机会，不改变当事人的心结或替其恢复。"
    elif tactic == "interrupt":
        enemy["statuses"].append("knowledge_interrupted")
        message = "已识别异常重复模式，阻止该敌人下一次攻击（每名角色对该目标每战一次）。"
    elif tactic == "expose":
        for weakness in enemy["weaknesses"]:
            key = f"{target}:{weakness}"
            if key not in battle["known_weaknesses"]:
                battle["known_weaknesses"].append(key)
        if "knowledge_exposed" not in enemy["statuses"]:
            enemy["statuses"].append("knowledge_exposed")
        message = "已标记真实弱点；本战后续命中该弱点额外增加 15% 伤害。"
    else:
        row = {"front": "前", "middle": "中", "back": "后"}.get(enemy["row"], enemy["row"])
        message = f"辨析结果：{enemy['display_name']}当前位于{row}排，速度 {enemy['speed']}，接触污染强度 {enemy['pollution_power']}。"
    effects = [{"effect_id": "knowledge_insight", "target_id": target, "tactic": tactic}]
    battle["revision"] += 1
    context.emit("KNOWLEDGE_INSIGHT_USED", message, actor_ids=[source], scene_id=battle["scene_id"],
                 payload={"battle_id": battle["battle_id"], "effects": effects, "command_cost": option["command_cost"]},
                 visibility="private", knowledge_tags=["combat", "knowledge"])
    return TransactionOutcome(True, True, "success", message, commit=True,
                              payload={"battle_id": battle["battle_id"], "battle_revision": battle["revision"], "effects": effects})
