"""Offline, same-checkpoint causal audit. Does not configure any paid provider.

The explorer sees only local people, contacts and voluntarily disclosed reports.
The separate auditor follows the first naturally occurring anomaly, even if the
explorer never discovers it. This is evidence, not a guarantee of an interesting
story or a complete step-11/LLM acceptance.
"""
import argparse
from collections import Counter
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import subprocess

from simulation.actions.commands import SimulationCommand
from simulation.api.server import CampusKernelBridge
from simulation.persistence.kernel_checkpoint import build_kernel_checkpoint

WALK = ("library_reading_hall", "mirror_lake_square", "student_center", "south_gate")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(",", ":")).encode()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def world_digest(bridge):
    state, rng = bridge.kernel.capture_checkpoint()
    return digest({"world": state.to_dict(), "rng": rng.snapshot()})


def visible_people(view):
    """Same-place residents within the shipped 18-person rendering cap."""
    here = view["player"]["current_location_id"]
    local = [(who, row) for who, row in view["population"].items()
             if row["current_location_id"] == here]
    return [who for who, _ in sorted(local,
        key=lambda item: (not item[1].get("is_phone_contact", False), item[0]))[:18]]


class AuditSession:
    def __init__(self, bridge):
        self.bridge = bridge
        self.commands, self.events, self.notes = [], [], []

    def act(self, action, parameters=None):
        state = self.bridge.kernel._state
        command = SimulationCommand(f"causal:{state.revision}:{len(self.commands)}", "player", action,
            state.revision, parameters=parameters or {}, issued_day=state.clock.day,
            issued_phase=state.clock.phase, issued_minute=state.clock.minute)
        result = self.bridge.kernel.execute(command)
        self.commands.append({"command": command.to_dict(), "result": result.to_dict()})
        self.events.extend(e.to_dict() for e in result.events)
        return result

    def travel(self, destination):
        view = self.bridge.snapshot()
        player = view["player"]
        route = self.bridge.location_graph.shortest_route(player["current_location_id"],
            destination, phase=view["clock"]["phase"], access_tags=player.get("access_tags", ()))
        if route is None:
            self.notes.append({"clock": view["clock"], "destination": destination,
                "reason": "no_legal_route"})
            return False
        for step in route.steps:
            if not self.act("TRAVERSE_LOCATION_PASSAGE", {"passage_id": step.passage_id}).success:
                return False
        return True


