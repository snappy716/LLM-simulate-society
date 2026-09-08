"""Bounded NPC controller of the SAME combat actions, never an alternate resolver.

Called after actual traversal, inside one world transaction. No provider calls,
invented equipment, off-screen healing or player-controlled party takeover.
"""
from dataclasses import replace
from simulation.systems.campus_combat import (
    active_battle_for_actor, campus_combat_view, combat_preparation_assessment,
    combat_readiness_assessment, night_combat_entry_cost,
)
from simulation.systems.campus_parties import create_party, party_for_actor, party_policy_from_state
from simulation.systems.campus_departures import has_upcoming_departure, active_departure as active_departure_for_member
from simulation.systems.campus_enemy_turns import recovering_from_defeat
from simulation.systems.transactions import TransactionOutcome
from simulation.systems.campus_expeditions import active_expedition, own_expedition_due, finish_expedition

DAMAGE = {"deal_physical", "deal_technique", "reveal_pattern", "apply_disruption", "specialization_effect"}
EXPECTED_NPC_COMBAT_FAILURES = {"npc_control_required", "task_not_owned", "party_commitment", "departure_reserved",
    "incapacitated", "recovering", "night_combat_action_exhausted", "invalid_phase", "night_layer_required",
    "task_location_required", "fear_limit", "injury_limit", "pollution_limit", "moral_boundary", "battle_already_active",
    "rescue_route_unavailable", "rescue_target_unavailable", "actor_stranded", "site_threat_active"}


def choose_combat_action(state, battle, leader_id, round_policy):
    """Only select the same playable options exposed to a controlling player."""
    options, candidates = battle["action_options"], []
    cards = {card["actor_id"]: card for card in battle["character_cards"].values()}
    def rank(blueprint, source, target):
        effects = set(blueprint.get("effect_ids", ()))
        if effects & DAMAGE:
            return 50 + float(blueprint.get("base_power", 0)) - float(blueprint.get("command_cost", 0)) * 2
        if "restore_health" in effects:
            missing = cards[target]["max_health"] - battle["health"][target]
            return 90 if battle["health"][target] < cards[target]["max_health"] * .45 else (20 if missing > 15 else -1)
        if "restore_focus" in effects:
            return 15 if cards[target]["max_focus"] - battle["focus"][target] > 10 else -1
        if "gain_barrier" in effects:
            return 12 if battle["barriers"].get(target, 0) == 0 else -1
        return 8 if effects else -1
    for instance_id, option in options["cards"].items():
        if not option["playable"]:
            continue
        blueprint = battle["card_instances"][instance_id]
        for target in option["target_ids"]:
            score = rank(blueprint, blueprint["owner_actor_id"], target)
            if score >= 0:
                candidates.append((score, "PLAY_COMBAT_CARD", instance_id + target,
                    {"card_instance_id": instance_id, "target_ids": [target]}))
    for source, option in options["base_commands"].items():
        if option["playable"]:
            blueprint = round_policy.base_command_blueprints[option["base_command_id"]]
            for target in option["target_ids"]:
                score = rank(blueprint, source, target)
                if score >= 0:
                    candidates.append((score, "USE_COMBAT_BASE_COMMAND", source + target,
                        {"source_actor_id": source, "target_ids": [target]}))
    for option in options["items"]:
        if not option.get("playable"):
            continue
        for target in option["target_ids"]:
            if battle["health"][target] < cards[target]["max_health"] * .4:
                candidates.append((85, "USE_COMBAT_ITEM", option["source_actor_id"] + option["item_id"] + target,
                    {"source_actor_id": option["source_actor_id"], "item_id": option["item_id"], "target_id": target}))
    for option in options.get("insights", []):
        if option["playable"] and option["tactic"] in {"interrupt", "expose"}:
            candidates.append((55 if option["tactic"] == "expose" else 40, "USE_KNOWLEDGE_INSIGHT",
                option["source_actor_id"] + option["target_id"] + option["tactic"],
                {key: option[key] for key in ("source_actor_id", "target_id", "tactic")}))
    if not candidates:
        return "END_COMBAT_ROUND", {}
    chosen = sorted(candidates, key=lambda row: (-row[0], row[1], row[2]))[0]
    return chosen[1], chosen[3]


