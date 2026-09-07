"""Evidence-bound learning and slow life growth, shared by all actors.

The existing anomaly catalogue owns topic identities. These original teaching
chapter labels are not main-story books or quotations from real psychologists.
Defaults are additive: an old current-format actor starts with no new mastery.
"""
from copy import deepcopy
from simulation.domain.action_economy import build_action_economy_policy
from simulation.domain.campus import ATTRIBUTE_NAMES, BaseAttributes, derive_stats
from simulation.systems.campus_abilities import grant_ability_experience
from simulation.systems.campus_vitals import actor_layer, battle_locked
from simulation.systems.campus_departures import active_departure
from simulation.systems.time import consume_major_action
from simulation.systems.transactions import TransactionOutcome

GROWTH_ACTIONS = ("READ_KNOWLEDGE", "REFLECT_ON_CASE", "SET_STUDY_FOCUS", "CONFIGURE_ACTOR_DECK")
COMPONENT_CAPS = {"theory": 40, "cases": 30, "application": 20, "reflection": 10}
CHAPTER_NAMES = {
    "moon_fragment": "观察与注意", "shadow_collector": "习惯与重复",
    "missing_glyph": "姓名与身份", "rewritten_form": "叙事与矛盾",
    "silence_moth": "交流与沉默", "sleepwalking_shell": "梦与记忆",
    "empty_face": "自我确认", "light_chaser": "注意转移",
}


def _topics(state):
    return state.metadata.get("campus_combat", {}).get("enemy_archetypes", {})


def _growth(state):
    return state.knowledge.setdefault("growth", {"schema_version": 1, "actors": {}, "processed_events": {}})


def _actor_growth(state, actor_id):
    return _growth(state)["actors"].setdefault(actor_id, {
        "topics": {}, "study_focus": "", "attribute_practice": {}, "case_records": {},
        "application_sources": [], "deck_ids": [], "history": [],
    })


def _topic_progress(record, topic_id):
    return record["topics"].setdefault(topic_id, {key: 0 for key in COMPONENT_CAPS})


def mastery_by_topic(state, actor_id):
    record = state.knowledge.get("growth", {}).get("actors", {}).get(actor_id, {})
    return {topic_id: sum(values.values()) for topic_id, values in record.get("topics", {}).items()}


def _credit(record, topic_id, component, amount, source_id, day, phase):
    progress = _topic_progress(record, topic_id)
    before = progress[component]
    progress[component] = min(COMPONENT_CAPS[component], before + amount)
    gain = progress[component] - before
    if gain:
        record["history"].append({"topic_id": topic_id, "component": component, "gain": gain,
                                  "source_id": source_id, "day": day, "phase": phase})
        record["history"] = record["history"][-64:]
    return gain


def study_assessment(state, actor_id):
    actor = state.population[actor_id]
    location = actor.get("current_location_id")
    place = state.places.get(location, {})
    if battle_locked(state, actor_id):
        return False, "请先结束战斗准备或战斗。"
    if actor_layer(state, actor_id) != "surface":
        return False, "请返回表世界整理学习。"
    if location not in {"library_reading_hall", actor.get("home_location_id")}:
        return False, "请到图书馆阅览大厅或自己的住处学习。"
    if place.get("open_phases") and state.clock.phase not in place["open_phases"]:
        return False, "此处当前未开放。"
    if active_departure(state, actor_id):
        return False, "主要行动已为出击预留，请先处理出击预约。"
    if state.action_economy.get("actors", {}).get(actor_id, {}).get("major_remaining", 0) <= 0:
        return False, "本时段没有剩余主要行动。"
    return True, "阅读或反思消耗一次主要行动；不自动推进时段。"


def deck_catalog(state, actor_id):
    actor = state.population[actor_id]
    meta = state.metadata.get("campus_abilities", {}).get("card_blueprints", {})
    result = {key: deepcopy(meta[key]) for key in actor.get("card_pool_ids", []) if key in meta}
    for card in state.metadata.get("campus_combat", {}).get("round_policy", {}).get("generic_card_blueprints", []):
        result[card["card_id"]] = deepcopy(card)
    return result


