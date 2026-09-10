"""Optional clinic care, backed by actual staff shifts and pharmacy resources.

Health is a game resource, not a diagnosis. Rest still restores health/focus in
full. Clinic care preserves the patient's major action, at a real material and
cash cost, with bounded capacity supplied by a medic's completed major shift.
"""
from copy import deepcopy
from collections import Counter

from simulation.systems.campus_vitals import actor_layer, battle_locked, change_vital
from simulation.systems.transactions import TransactionOutcome

ACTION = "VISIT_CAMPUS_CLINIC"
SHIFTS = {"MEDICAL_SHIFT", "ON_CALL_MEDICAL_SHIFT"}
LOCATION = "hospital_clinic"
SHOP = "campus_pharmacy"
SUPPLIES = {"bandage_roll": 1, "antiseptic_bottle": 1}
VISITS_PER_SHIFT = 4
HEAL_PERCENT = 50
SERVICE_FEE = 8


def ledger(state):
    return state.situations.get("campus_medical", {})


def _available(state, actor_id):
    from simulation.systems.campus_night_sites import captive_site
    return (actor_id in state.population and actor_layer(state, actor_id) == "surface"
            and not battle_locked(state, actor_id) and not captive_site(state, actor_id))


def validate_shift(context, command, definition):
    if definition.activity_id not in SHIFTS:
        return None
    state = context.state
    actor = state.population.get(command.actor_id, {})
    if command.source == "player" and command.actor_id != "player":
        return TransactionOutcome(False, False, "actor_not_authorized", "不能替医护人员完成值班。")
    if (actor.get("occupation_id") != "medical_staff"
            or actor.get("current_location_id") != LOCATION
            or not _available(state, command.actor_id)
            or actor.get("vitals", {}).get("health", 0) <= 0):
        return TransactionOutcome(False, False, "medical_shift_unavailable", "须由能够行动的医护人员实际到表世界诊室值班。")
    if command.issued_day != state.clock.day or command.issued_phase != state.clock.phase:
        return TransactionOutcome(False, False, "command_clock_mismatch", "值班指令已过期。")
    return None


def settle_shift(context, command, definition):
    if definition.activity_id not in SHIFTS:
        return
    state = context.state
    book = state.situations.setdefault("campus_medical", {"schema_version": 1, "shifts": {}, "receipts": {}})
    key = f"{state.clock.day}:{state.clock.phase}:{command.actor_id}"
    # A second command must never manufacture a second capacity allocation.
    if key not in book["shifts"]:
        book["shifts"][key] = {"shift_id": key, "staff_id": command.actor_id,
            "day": state.clock.day, "phase": state.clock.phase,
            "location_id": LOCATION, "source_command_id": command.command_id,
            "capacity": VISITS_PER_SHIFT, "used": 0}


def price(state):
    catalog = state.inventories.get("catalog", {})
    if any(item not in catalog for item in SUPPLIES):
        return None
    return SERVICE_FEE + sum(catalog[item]["base_price"] * count for item, count in SUPPLIES.items())


def ready_shifts(state):
    result = []
    for key, row in sorted(ledger(state).get("shifts", {}).items()):
        staff = row["staff_id"]
        person = state.population.get(staff, {})
        if ((row["day"], row["phase"]) == (state.clock.day, state.clock.phase)
                and row["used"] < row["capacity"] and _available(state, staff)
                and person.get("occupation_id") == "medical_staff"
                and person.get("current_location_id") == LOCATION
                and person.get("vitals", {}).get("health", 0) > 0):
            result.append(row)
    return result


