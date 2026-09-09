"""Opt-in audit player. Public views and formal commands only; never game AI."""
from simulation.systems.campus_autonomous_combat import choose_combat_action
from simulation.systems.campus_combat import load_combat_round_policy


def refresh_case(session, row):
    session.act("ASK_ANOMALY_EXPERIENCE", {"npc_id": row["npc_id"], "case_id": row["case_id"]})
    return next(r for r in session.bridge.snapshot()["social"]["anomalies"] if r["case_id"] == row["case_id"])


def support_here(session):
    from production.run_causal_comparison import visible_people
    view = session.bridge.snapshot()
    local = set(visible_people(view))
    for row in view["social"]["anomalies"]:
        if row["npc_id"] not in local:
            continue
        row = refresh_case(session, row)
        if not row["can_support"]:
            continue
        if row["anchor_options"] and not row["confirmed_anchor"]:
            session.act("CONFIRM_RELATIONSHIP_ANCHOR", {"npc_id": row["npc_id"], "case_id": row["case_id"],
                "expected_case_revision": row["report"]["revision"], "source_id": row["anchor_options"][0]["source_id"]})
            row = refresh_case(session, row)
        params = {"npc_id": row["npc_id"], "case_id": row["case_id"], "expected_case_revision": row["report"]["revision"]}
        if row["can_use_anchor"]:
            params["anchor_id"] = row["confirmed_anchor"]["anchor_id"]
        if session.act("SUPPORT_ANOMALY", params).success:
            return True
    return False


def observe_here(session, asked):
    from production.run_causal_comparison import visible_people
    view = session.bridge.snapshot()
    # Inspect everyone actually present before walking away. No remote cast
    # lookup; no fixed three-person sampling limit carried into this policy.
    local = visible_people(view)
    for who in local:
        if who not in asked:
            asked.add(who)
            heard = session.act("ASK_ANOMALY_EXPERIENCE", {"npc_id": who})
            if heard.success and not view["population"][who].get("is_phone_contact", False):
                session.act("ADD_PHONE_CONTACT", {"target_id": who})


