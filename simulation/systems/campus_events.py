"""Competitions and collaborative festivals on the existing life ledger.

Actual performance freezes pre-action inputs. End-of-phase results include only
completed attendance; no separate prize, task, wallet or invented audience.
"""
from copy import copy, deepcopy

def event_definition_errors(definitions, item_ids):
    from simulation.domain.campus import ATTRIBUTE_NAMES
    for row in definitions.values():
        config = row.get("event") if isinstance(row, dict) else None
        if config is None:
            continue
        if (not isinstance(config, dict) or config.get("kind") not in {"competition", "festival"}
                or row.get("course") or row.get("job")
                or not isinstance(config.get("attributes"), dict) or not config["attributes"]
                or any(k not in ATTRIBUTE_NAMES or type(v) is not int or not 1 <= v <= 5 for k,v in config["attributes"].items())
                or config.get("practice_category") not in {"study", "social", "exploration", "club"}
                or not isinstance(config.get("check_tags"), list) or not config["check_tags"]
                or any(not isinstance(t, str) or not t for t in config["check_tags"])
                or not isinstance(config.get("preparation_topic"), str)
                or config.get("tool_id") not in item_ids
                or type(config.get("club_resource_cost")) is not int or config["club_resource_cost"] < 1
                or (config["kind"] == "competition" and (type(config.get("qualifying_score")) is not int or config["qualifying_score"] < 1))
                or (config["kind"] == "festival" and (type(config.get("target_score")) is not int or config["target_score"] < 1
                    or type(config.get("minimum_participants")) is not int or config["minimum_participants"] < 2))):
            yield "invalid campus event definition"


def options_problem(state, actor_id, row, options):
    if not isinstance(options, dict) or set(options) - {"club_id", "use_club_resources"}:
        return "invalid_event_options", "活动选项不合法；成绩与奖励由实际执行决定。"
    club_id, support = options.get("club_id", ""), options.get("use_club_resources", False)
    if not isinstance(club_id, str) or type(support) is not bool:
        return "invalid_event_options", "请选择有效的代表社团与资源选项。"
    if not row.get("event"):
        return ("invalid_event_options", "这项活动不使用比赛/节庆选项。") if options else None
    if not club_id:
        return ("event_club_required", "使用社团资源须先选择本人有权限的社团。") if support else None
    club = state.organizations.get(club_id, {})
    member = club.get("memberships", {}).get(actor_id)
    if not member:
        return "event_not_member", "只能代表本人当前加入的社团；也可以退出报名后改为个人参加。"
    if support:
        if member.get("rank") not in {"core_member", "leader"}:
            return "event_resource_permission", "只有骨干或负责人可以使用社团公共资源。"
        if club.get("resources", {}).get("current", 0) < row["event"]["club_resource_cost"]:
            return "event_resource_unavailable", "社团资源不足，尚未扣行动或记出勤；可退出后改为个人或无资源参加。"
    return None


def event_options(state, actor_id, row):
    """Existing dawn candidate carries explicit NPC choices, not extra LLM calls."""
    if not row.get("event"):
        return {}
    actor = state.population[actor_id]
    clubs = sorted((c for c in state.organizations.values() if actor_id in c.get("memberships", {})),
        key=lambda c: (-c["memberships"][actor_id].get("contribution", 0), c["organization_id"]))
    if not clubs or actor.get("personality", {}).get("altruism", 50) < 40:
        return {}
    club = clubs[0]
    options = {"club_id": club["organization_id"], "use_club_resources": False}
    supported = {**options, "use_club_resources": True}
    # Preserve a reserve for ordinary club work; no automatic player spending.
    if (actor.get("personality", {}).get("conscientiousness", 50) >= 55
            and club.get("resources", {}).get("current", 0) >= 2 * row["event"]["club_resource_cost"]
            and not options_problem(state, actor_id, row, supported)):
        options = supported
    return options