def visit_problem(state, actor_id, *, require_arrival=True):
    person = state.population.get(actor_id)
    if person is None:
        return "unknown_actor", "未找到就诊者。"
    if not _available(state, actor_id):
        return "clinic_layer_unavailable", "须先脱离战斗与被困状态，返回表世界。"
    if require_arrival and person.get("current_location_id") != LOCATION:
        return "clinic_arrival_required", "请沿道路和医院入口到诊室，手机不能远程治疗。"
    if state.clock.phase not in state.places.get(LOCATION, {}).get("open_phases", ()):
        return "clinic_closed", "诊室当前未开放。"
    vitals = person.get("vitals", {})
    if not vitals or vitals["health"] >= vitals["max_health"]:
        return "clinic_no_injury", "生命已满，无需伤势处理；专注不足可以回住处休息。"
    if any(r["patient_id"] == actor_id and (r["day"], r["phase"]) == (state.clock.day, state.clock.phase)
           for r in ledger(state).get("receipts", {}).values()):
        return "clinic_already_treated", "本时段已接受过诊室处理，仍可使用物品或回住处休息。"
    fee = price(state)
    shop = state.inventories.get("shops", {}).get(SHOP)
    if fee is None or shop is None or any(shop["quantities"].get(item, 0) < count for item, count in SUPPLIES.items()):
        return "clinic_supply_shortage", "诊室共用药房物资，目前不足；尚未扣款。"
    if person.get("wealth", 0) < fee:
        return "insufficient_funds", f"本次需 {fee} 元，余额不足；可回住处休息。"
    if not any(row["staff_id"] != actor_id for row in ready_shifts(state)):
        return "clinic_no_staff", "当前没有已到岗且仍有接诊名额的医护人员。"
    return None


