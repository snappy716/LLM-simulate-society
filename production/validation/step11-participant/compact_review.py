"""Compact a generated game audit without rewriting its outcomes."""
from collections import Counter
import json
from pathlib import Path
import sys

source, destination = map(Path, sys.argv[1:])
result = {"comparison": json.loads((source / "comparison.json").read_text()), "branches": {}}
for mode in result["comparison"]["branches"]:
    raw = json.loads((source / f"{mode}.json").read_text())
    subject = raw["frames"][0]["auditor_only"]["case"]["actor_id"]
    frames = []
    history_length, chronicle_seen = 0, set()
    for frame in raw["frames"]:
        audit = frame["auditor_only"]
        shown = frame["available_player_views_not_proof_of_reading"]
        frames.append({"clock": frame["clock"], "case_status": audit["case"]["status"],
            "case_history_added": audit["case"]["history"][history_length:], "world_counts": frame["world_counts"],
            "subject_local": subject in shown["local_ids"],
            "subject_contact": subject in {c["actor_id"] for c in shown["messaging"]["contacts"]},
            "known_cases": [r["case_id"] for r in shown["social"]["anomalies"]],
            "new_available_chronicle_entries": [{key: entry.get(key) for key in
                ("entry_id", "day", "phase", "display_summary", "visibility")}
                for entry in shown["subject_chronicle"]["items"] if entry["entry_id"] not in chronicle_seen],
            "related_goal_steps": {who: {gid: {key: goal.get(key) for key in ("kind", "step", "status")}
                for gid, goal in data["goals"].items()} for who, data in audit["actors"].items()}})
        history_length = len(audit["case"]["history"])
        chronicle_seen.update(entry["entry_id"] for entry in shown["subject_chronicle"]["items"])
    result["branches"][mode] = {"subject": subject,
        "name": raw["frames"][0]["auditor_only"]["actors"][subject]["person"]["display_name"],
        "commands": dict(Counter(r["command"]["action_id"] for r in raw["commands"])),
        "non_advance_results": [{"command": r["command"], "result": {k: r["result"][k]
            for k in ("success", "code", "message", "world_revision")}}
            for r in raw["commands"] if r["command"]["action_id"] != "ADVANCE_PHASE"],
        "frames": frames}
destination.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
for mode, data in result["branches"].items():
    print(mode, {"commands": data["commands"], "subject_local_frames": sum(f["subject_local"] for f in data["frames"]),
        "subject_contact_frames": sum(f["subject_contact"] for f in data["frames"]),
        "subject_known_frames": sum(result["comparison"]["case_id"] in f["known_cases"] for f in data["frames"]),
        "total_known_cases": len(set(c for f in data["frames"] for c in f["known_cases"]))})
print("CAUSAL_REVIEW_OK")
