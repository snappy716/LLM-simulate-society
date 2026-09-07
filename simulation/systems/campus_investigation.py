"""Source-bound campus investigation; facts, beliefs, notes and hypotheses differ.

Facts come from existing notices, inspected physical stock, and committed
events. A client or language model cannot provide their contents or confidence.
No world-wide truth catalogue is exposed through the personal notebook view.
"""
from copy import deepcopy

from simulation.domain.action_economy import build_action_economy_policy
from simulation.systems.campus_intelligence import create_campus_claim, known_claims, share_specific_known_claim, disclosable_known_claims
from simulation.systems.campus_vitals import actor_layer, battle_locked
from simulation.systems.time import consume_major_action
from simulation.systems.transactions import TransactionOutcome
from simulation.systems.campus_departures import active_departure
from simulation.domain.entities import PHASES

INVESTIGATION_ACTIONS = (
    "OBSERVE_SCENE", "SEARCH_SCENE", "RECORD_EVIDENCE", "ASK_ABOUT_EVIDENCE",
    "SHARE_EVIDENCE", "SET_EVIDENCE_DISCLOSURE", "LINK_EVIDENCE",
)


def _ledger(state):
    # Additive empty runtime state: loading an earlier current-format save does
    # not invent evidence, regenerate NPCs or replenish resources.
    return state.knowledge.setdefault("investigation", {
        "schema_version": 1, "traces": {}, "observations": {}, "notes_by_actor": {},
        "hypotheses_by_actor": {}, "withheld_by_actor": {}, "last_query_by_pair": {},
    })


def _region(state, location):
    return state.places.get(location, {}).get("region_id") or location


def _context(state, location, layer, kind, source_id):
    return {"location_id": location, "layer": layer, "source_kind": kind,
            "source_id": source_id, "day": state.clock.day, "phase": state.clock.phase}


def project_investigation_events(state, events):
    """Record only explicitly supported facts, never private dialogue wording."""
    if not state.knowledge.get("claims"):
        return
    for event in events:
        task = state.tasks.get(event.payload.get("task_id"), {})
        is_task = event.event_type == "FORUM_TASK_COMPLETED" and bool(task)
        is_item = event.event_type == "CAMPUS_ITEM_ACTION_COMPLETED"
        if not (is_task or is_item) or not event.actor_ids:
            continue
        ledger = _ledger(state)
        key = event.event_id
        if key in ledger["observations"]:
            continue
        actor_id = event.actor_ids[0]
        if actor_id not in state.population:
            continue
        layer = ("night" if task.get("forum") == "night" else "surface") if is_task else event.payload.get("layer", "surface")
        claim = create_campus_claim(
            state, subject_id=actor_id,
            predicate="task_completed" if is_task else "item_" + str(event.payload.get("action_id", "action")).lower(),
            object_id=str(event.payload.get("task_id") if is_task else event.payload.get("item_id")),
            summary=event.public_summary, secrecy=20 if is_task else 40,
            known_by=[value for value in dict.fromkeys([*event.actor_ids, *event.target_ids]) if value in state.population],
            evidence_kind="committed_event",
        )
        claim["source_context"] = {**_context(state, event.scene_id, layer, "event", event.event_id),
                                   "day": event.day, "phase": event.phase}
        ledger["observations"][key] = claim["claim_id"]
        # A task's published completion record can be found later at its region.
        # Private messages, motives and item owners do not become public clues.
        if is_task and (event.visibility == "public" or task.get("forum") == "night"):
            ledger["traces"][key] = {"claim_id": claim["claim_id"], "location_id": event.scene_id,
                                     "layer": layer, "day": event.day, "phase": event.phase}
    ledger = state.knowledge.get("investigation", {})
    traces = ledger.get("traces", {})
    while len(traces) > 128:
        del traces[next(iter(traces))]