def make_autonomous_combat_handler(combat_handler, policy, round_policy, graph, site_resolution_handler=None):
    def handle(context, command):
        state, actor_id = context.state, command.actor_id
        def fail(code, message):
            return TransactionOutcome(False, False, code, message)
        if actor_id == "player" or command.source != "rule" or actor_id not in state.population:
            return fail("npc_control_required", "后台战斗只控制独立 NPC，不控制玩家。")
        task_id = str(command.parameters.get("forum_task_id", command.parameters.get("task_id", "")))
        task = state.tasks.get(task_id, {})
        if task.get("forum") != "night" or task.get("assignee_id") != actor_id or task.get("state") != "locked":
            return fail("task_not_owned", "没有持有可执行的夜间任务。")
        from simulation.systems.campus_night_sites import site_for_task
        site = site_for_task(state, task)
        if site and site["status"] == "suppressed" and site_resolution_handler:
            return site_resolution_handler(context, replace(command, action_id="RESOLVE_NIGHT_SITE", parameters={
                "task_id": task_id, "expected_task_revision": task["lock_revision"]}))
        expedition = active_expedition(state, actor_id, leader_only=True)
        own_due = own_expedition_due(state, actor_id) and expedition["task_id"] == task_id
        if has_upcoming_departure(state, actor_id) and not own_due:
            return fail("departure_reserved", "已承诺参加另一场出击。")
        if recovering_from_defeat(state, actor_id):
            return fail("recovering", "正在等待正常次日恢复。")
        if active_battle_for_actor(state, actor_id):
            return fail("battle_already_active", "已有尚未结束的战斗。")
        party = party_for_actor(state, actor_id)
        if party is not None and (party["leader_id"] != actor_id or "player" in party["member_ids"]):
            return fail("party_commitment", "不能接管玩家或其他队长的小队。")
        if party is not None and len(party["member_ids"]) > 1 and not own_due:
            return fail("party_commitment", "协同行动需要先完成共同出击安排。")
        created = party is None
        if created:
            party = create_party(state, actor_id, party_policy_from_state(state), purpose_id="autonomous_task")
        assessment = combat_preparation_assessment(state, actor_id, policy, task_id=task_id)
        readiness = combat_readiness_assessment(state, actor_id, actor_id, policy, situation_id=task_id, graph=graph)
        entry = night_combat_entry_cost(state, [actor_id])
        if not assessment["allowed"] or not readiness["eligible"] or not entry["allowed"]:
            if created:
                del state.parties[party["party_id"]]
            code = assessment["reason"] if not assessment["allowed"] else readiness["reason"] if not readiness["eligible"] else "night_combat_action_exhausted"
            return fail(code, "当前地点、时段、状态或行动预算不允许出战。")
        deploying = [actor_id]
        if own_due:
            for member_id in party["member_ids"]:
                if member_id == actor_id:
                    continue
                eligible = combat_readiness_assessment(state, actor_id, member_id, policy, situation_id=task_id, graph=graph)
                cost = night_combat_entry_cost(state, [member_id])
                if eligible["eligible"] and cost["allowed"] and active_departure_for_member(state, member_id):
                    deploying.append(member_id)
        sequence = 0
        battle = None
        def issue(action, params=None):
            nonlocal sequence, battle
            sequence += 1
            parameters = dict(params or {})
            if battle is not None:
                parameters.update(battle_id=battle["battle_id"], expected_battle_revision=battle["revision"])
            result = combat_handler(context, replace(command, command_id=f"{command.command_id}:combat:{sequence}",
                action_id=action, parameters=parameters))
            if not result.success:
                raise RuntimeError(f"autonomous combat selected an invalid common action: {action}: {result.code}")
            return result
        started = issue("START_BATTLE_PREPARATION", {"task_id": task_id})
        battle = state.battles[started.payload["battle_id"]]
        for character_id, character in battle["character_cards"].items():
            if character["actor_id"] not in deploying:
                continue
            rows = [character["preferred_row"], *character["allowed_rows"]]
            destination = next(row for row in rows if len(battle["formations"][character["team_id"]][row]) < policy.row_capacity)
            issue("DEPLOY_COMBAT_CHARACTER", {"character_card_instance_id": character_id, "destination_row": destination})
        issue("CONFIRM_BATTLE_DEPLOYMENT")
        issue("START_CARD_COMBAT")
        # Termination guard retreats through the normal enemy pursuit pipeline.
        # This is a controller safety bound, not an automatic win or a chat cap.
        while battle["phase"] != "resolved":
            if battle["round"] > 12 or sequence >= 180:
                issue("RETREAT_CARD_COMBAT")
                break
            view = campus_combat_view(state, actor_id, policy, graph)["active_battle"]
            action, params = choose_combat_action(state, view, actor_id, round_policy)
            issue(action, params)
        result = battle["result"]
        receipt = {"battle_id": battle["battle_id"], "result": result, "rounds": battle["round"],
                   "actor_ids": list(battle["participant_ids"]), "day": state.clock.day, "phase": state.clock.phase}
        task.setdefault("execution_receipts", []).append(receipt)
        text = {"victory": "完成现场战斗", "defeat": "战败，被救回住处等待休息", "escaped": "承受追击后撤离"}.get(result, "结束现场战斗")
        task.setdefault("history", []).append({"day": state.clock.day, "phase": state.clock.phase, "kind": "combat_result",
            "message": f"实际卡牌战斗：{state.population[actor_id]['display_name']}经过 {battle['round']} 轮{text}。"})
        context.emit("NPC_NIGHT_TASK_EXECUTED", text, actor_ids=[actor_id], scene_id=battle["scene_id"],
                     visibility="secret", knowledge_tags=["night", "combat", "task"], payload={"task_id": task_id, **receipt})
        finish_expedition(context, task_id, receipt)
        if created:
            del state.parties[party["party_id"]]
        return TransactionOutcome(True, True, "success", text, commit=True,
            payload={"autonomous_battle": receipt, "task_completed": task["state"] == "completed", "effects": {}})
    return handle


