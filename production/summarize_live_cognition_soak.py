"""Summarize saved audit evidence without any network access or credentials."""
import argparse
from collections import Counter
import json
from pathlib import Path


def summarize(source):
    load = lambda name: json.loads((source / name).read_text(encoding="utf-8"))
    requests = load("requests.json")
    live, offline = load("live-summary.json"), load("offline-summary.json")
    events, offline_events = load("live-events.json"), load("offline-events.json")
    focus = set(live["focused_ids"])
    plans = {(day["day"], actor, phase): slot for day in load("live-plans.json")
             for actor, slots in day["actors"].items() if actor in focus for phase, slot in slots.items()}
    completions = lambda rows: {(e["day"], e["actor_ids"][0], e["phase"]):
                               (e["payload"]["activity_id"], e["scene_id"])
                               for e in rows if e["event_type"] == "NPC_ACTIVITY_COMPLETED"}
    actual, control = completions(events), completions(offline_events)
    choices = [choice for r in requests for choice in r.get("response", {}).get("daily_choices", {}).values()]
    metric = {"seed": live["seed"], "days": live["days"], "requests": len(requests),
              "request_kinds": dict(Counter(r["kind"] for r in requests)),
              "tokens": {key: sum(r.get("usage", {}).get(key, 0) for r in requests)
                         for key in ("prompt_tokens", "completion_tokens", "total_tokens")},
              "plan_choices": len(choices), "non_first_choices": sum(not c.endswith(":0") for c in choices),
              "planned_focused_slots": len(plans),
              "accepted_llm_slots": sum(s["planned_source"] == "llm" for s in plans.values()),
              "completed_focused_slots": sum(key in actual for key in plans),
              "matching_plan_activity_and_location": sum(actual.get(key) == (s["activity_id"], s["location_id"])
                                                        for key, s in plans.items()),
              "changed_actual_slots_all": sum(actual.get(k) != control.get(k) for k in actual.keys() | control.keys()),
              "changed_actual_slots_focused": sum(actual.get(k) != control.get(k)
                                                   for k in actual.keys() | control.keys() if k[1] in focus),
              "all_compared_completed_slots": len(actual.keys() | control.keys()),
              "usage_by_day": live["usage_by_day"], "live_phases": live["phases"],
              "event_counts": {"live": live["event_counts"], "offline": offline["event_counts"]},
              "player_dialogue_samples": load("player-dialogue-samples.json")}
    social = [e for e in events if e["event_type"] == "NPC_INTERACTION_RESOLVED"]
    metric["interaction_model_decisions"] = sum(e["payload"]["decision_source"] == "llm" for e in social)
    metric["interaction_model_wording"] = sum(e["payload"]["wording_source"] == "llm" for e in social)
    agendas = [s["social_intent"] for s in plans.values() if s.get("social_intent")]
    receipts = [e for e in events if e["event_type"] == "NPC_SOCIAL_PLAN_RESOLVED"]
    metric["social_plans"] = len(agendas)
    metric["social_plan_outcomes"] = dict(Counter(e["payload"]["outcome"] for e in receipts))
    appointments = [e for e in events if e["event_type"] == "NPC_SOCIAL_APPOINTMENT_REPLIED"]
    confirmed = {(e["day"], e["actor_ids"][0]) for e in appointments if e["payload"]["status"] == "confirmed"}
    metric["social_appointment_replies"] = dict(Counter(e["payload"]["status"] for e in appointments))
    metric["confirmed_appointment_outcomes"] = dict(Counter(e["payload"]["outcome"] for e in receipts
        if (e["day"], e["actor_ids"][0]) in confirmed))
    metric["planning_requests_with_previous_social_feedback"] = sum(
        "previous_social_attempt" in r.get("request", {}).get("state", {}) for r in requests if r["kind"] == "plan")
    metric["task_completion_origins"] = {
        name: dict(Counter(e["payload"].get("origin_kind") for e in rows if e["event_type"] == "FORUM_TASK_COMPLETED"))
        for name, rows in (("live", events), ("offline", offline_events))}
    metric["plan_override_reasons"] = dict(Counter((row["decision"] or {}).get("decision_reason", "unspecified")
        for row in load("live-traces.json") if row["actor_id"] in focus
        and actual.get((row["day"], row["actor_id"], row["phase"])) !=
        (plans[row["day"], row["actor_id"], row["phase"]]["activity_id"],
         plans[row["day"], row["actor_id"], row["phase"]]["location_id"])))
    examples = [e for e in social if e["payload"]["wording_source"] == "llm"]
    examples += [e for e in social if e["payload"]["decision_source"] == "llm"][:8]
    examples += receipts[:8]
    examples += appointments[:8]
    examples += [e for e in events if e["event_type"] == "NPC_PERSONAL_GOAL_PROGRESS" and e["actor_ids"][0] in focus]
    examples += [e for e in events if e["event_type"] == "FORUM_TASK_COMPLETED" and e["payload"].get("origin_kind") == "need"][:2]
    return metric, examples


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    metrics, examples = summarize(args.source)
    for name, data in (("metrics", metrics), ("examples", examples)):
        (args.output / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("AUDIT_SUMMARY_OK")
