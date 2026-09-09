"""Dated personal evidence guides inquiries; never locate an unseen target."""
import hashlib
from simulation.systems.campus_tasks import phase_index

CHECK_POINTS = ("south_gate", "campus_security_office", "library_reading_hall", "canteen_dining_hall")
MAX_LEAD_AGE_PHASES = 8


def _supported_record(state, claim):
    source = claim.get("source_context", {})
    if source.get("layer") != "surface" or source.get("location_id") not in CHECK_POINTS:
        return False
    if claim.get("evidence_kind") == "contact_observation" and claim.get("predicate") == "contact_seen_at":
        from simulation.systems.campus_contact_inquiries import contact_report_valid
        case = state.situations.get("contact_inquiries", {}).get("cases", {}).get(source.get("source_id"), {})
        task = state.tasks.get(case.get("task_id"), {})
        return ((case.get("report") or {}).get("claim_id") == claim["claim_id"]
                and contact_report_valid(state, task.get("assignee_id"), task))
    if claim.get("evidence_kind") == "committed_event" and claim.get("predicate") == "task_completed":
        task = state.tasks.get(claim.get("object_id"), {})
        return (task.get("forum") == "surface" and task.get("state") == "completed"
                and task.get("assignee_id") == claim.get("subject_id") and task.get("scene_id") == source.get("location_id")
                and source.get("source_id") in state.knowledge.get("investigation", {}).get("observations", {})
                and state.knowledge["investigation"]["observations"][source["source_id"]] == claim["claim_id"]
                and any(h.get("kind") == "completed" and (h.get("day"), h.get("phase")) == (source.get("day"), source.get("phase")) for h in task.get("history", ())))
    return False


def known_contact_leads(state, actor_id, target_id):
    now, leads = phase_index(state.clock.day, state.clock.phase), []
    for claim_id, belief in state.knowledge.get("beliefs_by_actor", {}).get(actor_id, {}).items():
        claim = state.knowledge["claims"].get(claim_id, {})
        if (claim.get("subject_id") != target_id or belief.get("confidence", 0) < .5
                or belief.get("distortion", 1) > .35 or not _supported_record(state, claim)):
            continue
        source = claim["source_context"]
        age = now - phase_index(source["day"], source["phase"])
        if not 0 <= age <= MAX_LEAD_AGE_PHASES:
            continue
        leads.append({"claim_id": claim_id, "location_id": source["location_id"], "day": source["day"],
            "phase": source["phase"], "confidence": belief["confidence"], "source_actor_id": belief["source_actor_id"],
            "summary": f"本人掌握的第 {source['day']} 天 {source['phase']} 地点记录指向{state.places[source['location_id']]['name']}；只是过去记录，不保证现在仍在那里。"})
    return sorted(leads, key=lambda row: (-phase_index(row["day"], row["phase"]), -row["confidence"], row["claim_id"]))


def contact_check_options(state, actor_id, target_id):
    leads = known_contact_leads(state, actor_id, target_id)
    gap = state.cognition.get("messaging", {}).get("contact_gaps", {}).get(actor_id + ">" + target_id, {})
    cases = [case for case in state.situations.get("contact_inquiries", {}).get("cases", {}).values()
             if (case["issuer_id"], case["target_id"], case["episode_tick"]) == (actor_id, target_id, gap.get("first_tick"))]
    stop = any(c["status"] in {"open", "observed"} for c in cases)
    visited = {c["location_id"] for c in cases}
    options = []
    for location in CHECK_POINTS:
        place = state.places[location]
        lead = next((row for row in leads if row["location_id"] == location), None)
        options.append({"location_id": location, "name": place["name"], "lead": lead,
            "available": not stop and location not in visited,
            "open_now": state.clock.phase in place["open_phases"],
            "allowed_phases": list(place["open_phases"]),
            "basis": lead["summary"] if lead else "尚无本人掌握的可靠地点线索；这里只是公共会面点，不代表对方位置。"})
    # Stable per-contact fallback distributes uncertainty, without reading the
    # target's current location, home, schedule, captive status or private goals.
    return sorted(options, key=lambda row: (not row["available"], row["lead"] is None,
        -phase_index(row["lead"]["day"], row["lead"]["phase"]) if row["lead"] else 0,
        hashlib.sha256((actor_id + ":" + target_id + ":" + row["location_id"]).encode()).hexdigest()))


def inquiry_basis(state, actor_id, target_id, location):
    option = next(row for row in contact_check_options(state, actor_id, target_id) if row["location_id"] == location)
    lead = option["lead"]
    return {"kind": "known_evidence" if lead else "public_fallback", "summary": option["basis"],
        "selected_day": state.clock.day, "selected_phase": state.clock.phase,
        "source_claim_id": lead["claim_id"] if lead else None,
        "source_day": lead["day"] if lead else None, "source_phase": lead["phase"] if lead else None}


def contact_leads_invariant(state):
    try:
        for case in state.situations.get("contact_inquiries", {}).get("cases", {}).values():
            basis = case.get("decision_basis")
            if basis is None:  # Current-format old saves have no selection receipt.
                continue
            if not isinstance(basis["summary"], str) or not 1 <= len(basis["summary"]) <= 250:
                return ["invalid contact choice summary"]
            selected = phase_index(basis["selected_day"], basis["selected_phase"])
            if basis["selected_day"] != case["created_day"] or selected > phase_index(state.clock.day, state.clock.phase):
                return ["invalid contact choice date"]
            if basis["kind"] == "public_fallback":
                if any(basis[key] is not None for key in ("source_claim_id", "source_day", "source_phase")):
                    return ["fallback contact choice fabricates source"]
            elif basis["kind"] == "known_evidence":
                claim_id = basis["source_claim_id"]
                claim = state.knowledge["claims"][claim_id]
                source = claim["source_context"]
                if (claim_id not in state.knowledge["beliefs_by_actor"][case["issuer_id"]]
                        or claim["subject_id"] != case["target_id"] or source["location_id"] != case["location_id"]
                        or (basis["source_day"], basis["source_phase"]) != (source["day"], source["phase"])
                        or not 0 <= selected - phase_index(source["day"], source["phase"]) <= MAX_LEAD_AGE_PHASES
                        or not _supported_record(state, claim)):
                    return ["invalid source-bound contact choice"]
            else:
                return ["unknown contact choice kind"]
        return []
    except (KeyError, TypeError, AttributeError, ValueError):
        return ["malformed contact choice receipt"]