def explore(session, index):
    """A modest daytime helper, not an omniscient scripted solution."""
    bridge = session.bridge
    view = bridge.snapshot()
    if view["clock"]["phase"] not in {"morning", "afternoon"}:
        return
    session.travel(WALK[(index // 4 + (view["clock"]["phase"] == "afternoon")) % len(WALK)])
    view = bridge.snapshot()
    # Contacts may be called remotely, but their projected remote positions are
    # deliberately never used to hunt the audited case's person down.
    contacts = [row["actor_id"] for row in view["messaging"]["contacts"]]
    candidates = list(dict.fromkeys(visible_people(view) + contacts))
    if candidates:
        offset = (index * 3) % len(candidates)
        candidates = candidates[offset:] + candidates[:offset]
    for who in candidates[:3]:
        session.act("ASK_ANOMALY_EXPERIENCE", {"npc_id": who})
    view = bridge.snapshot()
    local = set(visible_people(view))
    for row in view["social"]["anomalies"]:
        if row["npc_id"] in local:
            session.act("ASK_ANOMALY_EXPERIENCE", {"npc_id": row["npc_id"], "case_id": row["case_id"]})
            current = next(r for r in bridge.snapshot()["social"]["anomalies"] if r["case_id"] == row["case_id"])
            if current["can_support"]:
                session.act("SUPPORT_ANOMALY", {"npc_id": row["npc_id"], "case_id": row["case_id"],
                    "expected_case_revision": current["report"]["revision"]})
                return
    # A disclosed topic motivates real study; no report means no hidden-topic
    # hint. Going to the library is allowed even if today's action is exhausted.
    known = {r["topic_id"] for r in view["social"]["anomalies"]}
    topic = next((t["topic_id"] for t in view["growth"]["topics"]
        if t["topic_id"] in known and t["components"]["theory"] < 40), None)
    if topic and session.travel("library_reading_hall"):
        session.act("READ_KNOWLEDGE", {"topic_id": topic})


def natural_start(seed, max_days=7):
    bridge = CampusKernelBridge(seed)
    bridge.cognition_runtime.configure_rule()
    session = AuditSession(bridge)
    for _ in range(max_days * 4):
        result = session.act("ADVANCE_PHASE")
        if not result.success:
            raise RuntimeError(result.code)
        cases = bridge.kernel._state.situations.get("campus_anomalies", {}).get("cases", {})
        if cases:
            cid = next(iter(cases))
            return bridge.kernel.capture_checkpoint(), cid, session.commands
    raise RuntimeError("No natural anomaly in bootstrap; do not fabricate one")


def sample(bridge, cid):
    before = world_digest(bridge)
    state = bridge.kernel._state
    case = state.situations["campus_anomalies"]["cases"][cid]
    subject = case["actor_id"]
    view = bridge.snapshot()
    related = {subject} | {r["helper_id"] for r in case["history"] if r["route"] == "day_support"}
    actors = {who: {"person": deepcopy(state.population[who]),
        "goals": deepcopy(state.cognition.get("long_term_plans", {}).get("actors", {}).get(who, {})),
        "daily_plan": deepcopy(state.cognition.get("daily_plans", {}).get("actors", {}).get(who, {})),
        "inventory": deepcopy(state.inventories.get("actors", {}).get(who, {})),
        "relationships": {other: deepcopy(state.relationships[who].get(other, {})) for other in related if other != who}}
        for who in sorted(related)}
    result = {"clock": deepcopy(view["clock"]), "revision": state.revision,
        "auditor_only": {"case": deepcopy(case), "actors": actors,
            "origin_site": deepcopy(state.situations.get("night_sites", {}).get("sites", {}).get(cid, {})),
            "linked_tasks": {key: deepcopy(t) for key, t in state.tasks.items() if t.get("anomaly_case_id") == cid}},
        "available_player_views_not_proof_of_reading": {
            "local_ids": visible_people(view), "social": deepcopy(view["social"]),
            "messaging": deepcopy(view["messaging"]), "tasks": deepcopy(view["tasks"]),
            "player": deepcopy(view["player"]), "growth": deepcopy(view["growth"]),
            "subject_chronicle": bridge.chronicle(subject, limit=50)},
        "world_counts": {"completed_tasks": sum(t["state"] == "completed" for t in state.tasks.values()),
            "anomalies": dict(Counter(c["status"] for c in state.situations["campus_anomalies"]["cases"].values()))},
        "calls_today": state.cognition["usage"]["calls"]}
    if world_digest(bridge) != before:
        raise RuntimeError("Audit sampling mutated world or random streams")
    return result


def run_branch(checkpoint, cid, days, mode, output=None):
    if mode not in {"unattended", "explorer"} or not 1 <= days <= 7:
        raise ValueError("Expected unattended/explorer and 1..7 days")
    initial, rng = checkpoint
    bridge = CampusKernelBridge(initial.master_seed)
    bridge.cognition_runtime.configure_rule()
    bridge.kernel.restore_checkpoint(initial, rng, expected_revision=bridge.kernel.state.revision)
    restored_digest = world_digest(bridge)
    session = AuditSession(bridge)
    frames = [sample(bridge, cid)]
    for index in range(days * 4):
        if mode == "explorer":
            explore(session, index)
        result = session.act("ADVANCE_PHASE")
        if not result.success:
            raise RuntimeError(f"Phase {index}: {result.code}")
        frames.append(sample(bridge, cid))
        if frames[-1]["calls_today"]:
            raise RuntimeError("Offline audit unexpectedly used a model")
        if output:
            write(output / f"{mode}-progress.json", {"completed_phases": index + 1, "clock": frames[-1]["clock"]})
        print(mode, index + 1, frames[-1]["clock"], flush=True)
    final = frames[-1]["auditor_only"]["case"]
    result = {"mode": mode, "days": days, "start_digest": restored_digest,
        "source_digest": digest(build_kernel_checkpoint(initial, rng)), "case_id": cid,
        "player_policy": "none" if mode == "unattended" else "daytime_local_and_contacts_no_hidden_target",
        "frames": frames, "commands": session.commands, "events": session.events, "notes": session.notes,
        "summary": {"status": final["status"], "history": final["history"],
            "heard_by_player": "player" in final["reports"],
            "player_supports": sum(r.get("helper_id") == "player" for r in final["history"]),
            "command_failures": dict(Counter(c["result"]["code"] for c in session.commands if not c["result"]["success"])),
            "events": dict(Counter(e["event_type"] for e in session.events)), "api_calls": 0}}
    if output:
        write(output / f"{mode}.json", result)
    return result


def compare(left, right):
    if (left["mode"], right["mode"]) != ("unattended", "explorer"):
        raise ValueError("Expected distinct unattended and explorer branches")
    if left["start_digest"] != right["start_digest"] or left["source_digest"] != right["source_digest"] or left["case_id"] != right["case_id"]:
        raise ValueError("Branches did not begin at the same event/checkpoint")
    if left["days"] != right["days"] or any(len(r["frames"]) != r["days"] * 4 + 1 for r in (left, right)):
        raise ValueError("Incomplete or unequal observation periods")
    phases = ("morning", "afternoon", "evening", "late_night")
    for branch in (left, right):
        ticks = [(f["clock"]["day"] - 1) * 4 + phases.index(f["clock"]["phase"]) for f in branch["frames"]]
        advances = [r for r in branch["commands"] if r["command"]["action_id"] == "ADVANCE_PHASE"]
        if (ticks != list(range(ticks[0], ticks[0] + branch["days"] * 4 + 1))
                or len(advances) != branch["days"] * 4 or not all(r["result"]["success"] for r in advances)
                or any(f["calls_today"] for f in branch["frames"])):
            raise ValueError("Incomplete formal phase progression or unexpected API use")
        if branch["mode"] == "unattended" and len(advances) != len(branch["commands"]):
            raise ValueError("Unattended branch contains player intervention")
    return {"same_checkpoint_verified": True, "case_id": left["case_id"], "days": left["days"],
        "branches": {r["mode"]: r["summary"] for r in (left, right)},
        "scope": "Offline day-helper comparison; night-player and real LLM branches still required"}


def code_manifest():
    root = Path(__file__).resolve().parents[1]
    paths = [Path(__file__).resolve()]
    for folder, extension in (("simulation", "*.py"), ("content", "*.json"),
                              ("contracts", "*.json"), ("game/scripts", "*.gd")):
        paths.extend((root / folder).rglob(extension))
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(paths)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--days", type=int, default=7, choices=range(1, 8))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    checkpoint, cid, bootstrap = natural_start(args.seed)
    write(args.output / "initial-checkpoint.json", build_kernel_checkpoint(*checkpoint))
    write(args.output / "bootstrap-commands.json", bootstrap)
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    write(args.output / "configuration.json", {"seed": args.seed, "days": args.days, "code_commit": revision,
        "source_files": code_manifest(),
        "content_version": checkpoint[0].content_version, "start_clock": asdict(checkpoint[0].clock),
        "bootstrap_only_advance_commands": True, "injected_conditions": [], "api": "disabled"})
    left = run_branch(checkpoint, cid, args.days, "unattended", args.output)
    right = run_branch(checkpoint, cid, args.days, "explorer", args.output)
    write(args.output / "comparison.json", compare(left, right))
    print("CAUSAL_COMPARISON_OK", flush=True)


if __name__ == "__main__":
    main()