def validate_deck(state, actor_id, cards):
    policy = state.metadata.get("campus_combat", {}).get("round_policy", {})
    size = policy.get("deck_size_per_actor", 8)
    if not isinstance(cards, list) or len(cards) != size or any(not isinstance(key, str) for key in cards):
        return "请选择八张指令牌，允许重复配置已有指令。"
    catalog = deck_catalog(state, actor_id)
    if any(key not in catalog for key in cards):
        return "牌组只能包含该角色已有能力牌与通用牌。"
    if any(key not in cards for key in policy.get("required_generic_card_ids", [])):
        return "请保留稳固架势与调整呼吸，保证基础防护与支援。"
    return ""


def configured_growth_deck(state, actor_id):
    return list(state.knowledge.get("growth", {}).get("actors", {}).get(actor_id, {}).get("deck_ids", []))


def _practice(state, actor_id, attribute, amount=1):
    if battle_locked(state, actor_id):
        return
    actor = state.population[actor_id]
    record = _actor_growth(state, actor_id)
    practice = record["attribute_practice"]
    current = actor["attributes"][attribute]
    if current >= 10:
        return
    practice[attribute] = practice.get(attribute, 0) + amount
    threshold = 8 + current * 2
    if practice[attribute] >= threshold:
        practice[attribute] -= threshold
        actor["attributes"][attribute] += 1
        # Growth raises capacity, never restores missing resources for free.
        stats = derive_stats(BaseAttributes(**actor["attributes"]), identity_anchor_count=len(actor.get("identity_anchor_ids", [])))
        if "vitals" in actor:
            actor["vitals"]["max_health"] = stats.max_health
            actor["vitals"]["max_focus"] = stats.max_focus