def performance_inputs(state, actor_id, row, options):
    config, actor = row["event"], state.population[actor_id]
    attributes = {k: actor["attributes"][k] for k in config["attributes"]}
    practice = actor.get("activity_progress", {}).get("by_category", {}).get(config["practice_category"], 0)
    knowledge = state.knowledge.get("actors", {}).get(actor_id, {}).get("topics", {}).get(config["preparation_topic"], 0)
    quantity = state.inventories.get("actors", {}).get(actor_id, {}).get("quantities", {}).get(config["tool_id"], 0)
    fatigue = actor.get("needs", {}).get("rest", 0)
    from simulation.systems.campus_abilities import ability_modifier_for_check
    ability = ability_modifier_for_check(state, actor_id, config["check_tags"])
    components = {"attributes": sum(attributes[k] * w for k,w in config["attributes"].items()), "ability": ability["modifier"],
        "practice": min(6, practice), "preparation": min(6, knowledge // 4),
        "tool": 4 if quantity > 0 else 0, "organization": 8 if options.get("use_club_resources") else 0,
        "fatigue": -(fatigue // 20)}
    return {"inputs": {"attributes": attributes, "practice_count": practice, "knowledge_progress": knowledge,
        "tool_quantity": quantity, "rest_need": fatigue, "ability": ability,
        "ability_ranks": {key: progress["rank"] for key, progress in actor.get("ability_progress", {}).items()}},
        "components": components, "score": max(0, sum(components.values()))}


def event_motivation(state, actor_id, row):
    """Personal reasons to prefer a limited weekly event over generic routine.

    No invitation quota, attendance floor or winner-dependent forced decision.
    Habit/novelty is based only on this actor's actual previous participation.
    """
    if not row.get("event"):
        return 0, ""
    actor, kind = state.population[actor_id], row["event"]["kind"]
    member = any(actor_id in c.get("memberships", {}) for c in state.organizations.values())
    trait = "altruism" if kind == "festival" else "conscientiousness"
    value = "belonging" if kind == "festival" else "achievement"
    records = state.situations.get("campus_life", {}).get("records", {})
    recent = [r[actor_id] for sid,r in records.items() if sid.endswith(":" + row["id"]) and actor_id in r
        and r[actor_id]["status"] == "completed" and 0 <= row["day"] - r[actor_id]["completed_day"] <= 7]
    score = (6 if member else 0) + (3 if value in actor.get("core_values", ()) else 0)
    score += max(0, actor.get("personality", {}).get(trait, 50) - 40) * .08
    score += max(0, actor.get("personality", {}).get("openness", 50) - 40) * .08 / (1 + len(recent))
    if any(row["day"] - r["completed_day"] <= 1 for r in recent):
        score -= 4
    return round(score, 3), "可自愿展示本社团成果，结合本人兴趣与近期真实参加经历权衡" if member else "可尝试每周校园展示，结合本人兴趣与近期真实参加经历权衡"


def own_event_context(state, actor_id):
    data = state.situations.get("campus_life", {})
    result = []
    for sid, actors in data.get("records", {}).items():
        row = data.get("definitions", {}).get(sid.split(":")[-1], {})
        record = actors.get(actor_id, {})
        if not row.get("event") or record.get("status") not in {"completed", "missed"}:
            continue
        receipt = record.get("result", {}).get("event", {})
        result.append({"day": int(sid.split(":")[1]), "name": row["name"], "status": record["status"],
            "summary": receipt.get("summary", "报名后未实际参加；没有出勤或奖励。")})
    return sorted(result, key=lambda r: (r["day"], r["name"]), reverse=True)[:3]


def prepare_performance(context, command):
    """Read only, after validation but before effects/knowledge/practice gains."""
    from simulation.systems.campus_life import session, participant
    sid = command.parameters.get("life_session_id")
    row = session(context.state, sid)
    if not row or not row.get("event"):
        return None
    options = participant(context.state, command.actor_id, sid).get("event_options", {})
    return performance_inputs(context.state, command.actor_id, row, options)


def settle_performance(context, actor_id, row, record, prepared):
    options = record.get("event_options", {})
    club_id = options.get("club_id", "")
    club = context.state.organizations.get(club_id, {})
    receipt = {**deepcopy(prepared), "kind": row["event"]["kind"], "club_id": club_id,
        "club_name": club.get("name", ""), "finalized": False, "resource_cost": 0,
        "summary": "已实际展示；时段结束后统一公布结果，当前不是最终排名。"}
    if options.get("use_club_resources"):
        resources = club["resources"]
        cost = row["event"]["club_resource_cost"]
        receipt.update(resource_cost=cost, resource_before=resources["current"], resource_after=resources["current"] - cost)
        resources["current"] -= cost
        resources["spent_total"] += cost
        from simulation.systems.campus_clubs import _append_history
        _append_history(club, context.state, "campus_event_preparation", actor_id=actor_id, session_id=row["session_id"], resource_spent=cost)
    return receipt


def _outcome(row, receipt, scores):
    config, score = row["event"], receipt["score"]
    if config["kind"] == "competition":
        rank = 1 + sum(other > score for other in scores)
        awarded = rank <= 3 and score >= config["qualifying_score"]
        return {"rank": rank, "outcome": "placed" if awarded else "participated", "recognized": awarded,
            "summary": f"第 {rank} 名（同分并列），表现 {score}；" + ("达到入选标准。" if awarded else "未入选，可通过上课、练习与准备再挑战。")}
    total = sum(scores)
    complete = len(scores) >= config["minimum_participants"] and total >= config["target_score"]
    return {"total_score": total, "outcome": "full_festival" if complete else "small_exchange", "recognized": complete,
        "summary": f"{len(scores)} 人实际参展，总贡献 {total}/{config['target_score']}；" + ("完成联合展示。" if complete else "形成小型交流，下一场可邀请伙伴补足展示。")}


def finalize_events(context):
    from simulation.systems.campus_life import ledger, session, stamp
    state, count = context.state, 0
    for sid, actors in ledger(state).get("records", {}).items():
        row = session(state, sid)
        if not row or not row.get("event") or stamp(row["day"], row["phase"]) >= stamp(state.clock.day, state.clock.phase):
            continue
        entries = {actor: record["result"]["event"] for actor, record in actors.items() if record["status"] == "completed"}
        scores = [r["score"] for r in entries.values()]
        for actor_id, receipt in entries.items():
            if receipt["finalized"]:
                continue
            outcome = _outcome(row, receipt, scores)
            actor = state.population[actor_id]
            actor["emotions"]["joy"] = min(100, actor["emotions"]["joy"] + (3 if outcome["recognized"] else 1))
            actor["needs"]["achievement"] = max(0, actor["needs"]["achievement"] - (10 if outcome["recognized"] else 3))
            club_id = receipt["club_id"]
            club = state.organizations.get(club_id, {})
            member = club.get("memberships", {}).get(actor_id)
            contribution = (3 if outcome["recognized"] else 1) if member else 0
            if member:
                member["contribution"] += contribution
                from simulation.systems.campus_clubs import _append_history
                _append_history(club, state, "campus_event_result", actor_id=actor_id, session_id=sid, contribution=contribution)
            receipt.update(**outcome, finalized=True, contribution=contribution)
            count += 1
        if entries and not all(r.get("announced") for r in entries.values()):
            # Public performance/result only, never private attributes, needs,
            # relationship/contact data or club resource balances.
            context.emit("CAMPUS_EVENT_RESULTS", f"{row['name']}已结束，{len(entries)} 人实际参加；结果已公布。",
                actor_ids=sorted(entries), scene_id=row["location_id"], visibility="public", knowledge_tags=["campus_life", "club", "event_results"],
                payload={"session_id": sid, "name": row["name"], "results": [_public_entry(state, a, r) for a,r in sorted(entries.items())]})
            for receipt in entries.values():
                receipt["announced"] = True
    return {"campus_event_results": count}


def _public_entry(state, actor_id, receipt):
    return {"actor_id": actor_id, "name": state.population[actor_id].get("display_name", actor_id),
        "club_name": receipt["club_name"], **{k: deepcopy(receipt[k]) for k in ("score", "rank", "outcome", "summary") if k in receipt}}


def event_board(state):
    from simulation.systems.campus_life import ledger, session, stamp
    board = []
    now = stamp(state.clock.day, state.clock.phase)
    available = ledger(state).get("events_available_from", {"day": 1, "phase": "morning"})
    for day in range(max(1, state.clock.day - 7), state.clock.day + 1):
        for key, definition in ledger(state).get("definitions", {}).items():
            if not definition.get("event"):
                continue
            row = session(state, f"life:{day}:{key}")
            if not row or not stamp(available["day"], available["phase"]) <= stamp(day, row["phase"]) <= now:
                continue
            ended = stamp(day, row["phase"]) < now
            actors = ledger(state)["records"].get(row["session_id"], {})
            results = [_public_entry(state, a, r["result"]["event"]) for a,r in actors.items()
                if r["status"] == "completed" and r["result"]["event"].get("finalized")]
            results.sort(key=lambda r: (r.get("rank", 0), -r["score"], r["actor_id"]))
            board.append({"session_id": row["session_id"], "name": row["name"], "day": day, "phase": row["phase"],
                "ended": ended, "summary": ("已结束；无人实际参加，不生成获奖者。" if not results else "正式结果（仅公开展示记录）") if ended else "进行中；全部参与者结束后统一公布成绩。",
                "results": results})
    return list(reversed(board))


def event_view(state, actor_id, row):
    from simulation.systems.campus_life import participant
    config = row.get("event")
    if not config:
        return {}
    choices = [{"club_id": "", "name": "个人参加", "can_use_resources": False}]
    for key, club in sorted(state.organizations.items()):
        if actor_id in club.get("memberships", {}):
            choices.append({"club_id": key, "name": club["name"], "can_use_resources": not options_problem(state, actor_id, row, {"club_id": key, "use_club_resources": True})})
    own = participant(state, actor_id, row["session_id"]) or {}
    return {"kind": config["kind"], "club_choices": choices, "event_options": deepcopy(own.get("event_options", {})),
        "summary": "表现取决于本人属性、已掌握的相关学院技能、既有练习、课程准备、笔记本和可选社团资源；准备不保证获胜。实际参加 1 主要行动，笔记本不消耗。社团资源在实际到场时复核并扣除 %d；报名不锁定公共资源。" % config["club_resource_cost"]}


def events_invariant(state):
    from simulation.systems.campus_life import ledger, session
    data = ledger(state)
    available = data.get("events_available_from")
    if available is not None:
        from simulation.systems.campus_life import PHASE_IDS
        if (not isinstance(available, dict) or type(available.get("day")) is not int or available["day"] < 1
                or available.get("phase") not in PHASE_IDS):
            yield "invalid campus event availability"
    errors = list(event_definition_errors(data.get("definitions", {}), state.inventories.get("catalog", {})))
    if errors:
        yield from errors
        return
    for sid, actors in data.get("records", {}).items():
        row = session(state, sid)
        if not row or not isinstance(actors, dict):
            continue
        scores = [r.get("result", {}).get("event", {}).get("score") for r in actors.values() if isinstance(r, dict) and r.get("status") == "completed"]
        for actor, record in actors.items():
            if not isinstance(record, dict):
                continue
            options = record.get("event_options", {})
            if (not isinstance(options, dict) or set(options) - {"club_id", "use_club_resources"}
                    or not isinstance(options.get("club_id", ""), str) or type(options.get("use_club_resources", False)) is not bool):
                yield "invalid campus event options"
                continue
            receipt = record.get("result", {}).get("event")
            if not row.get("event"):
                if options or receipt:
                    yield "unexpected campus event receipt"
                continue
            if record.get("status") != "completed":
                if receipt:
                    yield "unearned campus event receipt"
                continue
            if not isinstance(receipt, dict):
                yield "missing campus event receipt"
                continue
            components = receipt.get("components", {})
            if (not isinstance(components, dict) or set(components) != {"attributes", "ability", "practice", "preparation", "tool", "organization", "fatigue"}
                    or any(type(v) is not int for v in components.values()) or type(receipt.get("score")) is not int
                    or receipt["score"] != max(0, sum(components.values())) or type(receipt.get("finalized")) is not bool
                    or receipt.get("kind") != row["event"]["kind"] or receipt.get("club_id") != options.get("club_id", "")):
                yield "invalid campus event performance"
                continue
            inputs = receipt.get("inputs", {})
            config = row["event"]
            attributes = inputs.get("attributes", {}) if isinstance(inputs, dict) else {}
            ability = inputs.get("ability", {}) if isinstance(inputs, dict) else {}
            ranks = inputs.get("ability_ranks", {}) if isinstance(inputs, dict) else {}
            if (not isinstance(attributes, dict) or set(attributes) != set(config["attributes"])
                    or any(type(v) is not int or not 1 <= v <= 10 for v in attributes.values())
                    or not isinstance(ability, dict) or ability.get("actor_id") != actor
                    or ability.get("check_tags") != sorted(config["check_tags"])
                    or type(ability.get("modifier")) is not int or not 0 <= ability["modifier"] <= 6
                    or not isinstance(ranks, dict) or set(ranks) != set(state.population[actor].get("ability_progress", {}))
                    or any(type(v) is not int or not 1 <= v <= 5 for v in ranks.values())
                    or any(type(inputs.get(k)) is not int or inputs[k] < 0 for k in ("practice_count", "knowledge_progress", "tool_quantity", "rest_need"))):
                yield "invalid campus event inputs"
                continue
            from simulation.systems.campus_abilities import ability_modifier_for_check
            preview = copy(state)
            preview.population = {actor: {**state.population[actor], "ability_progress": {k: {"rank": v} for k,v in ranks.items()}}}
            if ability != ability_modifier_for_check(preview, actor, config["check_tags"]):
                yield "invalid campus event ability receipt"
            expected_components = {"attributes": sum(attributes[k] * w for k,w in config["attributes"].items()), "ability": ability["modifier"],
                "practice": min(6, inputs["practice_count"]), "preparation": min(6, inputs["knowledge_progress"] // 4),
                "tool": 4 if inputs["tool_quantity"] else 0, "organization": 8 if options.get("use_club_resources") else 0,
                "fatigue": -(inputs["rest_need"] // 20)}
            if components != expected_components:
                yield "campus event score does not match inputs"
            cost = row["event"]["club_resource_cost"] if options.get("use_club_resources") else 0
            if (receipt.get("resource_cost") != cost or (cost and (type(receipt.get("resource_before")) is not int
                    or type(receipt.get("resource_after")) is not int or receipt["resource_after"] < 0
                    or receipt["resource_before"] - receipt["resource_after"] != cost))):
                yield "invalid campus event resource receipt"
            if receipt["finalized"] and all(type(s) is int for s in scores):
                expected = _outcome(row, receipt, scores)
                if any(receipt.get(k) != v for k,v in expected.items()):
                    yield "invalid campus event result"