def make_medical_handler():
    def handle(context, command):
        state, actor_id = context.state, command.actor_id
        if command.source == "player" and actor_id != "player":
            return TransactionOutcome(False, False, "actor_not_authorized", "只能为自己申请就诊。")
        if command.action_id != ACTION or command.parameters:
            return TransactionOutcome(False, False, "invalid_clinic_request", "就诊使用本人实际状态，不能指定他人的治疗、价格或效果。")
        if command.issued_day != state.clock.day or command.issued_phase != state.clock.phase:
            return TransactionOutcome(False, False, "command_clock_mismatch", "就诊指令已过期。")
        problem = visit_problem(state, actor_id)
        if problem:
            return TransactionOutcome(False, False, *problem)
        shift = next(row for row in ready_shifts(state) if row["staff_id"] != actor_id)
        fee = price(state)
        person = state.population[actor_id]
        shop = state.inventories["shops"][SHOP]
        # All checks precede mutations, including for internal rule execution.
        person["wealth"] -= fee
        shop["cash"] += fee
        for item, count in SUPPLIES.items():
            shop["quantities"][item] -= count
        shift["used"] += 1
        vitals = person["vitals"]
        health = change_vital(state, actor_id, "health", max(1, vitals["max_health"] * HEAL_PERCENT // 100))
        receipt_id = f"clinic:{state.clock.day}:{state.clock.phase}:{actor_id}"
        receipt = {"receipt_id": receipt_id, "patient_id": actor_id, "staff_id": shift["staff_id"],
            "shift_id": shift["shift_id"], "day": state.clock.day, "phase": state.clock.phase,
            "location_id": LOCATION, "fee": fee, "materials": dict(SUPPLIES),
            "health": health, "major_action_cost": 0, "source_command_id": command.command_id}
        ledger(state)["receipts"][receipt_id] = receipt
        context.emit("CAMPUS_CLINIC_CARE_COMPLETED", "在诊室接受了伤势处理。",
            actor_ids=[actor_id, shift["staff_id"]], scene_id=LOCATION,
            payload=deepcopy(receipt), visibility="private", knowledge_tags=["care", "recovery"])
        return TransactionOutcome(True, True, "success", f"伤势处理完成，恢复 {health['delta']} 点生命，花费 {fee} 元；未消耗主要行动。",
            commit=True, payload=deepcopy(receipt))
    return handle


def medical_view(state, actor_id="player"):
    problem = visit_problem(state, actor_id)
    return {"location_id": LOCATION, "fee": price(state), "heal_percent": HEAL_PERCENT,
        "major_action_cost": 0, "can_visit": problem is None,
        "reason": problem[1] if problem else "可接受伤势处理；不恢复专注、不清除污染。",
        "available_visits": sum(row["capacity"] - row["used"] for row in ready_shifts(state)),
        "receipts": [deepcopy(row) for row in ledger(state).get("receipts", {}).values()
                     if row["patient_id"] == actor_id][-12:]}


def clinic_candidates(state, actor_id, graph):
    """A conditional option, not foreknowledge of staff choices or arrival."""
    problem = visit_problem(state, actor_id, require_arrival=False)
    if problem and problem[0] != "clinic_no_staff":
        return []
    actor = state.population[actor_id]
    route = graph.shortest_route(actor["current_location_id"], LOCATION, phase=state.clock.phase,
                                 access_tags=actor.get("access_tags", ()))
    if route is None:
        return []
    return [{"activity_id": ACTION, "action_class": "free", "location_id": LOCATION,
        "parameters": {}, "max_unit_price": price(state), "route_step_count": len(route.steps),
        "decision_source": "rule", "decision_reason": "injury_with_optional_clinic_care",
        "reason": f"本人生命 {actor['vitals']['health']}/{actor['vitals']['max_health']}；可付 {price(state)} 元申请处理伤势，最多恢复50%最大生命，不恢复专注。到场后须有医护和物资，每时段限一次；可不选，回家充分休息仍能全恢复。",
        "reason_codes": ["injury", "affordable", "clinic_open", "staff_rechecked_on_arrival"],
        "day": state.clock.day, "phase": state.clock.phase}]


def optional_errand_candidates(state, actor_id, graph, *, rule_choice=False):
    from simulation.systems.campus_trade import procurement_candidates
    purchases = procurement_candidates(state, actor_id, graph)
    care = clinic_candidates(state, actor_id, graph)
    if rule_choice and care:
        actor = state.population[actor_id]
        vitals = actor["vitals"]
        # Ordinary NPCs weigh injury, financial reserve and risk tolerance;
        # a successful LLM plan is never silently replaced by this preference.
        if (vitals["health"] * 2 > vitals["max_health"] or actor["wealth"] < price(state) * 2
                or actor.get("personality", {}).get("risk_tolerance", 50) > 80):
            care = []
    return care + purchases


def medical_invariant(state):
    book = ledger(state)
    if not book:
        return []  # Legacy and minimal worlds need no eager migration.
    errors = []
    if not isinstance(book, dict) or book.get("schema_version") != 1 or not isinstance(book.get("shifts"), dict) or not isinstance(book.get("receipts"), dict):
        return ["invalid campus medical ledger"]
    counts = Counter(r.get("shift_id") for r in book["receipts"].values()
                     if isinstance(r, dict) and isinstance(r.get("shift_id"), str))
    def valid_person(value):
        return isinstance(value, str) and value in state.population

    def valid_clock(row):
        from simulation.systems.campus_anomaly_meetings import stamp
        return (type(row.get("day")) is int and 1 <= row["day"] <= state.clock.day
                and row.get("phase") in ("morning", "afternoon", "evening", "late_night")
                and stamp(row["day"], row["phase"]) <= stamp(state.clock.day, state.clock.phase))
    for key, row in book["shifts"].items():
        if (not isinstance(row, dict) or row.get("shift_id") != key
                or not valid_person(row.get("staff_id")) or row.get("location_id") != LOCATION
                or not valid_clock(row) or key != f"{row['day']}:{row['phase']}:{row['staff_id']}"
                or row.get("capacity") != VISITS_PER_SHIFT or type(row.get("used")) is not int
                or not 0 <= row["used"] <= VISITS_PER_SHIFT
                or not isinstance(row.get("source_command_id"), str) or not row["source_command_id"]):
            errors.append("invalid campus medical shift")
            continue
        if counts[key] != row["used"]:
            errors.append("campus medical capacity and receipts disagree")
    for key, row in book["receipts"].items():
        if not isinstance(row, dict):
            errors.append("invalid campus medical receipt")
            continue
        shift = book["shifts"].get(row.get("shift_id"), {}) if isinstance(row.get("shift_id"), str) else {}
        if not isinstance(shift, dict):
            shift = {}
        health = row.get("health", {})
        if (row.get("receipt_id") != key or not valid_person(row.get("patient_id"))
                or not valid_clock(row) or key != f"clinic:{row['day']}:{row['phase']}:{row['patient_id']}"
                or not shift or row.get("staff_id") != shift.get("staff_id")
                or row.get("patient_id") == row.get("staff_id")
                or (row.get("day"), row.get("phase")) != (shift.get("day"), shift.get("phase"))
                or row.get("location_id") != LOCATION or row.get("materials") != SUPPLIES
                or row.get("major_action_cost") != 0 or type(row.get("fee")) is not int or row["fee"] < SERVICE_FEE
                or not isinstance(health, dict) or not all(type(health.get(k)) is int for k in ("before", "after", "delta"))
                or health.get("before", -1) < 0 or health.get("delta", 0) <= 0
                or health.get("after", 0) - health.get("before", 0) != health.get("delta")
                or not isinstance(row.get("source_command_id"), str) or not row["source_command_id"]):
            errors.append("invalid campus medical receipt")
    return errors