def project_growth_events(state, events):
    if "campus_abilities" not in state.metadata or not _topics(state):
        return
    supported = {"CAMPUS_ACTIVITY_EFFECT_APPLIED", "COMBAT_VICTORY", "COMBAT_DEFEAT_RESCUE",
                 "COMBAT_PARTY_RETREATED", "COMBAT_CARD_PLAYED", "COMBAT_BASE_COMMAND_USED", "KNOWLEDGE_INSIGHT_USED", "FORUM_TASK_COMPLETED"}
    for event in events:
        if event.event_type not in supported or event.event_id in state.knowledge.get("growth", {}).get("processed_events", {}):
            continue
        ledger = _growth(state)
        ledger["processed_events"][event.event_id] = event.day
        if event.event_type == "FORUM_TASK_COMPLETED":
            task = state.tasks.get(event.payload.get("task_id"), {})
            topic = task.get("enemy_archetype_id")
            # Combat victory supplies its own participant-specific cases below.
            # Existing investigation/stabilization/rescue task execution is also
            # a valid non-card-battle route; a forum post alone never qualifies.
            if (task.get("forum") != "night" or task.get("state") != "completed" or topic not in _topics(state)
                    or any(battle.get("situation_id") == task.get("task_id") and battle.get("result") == "victory" for battle in state.battles.values())):
                continue
            actor_id = task.get("assignee_id")
            if actor_id not in event.actor_ids or actor_id not in state.population:
                continue
            record = _actor_growth(state, actor_id)
            source = f"task:{task['task_id']}"
            if source not in record["case_records"]:
                record["case_records"][source] = {"topic_id": topic, "task_id": task["task_id"],
                    "event_id": event.event_id, "result": "task_completed", "day": event.day, "phase": event.phase,
                    "claim_id": state.knowledge.get("investigation", {}).get("observations", {}).get(event.event_id)}
                _credit(record, topic, "cases", 10, source, event.day, event.phase)
                if record["topics"][topic]["theory"] > 0:
                    _credit(record, topic, "application", 5, source, event.day, event.phase)
            continue
        if event.event_type == "CAMPUS_ACTIVITY_EFFECT_APPLIED":
            effects = event.payload.get("effects", {})
            # Free self-care and repeatable chat do not farm attributes/skills.
            if effects.get("budget", {}).get("action_class") != "major":
                continue
            for actor_id in event.actor_ids:
                actor = state.population[actor_id]
                category = effects.get("category")
                attribute = {"study": "focus", "research": "insight", "exploration": "dexterity",
                             "social": "empathy", "club": "expression", "work": "focus"}.get(category)
                activity = event.payload.get("activity_id")
                if activity in {"SECURITY_PATROL", "NIGHT_SECURITY_SHIFT"}:
                    attribute = "physique"
                elif activity in {"MAINTENANCE_SHIFT", "ON_CALL_MAINTENANCE"}:
                    attribute = "dexterity"
                elif activity in {"MEDICAL_SHIFT", "COUNSELING_SHIFT", "ON_CALL_MEDICAL_SHIFT"}:
                    attribute = "empathy"
                elif activity == "TEACH_CLASS":
                    attribute = "expression"
                if category == "club":
                    club_effect = effects.get("club", {})
                    club = state.organizations.get(club_effect.get("club_id"), {})
                    attribute = {"training_team": "physique", "expedition_team": "dexterity",
                                 "study_community": "insight", "volunteer_service": "empathy"}.get(club.get("category"), "expression")
                    if not club_effect.get("club_activity"):
                        attribute = None
                if attribute:
                    _practice(state, actor_id, attribute)
                if category in {"study", "research", "work"}:
                    for ability_id in actor.get("ability_progress", {}):
                        grant_ability_experience(state, actor_id, ability_id, 5)
                record = _actor_growth(state, actor_id)
                topic = record["study_focus"]
                if topic and category in {"study", "research"}:
                    _credit(record, topic, "theory", 5, event.event_id, event.day, event.phase)
            continue
        battle = state.battles.get(event.payload.get("battle_id"), {})
        if not battle:
            continue
        if event.event_type in {"COMBAT_VICTORY", "COMBAT_DEFEAT_RESCUE", "COMBAT_PARTY_RETREATED"}:
            for actor_id in battle.get("actor_decks", {}):
                record = _actor_growth(state, actor_id)
                for enemy in battle.get("enemy_units", {}).values():
                    topic = enemy.get("archetype_id")
                    if topic not in _topics(state):
                        continue
                    source = f"{battle['battle_id']}:{topic}"
                    if source in record["case_records"]:
                        continue
                    record["case_records"][source] = {"topic_id": topic, "battle_id": battle["battle_id"],
                        "result": battle.get("result"), "day": event.day, "phase": event.phase}
                    _credit(record, topic, "cases", 10, source, event.day, event.phase)
            continue
        for actor_id in event.actor_ids:
            record = _actor_growth(state, actor_id)
            for effect in event.payload.get("effects", []):
                enemy = battle.get("enemy_units", {}).get(effect.get("target_id"), {})
                topic = enemy.get("archetype_id")
                if (topic not in _topics(state) or effect.get("effect_id") not in {"reveal_pattern", "apply_disruption", "knowledge_insight"}
                        or record["topics"].get(topic, {}).get("theory", 0) <= 0):
                    continue
                source = f"{battle['battle_id']}:{topic}:{effect['effect_id']}"
                if source in record["application_sources"]:
                    continue
                record["application_sources"].append(source)
                _credit(record, topic, "application", 5, source, event.day, event.phase)
    # Active battle cards are projections of current personal understanding;
    # resolved encounters retain their historical combat values.
    for battle in state.battles.values():
        if battle.get("phase") != "resolved":
            for card in battle.get("character_cards", {}).values():
                card["knowledge_mastery"] = mastery_by_topic(state, card["actor_id"])