def _sources(state, actor_id, deep=False):
    location = state.population[actor_id]["current_location_id"]
    layer = actor_layer(state, actor_id)
    region = _region(state, location)
    ledger = state.knowledge.get("investigation", {})
    beliefs = state.knowledge["beliefs_by_actor"][actor_id]
    observations = ledger.get("observations", {})
    result = []
    if not deep:
        for task_id, task in sorted(state.tasks.items()):
            if (_region(state, task.get("scene_id")) != region
                    or ("night" if task.get("forum") == "night" else "surface") != layer):
                continue
            issuer = task.get("issuer_id")
            if issuer not in state.population:
                continue
            key = f"notice:{task_id}:{task.get('state')}"
            claim_id = observations.get(key)
            if claim_id in beliefs:
                continue
            state_names = {"open": "公开征集中", "viewed": "公开征集中", "considering": "公开征集中",
                           "locked": "已有人承接", "in_progress": "正在处理", "completed": "已完成",
                           "expired": "已过期", "failed": "未能完成"}
            result.append({"source_id": key, "claim_id": claim_id, "kind": "notice",
                           "label": "待整理的校园公告", "subject_id": issuer, "object_id": task_id,
                           "summary": f"公告《{task['title']}》目前{state_names.get(task.get('state'), '已更新')}。",
                           "predicate": "task_notice", "location_id": location, "layer": layer})
    else:
        from simulation.systems.campus_fieldwork import field_sources
        result.extend(field_sources(state, actor_id))
        for key, trace in ledger.get("traces", {}).items():
            if trace["layer"] == layer and _region(state, trace["location_id"]) == region and trace["claim_id"] not in beliefs:
                result.append({"source_id": key, "claim_id": trace["claim_id"], "kind": "archive",
                               "label": f"第 {trace['day']} 天的公开处理记录"})
        ground_key = layer + ":" + location
        ground = state.inventories.get("ground", {}).get(ground_key, {}).get("quantities", {})
        for item_id, quantity in sorted(ground.items()):
            if quantity <= 0:
                continue
            key = f"ground:{ground_key}:{item_id}:{quantity}:{state.clock.day}:{state.clock.phase}"
            claim_id = observations.get(key)
            if claim_id in beliefs:
                continue
            name = state.inventories["catalog"][item_id]["name"]
            result.append({"source_id": key, "claim_id": claim_id, "kind": "inspection",
                           "label": "待检查的现场物品（不等于已知物主）", "subject_id": actor_id,
                           "object_id": item_id, "predicate": "observed_ground_item",
                           "summary": f"在{state.places.get(location, {}).get('name', location)}检查到 {quantity} 件{name}；无法仅据此确定物主或动机。",
                           "location_id": location, "layer": layer})
    return result[:32]


def _learn_source(state, actor_id, source):
    ledger = _ledger(state)
    claim_id = source.get("claim_id")
    if not claim_id:
        claim = create_campus_claim(state, subject_id=source["subject_id"],
            predicate=source["predicate"], object_id=source["object_id"], summary=source["summary"],
            secrecy=10, known_by=[], evidence_kind=source["kind"])
        claim["source_context"] = _context(state, source["location_id"], source["layer"], source["kind"], source["source_id"])
        claim_id = claim["claim_id"]
        ledger["observations"][source["source_id"]] = claim_id
    state.knowledge["beliefs_by_actor"][actor_id][claim_id] = {
        "claim_id": claim_id, "source_actor_id": actor_id, "upstream_source_actor_id": None,
        "source_kind": source["kind"], "confidence": 1.0, "distortion": 0.0,
        "learned_day": state.clock.day, "learned_phase": state.clock.phase,
        "last_confirmed_day": state.clock.day, "last_confirmed_phase": state.clock.phase,
        "transmission_count": 0,
    }
    return claim_id


def _nearby(state, actor_id):
    actor = state.population[actor_id]
    return [other_id for other_id, other in state.population.items()
            if other_id != actor_id and other["current_location_id"] == actor["current_location_id"]
            and actor_layer(state, other_id) == actor_layer(state, actor_id) and not battle_locked(state, other_id)]