def daytime(session, index):
    from production.run_causal_comparison import WALK
    view = session.bridge.snapshot()
    clock = view["clock"]
    # Only the explicit test player makes this acceptance decision. Production
    # never automatically accepts a player's invitation.
    for meeting in view["social"]["anomaly_meetings"]:
        if meeting["status"] == "pending" and meeting["proposer_id"] != "player":
            session.act("ACCEPT_ANOMALY_MEETING", {"meeting_id": meeting["meeting_id"], "expected_revision": meeting["revision"]})
    view = session.bridge.snapshot()
    due = next((m for m in view["social"]["anomaly_meetings"] if m["status"] == "confirmed"
        and (m["day"], m["phase"]) == (clock["day"], clock["phase"])), None)
    if due:
        session.travel(due["location_id"])
        support_here(session)
        return  # Do not spend an appointment's reserved action on random study.
    asked = set()
    observe_here(session, asked)
    if support_here(session):
        return
    # Existing friends can tell us about an experience remotely; only disclosed
    # appointments may supply a remote meeting location.
    for contact in session.bridge.snapshot()["messaging"]["contacts"]:
        who = contact["actor_id"]
        if who not in asked:
            asked.add(who)
            session.act("ASK_ANOMALY_EXPERIENCE", {"npc_id": who})
    view = session.bridge.snapshot()
    known = {r["topic_id"] for r in view["social"]["anomalies"]}
    topic = next((t["topic_id"] for t in view["growth"]["topics"]
        if t["topic_id"] in known and t["components"]["theory"] < 40), None)
    if topic:
        if session.travel("library_reading_hall"):
            observe_here(session, asked)
            if not support_here(session):
                session.act("READ_KNOWLEDGE", {"topic_id": topic})
    else:
        session.travel(WALK[(index // 4 + (clock["phase"] == "afternoon")) % len(WALK)])
        observe_here(session, asked)
        support_here(session)
    view = session.bridge.snapshot()
    contacts = {c["actor_id"] for c in view["messaging"]["contacts"]}
    mastery = {t["topic_id"]: t["mastery"] for t in view["growth"]["topics"]}
    for row in view["social"]["anomalies"]:
        if row["npc_id"] in contacts and mastery.get(row["topic_id"], 0) >= 20 and row["meeting_options"]:
            session.act("PROPOSE_ANOMALY_MEETING", {"case_id": row["case_id"], **row["meeting_options"][0]})


def fight(session, task_id):
    started = session.act("START_BATTLE_PREPARATION", {"task_id": task_id})
    if not started.success:
        return
    battle = session.bridge.snapshot()["combat"]["active_battle"]
    bid = battle["battle_id"]
    def issue(action, parameters=None):
        current = session.bridge.snapshot()["combat"]["active_battle"]
        return session.act(action, {"battle_id": bid, "expected_battle_revision": current["revision"], **(parameters or {})})
    own = next(c for c in battle["character_cards"].values() if c["actor_id"] == "player")
    deployed = issue("DEPLOY_COMBAT_CHARACTER", {"character_card_instance_id": own["character_card_instance_id"], "destination_row": own["preferred_row"]})
    if not deployed.success or not issue("CONFIRM_BATTLE_DEPLOYMENT").success:
        issue("CANCEL_BATTLE_PREPARATION")
        return
    if not issue("START_CARD_COMBAT").success:
        issue("CANCEL_BATTLE_PREPARATION")
        return
    policy = load_combat_round_policy(session.bridge.registry)  # Public game rules.
    for _ in range(180):
        view = session.bridge.snapshot()["combat"]["active_battle"]
        if not view or view["phase"] == "resolved":
            return
        # This shipped chooser does not read its state argument; passing None
        # makes accidental future dependence on hidden world state fail loudly.
        action, params = choose_combat_action(None, view, "player", policy)
        if not issue(action, params).success:
            raise RuntimeError("Audit battle chooser selected an invalid public option")
    issue("RETREAT_CARD_COMBAT")  # Real pursuit/possible defeat, not a fake win.


def nighttime(session):
    view = session.bridge.snapshot()
    day = view["clock"]["day"]
    if view["night_world"]["current_layer"] != "night":
        if not view["night_world"]["can_enter"] or not session.act("ENTER_NIGHT_WORLD").success:
            return
    view = session.bridge.snapshot()
    tasks = [t for t in view["tasks"].values() if t["forum"] == "night"
        and t["state"] in {"open", "viewed", "considering"} and t.get("night_site")]
    # Prefer the publicly advertised residual-shell problem, not its hidden
    # person/case ID. NPC locks remain authoritative and may beat us to it.
    tasks.sort(key=lambda t: ("afterimage" not in t.get("tags", []), t["task_id"]))
    if tasks:
        task = tasks[0]
        session.act("VIEW_FORUM_TASK", {"task_id": task["task_id"]})
        current = session.bridge.snapshot()["tasks"][task["task_id"]]
        if session.act("CLAIM_FORUM_TASK", {"task_id": task["task_id"], "expected_task_revision": current["lock_revision"]}).success:
            if session.travel(task["scene_id"]):
                fight(session, task["task_id"])
                current = session.bridge.snapshot()["tasks"][task["task_id"]]
                if current.get("night_site", {}).get("can_follow_through"):
                    session.act("RESOLVE_NIGHT_SITE", {"task_id": task["task_id"], "expected_task_revision": current["lock_revision"]})
    view = session.bridge.snapshot()
    # Defeat may already have advanced to tomorrow and recovered in the dorm.
    if view["clock"]["day"] == day and view["night_world"]["can_exit"]:
        session.act("EXIT_NIGHT_WORLD")


def participate(session, index):
    phase = session.bridge.snapshot()["clock"]["phase"]
    if phase in {"morning", "afternoon"}:
        daytime(session, index)
    elif phase == "evening":
        nighttime(session)
    elif phase == "late_night":
        view = session.bridge.snapshot()
        if view["night_world"]["current_layer"] == "surface":
            session.travel(view["player"]["home_location_id"])
            player = session.bridge.snapshot()["player"]
            if player["can_rest_recover"] and any(player["vitals"][key] < player["vitals"]["max_" + key] for key in ("health", "focus")):
                session.act("REST")  # Actual home/action cost, never reset vitals.
