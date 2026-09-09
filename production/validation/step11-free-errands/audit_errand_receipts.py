"""Read-only semantic audit of recorded branch outcomes, never calls a provider."""
import json
from collections import Counter
from pathlib import Path
import sys


def audit(branch):
    slots = {}
    observed = []
    for frame in branch["frames"]:
        for actor, plans in frame["cognition_audit"]["daily_plans"].items():
            for phase, plan in plans.items():
                slots[plan["day"], phase, actor] = plan
        if frame is not branch["frames"][0]:
            for actor, actual in frame["cognition_audit"]["actual_activities"].items():
                plan = slots.get((frame["clock"]["day"], frame["clock"]["phase"], actor), {})
                if plan.get("planned_source") == "llm":
                    observed.append((frame["clock"], actor, plan, actual))
    counts = Counter()
    examples = []
    violations = []
    for row in branch["commands"]:
        events = row["result"].get("events", [])
        for i, event in enumerate(events):
            if event["event_type"] not in {"NPC_FREE_ERRAND_COMPLETED", "NPC_FREE_ERRAND_BLOCKED"}:
                continue
            actor = event["actor_ids"][0]
            key = event["day"], event["phase"], actor
            plan = slots.get(key, {})
            source = "llm" if plan.get("planned_source") == "llm" else "rule"
            success = event["event_type"] == "NPC_FREE_ERRAND_COMPLETED"
            counts[f"{source}_errand_{'completed' if success else 'blocked'}"] += 1
            followup = next((e for e in events[i+1:] if actor in e["actor_ids"]
                and (e["day"], e["phase"]) == key[:2]
                and e["event_type"] in {"NPC_ACTIVITY_COMPLETED", "NPC_ACTIVITY_BLOCKED"}), None)
            if followup is None:
                violations.append([key, "missing_primary_result"])
            else:
                counts[f"{source}_errand_then_{followup['event_type'].lower()}"] += 1
                if source == "llm" and followup["event_type"] == "NPC_ACTIVITY_COMPLETED" and (
                        followup["payload"].get("activity_id"), followup["payload"].get("location_id")) == (
                        plan.get("activity_id"), plan.get("location_id")):
                    counts["llm_errand_then_original_primary_completed"] += 1
            if source == "llm":
                params = event["payload"]["parameters"]
                authorized = [e for e in plan.get("free_errands", [])
                    if e["parameters"]["shop_id"] == params.get("shop_id")
                    and e["parameters"]["item_id"] == params.get("item_id")
                    and params.get("quantity", 0) <= e["parameters"]["quantity"]]
                if not authorized:
                    violations.append([key, "unauthorized_errand"])
                if success and len(examples) < 4:
                    examples.append({"clock_actor": key, "purchase": params,
                        "chosen_primary": plan["activity_id"], "chosen_location": plan["location_id"],
                        "actual_followup": followup["payload"] if followup else None})
    for clock, actor, plan, actual in observed:
        counts["observed_llm_slots"] += 1
        counts["selected_errands_in_observed_slots"] += len(plan.get("free_errands", []))
        current = (actual.get("day"), actual.get("phase")) == (clock["day"], clock["phase"])
        if current and actual.get("activity_id") == "BUY_ITEM" and plan["activity_id"] != "BUY_ITEM":
            violations.append([clock, actor, "purchase_replaced_primary"])
        if current and actual.get("status") == "completed":
            counts["observed_completed_current_activity"] += 1
            if (actual.get("activity_id"), actual.get("location_id")) == (plan["activity_id"], plan["location_id"]):
                counts["observed_matching_primary"] += 1
    plans = [r for r in branch.get("requests", []) if r.get("kind") == "plan"]
    for request in plans:
        response = request.get("response", {})
        counts["daily_requests"] += 1
        if any((request["request"].get("free_options") or {}).values()):
            counts["requests_with_available_errands"] += 1
            if not any((response.get("free_choices") or {}).values()):
                counts["requests_with_options_but_no_purchase_chosen"] += 1
        if any((response.get("free_choices") or {}).values()):
            counts["requests_choosing_errands"] += 1
    return {"counts": dict(counts), "violations": violations, "examples": examples,
        "limits": "Only observed slots; optional receipts count errands, not distinct NPC phases. Legal primary overrides are not all failures."}


root = Path(sys.argv[1])
results = {}
for label, mode in (("rule-unattended", "unattended"), ("llm-unattended", "unattended"), ("llm-participant", "participant")):
    path = root / label / f"{mode}.json"
    if path.exists():
        results[label] = audit(json.loads(path.read_text()))
print(json.dumps(results, ensure_ascii=False, indent=2))
assert len(results) == 3, "All three completed branches are required for acceptance"
assert all(not r["violations"] for r in results.values()), "Errand authorization or continuation violation"
