"""Deterministic asynchronous forum attention; no game-clock or API charge."""
from dataclasses import replace
from simulation.systems.campus_tasks import AVAILABLE_STATES, _actor_has_active_task, _candidate_score
from simulation.systems.campus_night_tasks import _task_score
from simulation.systems.campus_departures import has_upcoming_departure
from simulation.systems.campus_enemy_turns import recovering_from_defeat
from simulation.systems.campus_schedules import current_schedule_slot
from simulation.systems.campus_parties import party_for_actor
from simulation.systems.campus_vitals import actor_layer, battle_locked
from simulation.systems.transactions import TransactionOutcome


def _ledger(state):
    ledger = state.cognition.setdefault("forum_attention", {"schema_version": 1, "sequence": 0, "phase": [], "tick": 0, "actors": {}})
    marker = [state.clock.day, state.clock.phase]
    if ledger["phase"] != marker:
        for task in state.tasks.values():
            if task.get("forum") not in {"surface", "night"}:
                continue
            task["considering_ids"] = []
            if task.get("state") == "considering":
                task["state"] = "viewed" if task.get("viewer_ids") else "open"
        ledger.update(phase=marker, tick=0, actors={})
    return ledger


def _eligible(state, actor_id):
    from simulation.systems.campus_night_sites import captive_site
    if captive_site(state, actor_id):
        return False
    if (actor_id == "player" or _actor_has_active_task(state, actor_id) or has_upcoming_departure(state, actor_id)
            or recovering_from_defeat(state, actor_id) or battle_locked(state, actor_id)
            or current_schedule_slot(state, actor_id).get("priority", 0) >= 90):
        return False
    party = party_for_actor(state, actor_id)
    if party and (len(party["member_ids"]) > 1 or party["leader_id"] != actor_id):
        return False
    if actor_layer(state, actor_id) == "night":
        # The current activity executor performs a newly accepted job next phase.
        # Do not promise a same-night job after its last executable phase.
        return (state.clock.phase == "evening" and actor_id in state.situations["night_world"].get("active_actor_ids", []))
    return True


def _release(state, actor_id, record):
    task = state.tasks.get(record.get("task_id"), {})
    if actor_id in task.get("considering_ids", []):
        task["considering_ids"].remove(actor_id)
    if task.get("state") == "considering" and not task["considering_ids"]:
        task["state"] = "viewed" if task.get("viewer_ids") else "open"
    record.update(stage=0, task_id="", task_revision=0)


