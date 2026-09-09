"""A personally confirmed shared experience can ground one matching afterimage.

Evidence stays private. This is a tactical interruption, not remote treatment.
"""
from simulation.systems.campus_growth import mastery_by_topic
from simulation.systems.campus_relationship_anchors import anchors_valid


def owned_basis(state, battle, actor):
    case = state.situations.get("campus_anomalies", {}).get("cases", {}).get(battle.get("anomaly_origin", {}).get("case_id"))
    if not case or not anchors_valid(state, case):
        return None
    anchor = case.get("anchors", {}).get(actor)
    if not anchor or mastery_by_topic(state, actor).get(case["topic_id"], 0) < 40:
        return None
    # Reuse current willingness, not an old confirmation as permanent consent.
    from simulation.systems.campus_anomalies import _consents
    if not _consents(state, case["actor_id"], actor, 65):
        return None
    beliefs = state.knowledge.get("beliefs_by_actor", {}).get(actor, {})
    for key in ("claim_id", "report_claim_id"):
        belief = beliefs.get(anchor[key], {})
        if belief.get("confidence", 0) < .5 or belief.get("distortion", 1) > .35:
            return None
    return case, anchor


def options(state, battle, viewer_id):
    cards = battle.get("character_cards", {}).values()
    viewer = next((c for c in cards if c["actor_id"] == viewer_id), {})
    result = []
    for card in cards:
        actor = card["actor_id"]
        if card.get("deployment_state") != "deployed" or card.get("team_id") != viewer.get("team_id"):
            continue
        basis = owned_basis(state, battle, actor)
        if not basis:
            continue
        case, _ = basis
        for target, enemy in battle.get("enemy_units", {}).items():
            if enemy["archetype_id"] != case["topic_id"] or battle["enemy_health"].get(target, 0) <= 0:
                continue
            used = any(row["target_id"] == target for row in battle.get("evidence_insight_receipts", []))
            result.append({"source_actor_id": actor, "source_name": card["display_name"], "target_id": target,
                "target_name": enemy["display_name"], "tactic": "ground", "name": "现实参照",
                "mastery": mastery_by_topic(state, actor)[case["topic_id"]], "command_cost": 1, "used": used,
                "playable": battle.get("phase") == "player_turn" and not used and battle["health"].get(actor, 0) > 0
                    and battle["command_points"].get(card["team_id"], 0) >= 1 and "knowledge_interrupted" not in enemy["statuses"]})
    return result


def record_use(state, battle, actor, target):
    case, anchor = owned_basis(state, battle, actor)
    battle.setdefault("evidence_insight_receipts", []).append({"source_actor_id": actor, "target_id": target,
        "case_id": case["case_id"], "anchor_id": anchor["anchor_id"], "claim_id": anchor["claim_id"],
        "report_claim_id": anchor["report_claim_id"], "mastery": mastery_by_topic(state, actor)[case["topic_id"]],
        "round": battle["round"], "day": state.clock.day, "phase": state.clock.phase, "command_cost": 1})


def receipts_valid(state, battle):
    try:
        rows = battle.get("evidence_insight_receipts", [])
        used = [key for key in battle.get("knowledge_insight_used", []) if key.endswith(":ground")]
        if not isinstance(rows, list) or len(rows) != len(used) or len({r["target_id"] for r in rows}) != len(rows):
            return False
        for row in rows:
            case = state.situations["campus_anomalies"]["cases"][row["case_id"]]
            actor, target = row["source_actor_id"], row["target_id"]
            anchor = case["anchors"][actor]
            if (not anchors_valid(state, case) or battle.get("anomaly_origin", {}).get("case_id") != case["case_id"]
                    or actor not in battle["participant_ids"] or target not in battle["enemy_units"]
                    or battle["enemy_units"][target]["archetype_id"] != case["topic_id"]
                    or f"{actor}:{target}:ground" not in used
                    or any(row[key] != anchor[key] for key in ("anchor_id", "claim_id", "report_claim_id"))
                    or type(row["mastery"]) is not int or not 40 <= row["mastery"] <= 100
                    or type(row["round"]) is not int or not 1 <= row["round"] <= battle["round"]
                    or type(row["day"]) is not int or not anchor["day"] <= row["day"] <= state.clock.day
                    or row["phase"] not in {"evening", "late_night"} or type(row["command_cost"]) is not int or row["command_cost"] != 1):
                return False
        return True
    except (KeyError, TypeError, ValueError, AttributeError):
        return False