def make_investigation_handler(intelligence_policy):
    def handle(context, command):
        state, actor_id, params = context.state, command.actor_id, command.parameters
        def fail(code, message):
            return TransactionOutcome(False, False, code, message)
        if actor_id not in state.population or (command.source == "player" and actor_id != "player"):
            return fail("actor_not_authorized", "不能替其他角色进行调查。")
        if command.issued_day != state.clock.day or command.issued_phase != state.clock.phase:
            return fail("command_clock_mismatch", "调查指令所属时段已过期。")
        if battle_locked(state, actor_id):
            return fail("battle_locked", "请先结束战斗，再调查或整理证据。")
        action = command.action_id
        ledger = _ledger(state)
        beliefs = state.knowledge["beliefs_by_actor"][actor_id]
        payload = {"action_class": "free"}
        if action in {"OBSERVE_SCENE", "SEARCH_SCENE"}:
            sources = _sources(state, actor_id, action == "SEARCH_SCENE")
            if not sources:
                return fail("no_new_evidence", "此处目前没有新的可检查线索，不消耗行动。")
            if action == "SEARCH_SCENE":
                policy = build_action_economy_policy([{ "id": phase, **rule }
                    for phase, rule in state.action_economy["policy"]["phases"].items()])
                cost = consume_major_action(state, policy, command)
                if not cost.success:
                    return fail(cost.code, cost.message)
                payload["action_class"] = "major"
            payload["claim_ids"] = [_learn_source(state, actor_id, source) for source in sources]
            message = f"整理了 {len(sources)} 条有来源的记录；这些记录不直接证明任何人的动机。"
        elif action == "LINK_EVIDENCE":
            claim_ids, summary = params.get("claim_ids"), params.get("summary", "")
            if (not isinstance(claim_ids, list) or not 2 <= len(claim_ids) <= 4
                    or any(not isinstance(value, str) or value not in beliefs for value in claim_ids)
                    or len(set(claim_ids)) != len(claim_ids)):
                return fail("unknown_evidence", "只能关联自己掌握的 2～4 条不同记录。")
            if not isinstance(summary, str) or not 1 <= len(summary.strip()) <= 200:
                return fail("invalid_hypothesis", "请用 1～200 字写出待验证的推测。")
            hypotheses = ledger["hypotheses_by_actor"].setdefault(actor_id, [])
            entry = {"hypothesis_id": f"hypothesis:{actor_id}:{len(hypotheses) + 1}",
                     "claim_ids": list(claim_ids), "summary": summary.strip(), "status": "unverified",
                     "confidence": round(min(beliefs[key]["confidence"] for key in claim_ids) * .8, 3),
                     "day": state.clock.day, "phase": state.clock.phase}
            hypotheses.append(entry)
            payload["hypothesis"] = deepcopy(entry)
            message = "已记录待验证推测；未改写事实，也未向其他人宣告成立。"
        else:
            claim_id = params.get("claim_id")
            if not isinstance(claim_id, str) or claim_id not in beliefs:
                return fail("unknown_evidence", "只能操作自己已经掌握的证据。")
            if action == "RECORD_EVIDENCE":
                if state.inventories["actors"][actor_id]["quantities"].get("blank_notebook", 0) < 1:
                    return fail("notebook_required", "需要携带笔记本，才能固定记录来源与当时的判断。")
                entry = {"claim": deepcopy(state.knowledge["claims"][claim_id]),
                         "belief": deepcopy(beliefs[claim_id]), "day": state.clock.day, "phase": state.clock.phase}
                ledger["notes_by_actor"].setdefault(actor_id, {})[claim_id] = entry
                message = "已写入笔记本；后续转述不会覆盖这份记录。"
            elif action == "SET_EVIDENCE_DISCLOSURE":
                withheld = params.get("withheld")
                if type(withheld) is not bool:
                    return fail("invalid_disclosure", "请选择保密或允许分享。")
                hidden = ledger["withheld_by_actor"].setdefault(actor_id, [])
                if withheld and claim_id not in hidden:
                    hidden.append(claim_id)
                elif not withheld and claim_id in hidden:
                    hidden.remove(claim_id)
                message = "已设为保密；自主信息交流也不会透露此条。" if withheld else "已允许按关系与保密程度分享此条信息。"
            elif action in {"SHARE_EVIDENCE", "ASK_ABOUT_EVIDENCE"}:
                target_id = params.get("target_id")
                if not isinstance(target_id, str) or target_id not in _nearby(state, actor_id):
                    return fail("target_not_present", "请与对方处于同一地点、同一世界层，再当面交流。")
                pair = "|".join(sorted([actor_id, target_id]))
                now = [state.clock.day, state.clock.phase]
                if ledger["last_query_by_pair"].get(pair) == now:
                    return fail("evidence_pair_cooldown", "本时段已经深入交流过证据；普通聊天仍不受次数限制。")
                if action == "SHARE_EVIDENCE":
                    sender, receiver, selected = actor_id, target_id, claim_id
                else:
                    sender, receiver = target_id, actor_id
                    clue = state.knowledge["claims"][claim_id]
                    candidates = [item["claim"]["claim_id"] for item in disclosable_known_claims(state, sender, receiver, intelligence_policy)
                        if item["claim"]["claim_id"] not in beliefs
                        and (item["claim"]["object_id"] == clue["object_id"]
                             or item["claim"]["subject_id"] == clue["subject_id"])]
                    selected = next(iter(candidates), "")
                receipt = share_specific_known_claim(state, sender_id=sender, receiver_id=receiver,
                    claim_id=selected, interaction_id=command.command_id, intent_id="exchange_ideas", policy=intelligence_policy)
                ledger["last_query_by_pair"][pair] = now
                payload["shared"] = bool(receipt)
                payload["receipt"] = receipt
                payload["target_id"] = target_id
                message = ("已收到带有来源的转述，仍须核实。" if action == "ASK_ABOUT_EVIDENCE" else "对方获得了带有来源的转述记录，可信度仍由各自判断。") if receipt else "没有新的可分享信息，或信息被保密；未生成虚假回答。"
            else:
                return fail("unknown_action", "不支持的调查行动。")
            payload["claim_id"] = claim_id
        context.emit("CAMPUS_INVESTIGATION_COMPLETED", message, actor_ids=[actor_id],
            target_ids=[payload["target_id"]] if payload.get("target_id") else [],
            scene_id=state.population[actor_id]["current_location_id"],
            payload={"action_id": action, **deepcopy(payload)}, visibility="private",
            knowledge_tags=["investigation", "information", "evidence"])
        return TransactionOutcome(True, True, "success", message, commit=True, payload=payload)
    return handle