def make_growth_handler():
    def handle(context, command):
        state, actor_id, params = context.state, command.actor_id, command.parameters
        def fail(code, message):
            return TransactionOutcome(False, False, code, message)
        if actor_id not in state.population or (command.source == "player" and actor_id != "player"):
            return fail("actor_not_authorized", "不能替其他角色学习。")
        if command.issued_day != state.clock.day or command.issued_phase != state.clock.phase:
            return fail("command_clock_mismatch", "指令时段已过期。")
        if battle_locked(state, actor_id):
            return fail("battle_locked", "请先结束战斗准备或战斗。")
        record = _actor_growth(state, actor_id)
        payload = {"action_class": "free"}
        if command.action_id == "CONFIGURE_ACTOR_DECK":
            target = params.get("card_actor_id", actor_id)
            from simulation.systems.campus_parties import party_for_actor
            party = party_for_actor(state, actor_id) or {}
            controlled = [actor_id] + (party.get("member_ids", []) if party.get("leader_id") == actor_id else [])
            if not isinstance(target, str) or target not in controlled or battle_locked(state, target):
                return fail("deck_actor_not_controlled", "只能调整自己或当前队伍中未参战成员的牌组。")
            cards = params.get("card_ids")
            problem = validate_deck(state, target, cards)
            if problem:
                return fail("invalid_deck", problem)
            _actor_growth(state, target)["deck_ids"] = list(cards)
            payload.update(card_actor_id=target, card_ids=list(cards))
            message = "八张个人指令牌已保存，下次开战按此牌组洗牌。"
        else:
            topic = params.get("topic_id")
            if not isinstance(topic, str) or topic not in _topics(state):
                return fail("unknown_knowledge_topic", "请选择有效的研习主题。")
            if command.action_id == "SET_STUDY_FOCUS":
                record["study_focus"] = topic
                payload["topic_id"] = topic
                message = "已设为当前研习主题，后续学习和研究会结合该主题积累理论。"
            else:
                allowed, reason = study_assessment(state, actor_id)
                if not allowed:
                    return fail("study_unavailable", reason)
                progress = _topic_progress(record, topic)
                component = "theory" if command.action_id == "READ_KNOWLEDGE" else "reflection"
                if command.action_id not in {"READ_KNOWLEDGE", "REFLECT_ON_CASE"}:
                    return fail("unknown_action", "不支持的成长行动。")
                if progress[component] >= COMPONENT_CAPS[component]:
                    return fail("component_complete", "该部分已经完成；请通过其他来源加深理解，不扣行动。")
                if component == "reflection":
                    if progress["theory"] < 20 or progress["cases"] < 10:
                        return fail("reflection_requires_case", "反思需要至少 20 点理论和一份自己经历的案例。")
                    if state.inventories["actors"][actor_id]["quantities"].get("blank_notebook", 0) < 1:
                        return fail("notebook_required", "整理案例反思需要携带笔记本。")
                policy = build_action_economy_policy([{"id": key, **value} for key, value in state.action_economy["policy"]["phases"].items()])
                cost = consume_major_action(state, policy, command)
                if not cost.success:
                    return fail(cost.code, cost.message)
                gain = _credit(record, topic, component, 20 if component == "theory" else 10,
                               command.command_id, state.clock.day, state.clock.phase)
                _practice(state, actor_id, "focus" if component == "theory" else "insight")
                record["study_focus"] = topic
                payload.update(topic_id=topic, component=component, gain=gain, mastery=sum(progress.values()), action_class="major")
                message = f"{'理论阅读' if component == 'theory' else '案例反思'} +{gain}；当前理解度 {sum(progress.values())} / 100。"
        context.emit("CAMPUS_GROWTH_COMPLETED", message, actor_ids=[actor_id],
            scene_id=state.population[actor_id]["current_location_id"], payload=payload,
            visibility="private", knowledge_tags=["knowledge", "growth", "discovery"])
        return TransactionOutcome(True, True, "success", message, commit=True, payload=payload)
    return handle