def autonomous_combat_invariant(state):
    """Validate new receipts without inventing proof for pre-controller completed tasks."""
    errors, seen = [], set()
    try:
        for task in state.tasks.values():
            for receipt in task.get("execution_receipts", []):
                battle = state.battles.get(receipt["battle_id"], {})
                if (receipt["battle_id"] in seen or battle.get("situation_id") != task.get("task_id")
                        or battle.get("phase") != "resolved" or receipt["result"] != battle.get("result")
                        or receipt["actor_ids"] != battle.get("participant_ids") or "player" in receipt["actor_ids"]
                        or type(receipt["rounds"]) is not int or receipt["rounds"] != battle.get("round")
                        or type(receipt["day"]) is not int or receipt["day"] < 1
                        or receipt["phase"] not in {"evening", "late_night"}):
                    errors.append("invalid NPC combat execution receipt")
                seen.add(receipt["battle_id"])
            proof = task.get("completion_evidence")
            if proof is not None and task.get("resolution_kind") not in {"field_recon", "contact_inquiry"} and not task.get("night_site_id"):
                battle = state.battles.get(proof["battle_id"], {})
                if (proof.get("kind") != "combat_victory" or battle.get("result") != "victory"
                        or battle.get("situation_id") != task.get("task_id") or task.get("state") != "completed"):
                    errors.append("invalid completed combat task evidence")
    except (KeyError, TypeError, AttributeError):
        errors.append("invalid nested NPC combat receipt structure")
    return errors