def investigation_view(state, actor_id="player"):
    # Domain/preview tools may intentionally install only population/abilities.
    # An absent subsystem is unavailable, not an empty actionable investigation.
    if (actor_id not in state.knowledge.get("beliefs_by_actor", {})
            or actor_id not in state.inventories.get("actors", {})):
        return {"entries": [], "notes": {}, "hypotheses": [], "nearby": [],
                "scene_sources": [], "can_observe": False, "can_search": False,
                "can_record": False, "battle_locked": False, "rule_note": "调查系统尚未初始化。"}
    ledger = state.knowledge.get("investigation", {})
    entries = []
    for item in known_claims(state, actor_id):
        claim_id = item["claim"]["claim_id"]
        entries.append({**item, "noted": claim_id in ledger.get("notes_by_actor", {}).get(actor_id, {}),
                        "withheld": claim_id in ledger.get("withheld_by_actor", {}).get(actor_id, []),
                        "source_name": state.population.get(item["belief"]["source_actor_id"], {}).get("display_name", "未知来源")})
    sources = _sources(state, actor_id)
    deep_sources = _sources(state, actor_id, True)
    busy = battle_locked(state, actor_id)
    return {"entries": entries, "notes": deepcopy(ledger.get("notes_by_actor", {}).get(actor_id, {})),
            "hypotheses": deepcopy(ledger.get("hypotheses_by_actor", {}).get(actor_id, [])),
            "nearby": [{"actor_id": other, "name": state.population[other].get("display_name", other)} for other in _nearby(state, actor_id)],
            "scene_sources": [{"label": source["label"], "kind": source["kind"]} for source in [*sources, *deep_sources]],
            "can_observe": bool(sources) and not busy, "can_search": bool(deep_sources) and not busy
                and not active_departure(state, actor_id)
                and state.action_economy.get("actors", {}).get(actor_id, {}).get("major_remaining", 0) > 0,
            "can_record": not busy and state.inventories["actors"][actor_id]["quantities"].get("blank_notebook", 0) > 0,
            "battle_locked": busy,
            "rule_note": "公告观察、询问、分享和记笔记免费；深入搜查消耗一次主要行动。事实来源不等于动机证明，推测仍须验证。"}