def advance_forum_attention(context, graph, task_handler):
    state = context.state
    ledger = _ledger(state)
    ledger["sequence"] += 1
    ledger["tick"] += 1
    tick = ledger["tick"]
    rng = context.rng.stream("campus_forum_attention")
    summary = {"attention_view_count": 0, "attention_consider_count": 0, "attention_claim_count": 0,
               "night_task_view_count": 0, "night_npc_claim_count": 0,
               "forum_new_view_count": 0, "forum_consider_count": 0, "forum_npc_claim_count": 0}
    groups = {"surface": [], "night": []}
    for actor_id, actor in sorted(state.population.items()):
        if not _eligible(state, actor_id):
            if actor_id in ledger["actors"]:
                _release(state, actor_id, ledger["actors"][actor_id])
            continue
        record = ledger["actors"].get(actor_id)
        if record is None:
            record = {"stage": 0, "due": rng.randint(1, 3), "order": rng.random(), "task_id": "", "task_revision": 0}
            ledger["actors"][actor_id] = record
        if record["due"] <= tick:
            groups[actor_layer(state, actor_id)].append((-record["stage"], record["due"], record["order"], actor_id))
    for layer, candidates in groups.items():
        for _, _, _, actor_id in sorted(candidates)[:6]:
            record = ledger["actors"][actor_id]
            actor = state.population[actor_id]
            tasks = [task for task in state.tasks.values() if task.get("forum") == layer
                     and task.get("state") in AVAILABLE_STATES and task.get("issuer_id") != actor_id
                     and task.get("expires_day", state.clock.day) >= state.clock.day]
            def issue(action, task):
                return task_handler(context, replace(context.command,
                    command_id=f"{context.command.command_id}:attention:{ledger['sequence']}:{actor_id}:{action}",
                    actor_id=actor_id, action_id=action, source="rule", issued_day=state.clock.day, issued_phase=state.clock.phase,
                    parameters={"task_id": task["task_id"],
                    "expected_task_revision": record["task_revision"]}))
            if record["stage"] == 0:
                unseen = [task for task in tasks if actor_id not in task["viewer_ids"]]
                for task in rng.sample(unseen, min(3, len(unseen))):
                    outcome = issue("VIEW_FORUM_TASK", task)
                    if not outcome.success:
                        raise RuntimeError("legal NPC forum view refused: " + outcome.code)
                    summary["attention_view_count"] += 1
                    summary["night_task_view_count" if layer == "night" else "forum_new_view_count"] += 1
                record["stage"] = 1
            elif record["stage"] == 1:
                ranked = []
                for task in tasks:
                    if actor_id not in task["viewer_ids"]:
                        continue
                    route = graph.shortest_route(actor["current_location_id"], task["scene_id"],
                        phase=state.clock.phase, access_tags=actor.get("access_tags", ()))
                    if route is None:
                        continue
                    score = _task_score(state, graph, actor_id, task) if layer == "night" else _candidate_score(state, graph, task, actor_id)
                    if score is not None:
                        ranked.append((-score, task["task_id"], task))
                if ranked:
                    task = min(ranked, key=lambda row: row[:2])[2]
                    if actor_id not in task["considering_ids"]:
                        task["considering_ids"].append(actor_id)
                    task["state"] = "considering"
                    record.update(stage=2, task_id=task["task_id"], task_revision=task["lock_revision"])
                    summary["attention_consider_count"] += 1
                    if layer == "surface":
                        summary["forum_consider_count"] += 1
                else:
                    record["stage"] = 0
            else:
                task = state.tasks.get(record["task_id"])
                if task:
                    outcome = issue("CLAIM_FORUM_TASK", task)
                    if outcome.success:
                        summary["attention_claim_count"] += 1
                        summary["night_npc_claim_count" if layer == "night" else "forum_npc_claim_count"] += 1
                    elif outcome.code not in {"task_revision_conflict", "task_unavailable", "actor_has_active_task", "npc_commitment_conflict", "night_layer_required"}:
                        raise RuntimeError("unexpected NPC claim refusal: " + outcome.code)
                _release(state, actor_id, record)
            # Attention cadence depends on rest and interest, not actor ID order.
            pressure = int(actor.get("needs", {}).get("rest", 0)) // 45
            interest = int(actor.get("personality", {}).get("conscientiousness", 50)) // 80
            record["due"] = tick + max(1, rng.randint(1, 3) + pressure - interest)
    return summary


def make_attention_handler(advance):
    def handle(context, command):
        if command.actor_id != "player" or command.parameters:
            return TransactionOutcome(False, False, "invalid_attention_request", "校园动态不接受指定 NPC 或任务。")
        if command.issued_day != context.state.clock.day or command.issued_phase != context.state.clock.phase:
            return TransactionOutcome(False, False, "command_clock_mismatch", "校园动态请求已过期。")
        return TransactionOutcome(True, True, "success", "校园动态已更新；游戏时段与行动次数不变。", commit=True, payload=advance(context))
    return handle


def attention_invariant(state):
    ledger = state.cognition.get("forum_attention")
    if ledger is None:
        return []
    try:
        if (ledger["schema_version"] != 1 or type(ledger["sequence"]) is not int or ledger["sequence"] < 0
                or type(ledger["tick"]) is not int or not 0 <= ledger["tick"] <= ledger["sequence"]
                or ledger["phase"] != [state.clock.day, state.clock.phase]):
            return ["invalid forum attention clock"]
        for actor_id, record in ledger["actors"].items():
            if (actor_id == "player" or actor_id not in state.population or record["stage"] not in {0, 1, 2}
                    or type(record["due"]) is not int or record["due"] < 1
                    or not isinstance(record["order"], (int, float)) or not 0 <= record["order"] < 1
                    or type(record["task_revision"]) is not int or record["task_revision"] < 0
                    or (record["stage"] == 2 and record["task_id"] not in state.tasks)):
                return ["invalid NPC forum attention record"]
    except (KeyError, TypeError, AttributeError):
        return ["invalid nested forum attention state"]
    return []