def growth_view(state, actor_id="player"):
    if actor_id not in state.population or not _topics(state):
        return {"enabled": False, "topics": [], "deck_actors": []}
    actor = state.population[actor_id]
    record = state.knowledge.get("growth", {}).get("actors", {}).get(actor_id, {})
    allowed, reason = study_assessment(state, actor_id)
    topics = []
    for topic_id in _topics(state):
        progress = record.get("topics", {}).get(topic_id, {key: 0 for key in COMPONENT_CAPS})
        mastery = sum(progress.values())
        topics.append({"topic_id": topic_id, "name": CHAPTER_NAMES.get(topic_id, "异常观察研习"),
            "book_title": "校园跨学科研习讲义", "components": deepcopy(progress), "mastery": mastery,
            "damage_bonus_percent": round(mastery * .35, 2), "is_focus": record.get("study_focus") == topic_id,
            "can_read": allowed and progress["theory"] < 40,
            "can_reflect": allowed and progress["theory"] >= 20 and progress["cases"] >= 10 and progress["reflection"] < 10
                and state.inventories.get("actors", {}).get(actor_id, {}).get("quantities", {}).get("blank_notebook", 0) > 0,
            "milestones": {"information": mastery >= 25, "weakness": mastery >= 50, "interrupt": mastery >= 75,
                           "special_solution_ready": mastery == 100},
        })
    from simulation.systems.campus_parties import party_for_actor
    party = party_for_actor(state, actor_id) or {}
    controlled = list(dict.fromkeys([actor_id] + (party.get("member_ids", []) if party.get("leader_id") == actor_id else [])))
    decks = [{"actor_id": target, "name": state.population[target]["display_name"],
              "catalog": list(deck_catalog(state, target).values()), "deck_ids": configured_growth_deck(state, target),
              "can_configure": not battle_locked(state, actor_id) and not battle_locked(state, target)} for target in controlled]
    return {"enabled": True, "topics": topics, "study_reason": reason, "study_allowed": allowed,
            "attributes": deepcopy(actor.get("attributes", {})), "attribute_practice": deepcopy(record.get("attribute_practice", {})),
            "history": deepcopy(record.get("history", [])), "case_records": deepcopy(record.get("case_records", {})),
            "deck_actors": decks, "battle_locked": battle_locked(state, actor_id),
            "rule_note": "理论40＋案例30＋应用20＋反思10。知识不是诊断或真相；特殊解法需实际对象支持。牌组八张，可重复配置已有指令，保留防护和支援。"}


def growth_invariant(state):
    ledger = state.knowledge.get("growth")
    if ledger is None:
        return []
    if (not isinstance(ledger, dict) or ledger.get("schema_version") != 1
            or not isinstance(ledger.get("actors"), dict) or not isinstance(ledger.get("processed_events"), dict)):
        return ["invalid growth ledger"]
    errors = []
    for actor_id, record in ledger["actors"].items():
        if actor_id not in state.population or not isinstance(record, dict):
            errors.append("invalid growth actor")
            continue
        if any(not isinstance(record.get(key), dict) for key in ("topics", "attribute_practice", "case_records")) or any(not isinstance(record.get(key), list) for key in ("application_sources", "deck_ids", "history")):
            errors.append("invalid growth containers")
            continue
        if not isinstance(record.get("study_focus"), str) or (record["study_focus"] and record["study_focus"] not in _topics(state)):
            errors.append("invalid study focus")
        for topic, values in record["topics"].items():
            if (topic not in _topics(state) or not isinstance(values, dict) or set(values) != set(COMPONENT_CAPS)
                    or any(type(values[key]) is not int or not 0 <= values[key] <= cap for key, cap in COMPONENT_CAPS.items())):
                errors.append("invalid knowledge components")
        if record["deck_ids"] and validate_deck(state, actor_id, record["deck_ids"]):
            errors.append("invalid owned deck")
        if any(key not in ATTRIBUTE_NAMES or type(value) is not int or value < 0 for key, value in record["attribute_practice"].items()):
            errors.append("invalid attribute practice")
    return errors