def investigation_invariant(state):
    ledger = state.knowledge.get("investigation")
    if ledger is None:
        return []
    if not isinstance(ledger, dict) or ledger.get("schema_version") != 1:
        return ["invalid investigation schema"]
    fields = ("traces", "observations", "notes_by_actor", "hypotheses_by_actor", "withheld_by_actor", "last_query_by_pair")
    if any(not isinstance(ledger.get(key), dict) for key in fields):
        return ["invalid investigation containers"]
    claims = state.knowledge.get("claims", {})
    beliefs = state.knowledge.get("beliefs_by_actor", {})
    errors = []
    def valid_stamp(record):
        return (type(record.get("day")) is int and record["day"] > 0
                and isinstance(record.get("phase"), str)
                and record["phase"] in {phase.value for phase in PHASES})
    for value in ledger["observations"].values():
        if not isinstance(value, str) or value not in claims:
            errors.append("investigation observation references unknown claim")
    for trace in ledger["traces"].values():
        if (not isinstance(trace, dict) or not isinstance(trace.get("claim_id"), str) or trace["claim_id"] not in claims
                or not isinstance(trace.get("location_id"), str) or trace["location_id"] not in state.places
                or not isinstance(trace.get("layer"), str) or trace["layer"] not in {"surface", "night"} or not valid_stamp(trace)):
            errors.append("invalid investigation trace")
    for field in ("notes_by_actor", "hypotheses_by_actor", "withheld_by_actor"):
        for actor_id, records in ledger[field].items():
            if actor_id not in beliefs:
                errors.append("investigation unknown actor")
                continue
            if field == "notes_by_actor":
                if not isinstance(records, dict):
                    errors.append("invalid investigation notes")
                    continue
                for claim_id, note in records.items():
                    if (claim_id not in beliefs[actor_id] or not isinstance(note, dict)
                            or not isinstance(note.get("claim"), dict) or note["claim"].get("claim_id") != claim_id
                            or not isinstance(note.get("belief"), dict) or note["belief"].get("claim_id") != claim_id
                            or not valid_stamp(note)):
                        errors.append("invalid investigation note reference")
            elif not isinstance(records, list):
                errors.append("invalid investigation actor records")
            elif field == "withheld_by_actor":
                if any(not isinstance(key, str) or key not in beliefs[actor_id] for key in records):
                    errors.append("invalid investigation disclosure reference")
            else:
                for hypothesis in records:
                    if (not isinstance(hypothesis, dict) or hypothesis.get("status") != "unverified"
                            or not isinstance(hypothesis.get("claim_ids"), list)
                            or not 2 <= len(hypothesis["claim_ids"]) <= 4
                            or not isinstance(hypothesis.get("summary"), str) or not 1 <= len(hypothesis["summary"]) <= 200
                            or not valid_stamp(hypothesis)
                            or any(not isinstance(key, str) or key not in beliefs[actor_id] for key in hypothesis.get("claim_ids", []))):
                        errors.append("invalid investigation hypothesis")
    for pair, stamp in ledger["last_query_by_pair"].items():
        if (not isinstance(pair, str) or len(pair.split("|")) != 2
                or any(actor_id not in state.population for actor_id in pair.split("|"))
                or not isinstance(stamp, list) or len(stamp) != 2
                or not valid_stamp({"day": stamp[0], "phase": stamp[1]})):
            errors.append("invalid investigation exchange stamp")
    return errors
