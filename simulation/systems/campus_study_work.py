"""Named learning and paid shifts on the existing attendance/wealth ledgers.

No course credit for booking; no separate wallet, minted wages or stock.
Course units derive from validated receipts, not from a client progress claim.
"""
from copy import deepcopy
from dataclasses import replace


def course_progress(state, actor_id, offer_id):
    data = state.situations.get("campus_life", {})
    definition = data.get("definitions", {}).get(offer_id, {})
    units = definition.get("course", {}).get("units", [])
    receipts = []
    for sid, actors in data.get("records", {}).items():
        if not sid.endswith(":" + offer_id):
            continue
        record = actors.get(actor_id, {})
        receipt = record.get("result", {}).get("course", {})
        if record.get("status") == "completed" and receipt:
            receipts.append({**deepcopy(receipt), "session_id": sid})
    receipts.sort(key=lambda r: r["unit_index"])
    done = len(receipts)
    return {"offer_id": offer_id, "name": definition.get("name", offer_id), "completed_units": done,
            "total_units": len(units), "complete": bool(units) and done == len(units),
            "next_unit": units[done] if done < len(units) else "已完成全部单元",
            "receipts": receipts}


def study_work_assessment(state, actor_id, row):
    data = state.situations["campus_life"]
    course, job = row.get("course"), row.get("job")
    if course:
        progress = course_progress(state, actor_id, row["id"])
        if progress["complete"]:
            return "course_complete", "已完成这门课程的全部单元，可以选择其他学习或实际应用。"
        reserved = sum(actors.get(actor_id, {}).get("status") == "enrolled"
            for sid, actors in data["records"].items()
            if sid != row["session_id"] and sid.endswith(":" + row["id"]))
        if reserved + progress["completed_units"] >= progress["total_units"]:
            return "course_units_reserved", "剩余课程单元已有报名，请先赴约或退出原报名。"
    if job:
        prerequisite = job.get("required_course")
        if prerequisite and not course_progress(state, actor_id, prerequisite)["complete"]:
            name = data["definitions"][prerequisite]["name"]
            return "job_qualification", f"需要先实际完成{name}的全部单元。"
        actors = data["records"].get(row["session_id"], {})
        used = sum(n != actor_id and r["status"] in {"enrolled", "completed"} for n,r in actors.items())
        if used >= job["openings"]:
            return "job_filled", "这一班岗位已被其他参与者接取或完成。"
        # Honor earlier bookings in the same cash pool, without minting a
        # separate escrow balance. Shop trading can still change cash: recheck
        # at execution, and fail atomically instead of promising unpaid work.
        reserved = 0
        for sid, entries in data["records"].items():
            definition = data["definitions"][sid.split(":")[2]]
            other_job = definition.get("job", {})
            if other_job.get("shop_id") == job["shop_id"]:
                reserved += sum(other_job["wage"] for n,r in entries.items()
                    if r["status"] == "enrolled" and (sid, n) != (row["session_id"], actor_id))
        shop = state.inventories["shops"][job["shop_id"]]
        if shop["cash"] - reserved < job["wage"]:
            return "job_funds_unavailable", "付款方当前可用现金不足；未扣行动、未记出勤，可稍后再试或退出。"
    return None


def activity_terms(state, command, definition):
    sid = command.parameters.get("life_session_id")
    if not sid:
        return definition
    row = state.situations["campus_life"]["definitions"][sid.split(":")[2]]
    if row.get("course"):
        return replace(definition, knowledge_topic=row["course"]["topic"])
    if row.get("job"):
        # Named shifts transfer the configured wage instead of also minting
        # the generic routine-work wealth_delta. Legacy salaries stay scoped.
        return replace(definition, wealth_delta=0)
    return definition


def settle_study_work(context, actor_id, row, effects):
    state = context.state
    result = {}
    if row.get("course"):
        progress = course_progress(state, actor_id, row["id"])
        result["course"] = {"unit_index": progress["completed_units"], "unit_name": progress["next_unit"],
            "topic": row["course"]["topic"], "knowledge_gain": effects["knowledge"]["gain"]}
    if row.get("job"):
        job = row["job"]
        shop = state.inventories["shops"][job["shop_id"]]
        before = shop["cash"]
        shop["cash"] -= job["wage"]
        state.population[actor_id]["wealth"] += job["wage"]
        wealth = effects["wealth"]
        wealth["after"] = state.population[actor_id]["wealth"]
        wealth["delta"] = wealth["after"] - wealth["before"]
        result["job"] = {"shop_id": job["shop_id"], "payer_name": shop["name"], "wage": job["wage"],
                         "payer_before": before, "payer_after": shop["cash"]}
    return result


def study_work_view(state, actor_id, row):
    if row.get("course"):
        progress = course_progress(state, actor_id, row["id"])
        return {"kind": "course", "summary": f"本人课程进度 {progress['completed_units']}/{progress['total_units']} · 下一单元：{progress['next_unit']}"}
    if row.get("job"):
        job = row["job"]
        records = state.situations["campus_life"]["records"].get(row["session_id"], {})
        remaining = max(0, job["openings"] - sum(r["status"] in {"enrolled", "completed"} for r in records.values()))
        return {"kind": "job", "summary": f"班次报酬 {job['wage']} · 剩余岗位 {remaining}/{job['openings']} · 到场复核后由现有商店现金支付"}
    return {"kind": "activity", "summary": "普通公开活动"}


def visible_result(result):
    visible = deepcopy(result)
    if "job" in visible:
        visible["job"] = {key: value for key,value in visible["job"].items() if key in {"shop_id", "payer_name", "wage"}}
    return visible


def study_work_definition_errors(definitions, shops):
    for row in definitions.values():
        if not isinstance(row, dict):
            yield "invalid study/work definition"
            continue
        course, job = row.get("course"), row.get("job")
        if course is not None and job is not None:
            yield "opportunity cannot be both course and job"
        if course is not None:
            if (not isinstance(course, dict) or not isinstance(course.get("topic"), str)
                    or not course["topic"].startswith("course:") or row.get("activity_id") != "COURSEWORK"
                    or not isinstance(course.get("units"), list) or not course["units"]
                    or any(not isinstance(u, str) or not u for u in course["units"])
                    or len(set(course["units"])) != len(course["units"])):
                yield "invalid course units or activity"
        if job is not None:
            if (not isinstance(job, dict) or not isinstance(job.get("shop_id"), str)
                    or job["shop_id"] not in shops or row.get("activity_id") != "CAMPUS_SERVICE_SHIFT"
                    or shops[job["shop_id"]].get("location_id") != row.get("location_id")
                    or type(job.get("wage")) is not int or job["wage"] <= 0
                    or type(job.get("openings")) is not int or job["openings"] <= 0
                    or (job.get("required_course") is not None and
                        (not isinstance(job["required_course"], str) or not definitions.get(job["required_course"], {}).get("course")))):
                yield "invalid job payer, wage, openings or qualification"


def study_work_invariant(state):
    data = state.situations.get("campus_life", {})
    definitions = data.get("definitions", {})
    errors = list(study_work_definition_errors(definitions, state.inventories.get("shops", {})))
    if errors:
        yield from errors
        return
    unit_indices = {}
    for sid, actors in data.get("records", {}).items():
        if not isinstance(sid, str) or not isinstance(actors, dict) or any(not isinstance(r, dict) for r in actors.values()):
            yield "invalid study/work participants"
            continue
        definition = definitions.get(sid.split(":")[-1], {})
        job, course = definition.get("job"), definition.get("course")
        if job and sum(r.get("status") in {"enrolled", "completed"} for r in actors.values()) > job["openings"]:
            yield "job overbooked"
        for actor_id, record in actors.items():
            result = record.get("result", {})
            if not isinstance(result, dict):
                yield "invalid study/work receipt"
                continue
            if record.get("status") != "completed":
                if result:
                    yield "unearned study/work receipt"
                continue
            if course:
                receipt = result.get("course", {})
                index = receipt.get("unit_index") if isinstance(receipt, dict) else None
                if (type(index) is not int or not 0 <= index < len(course["units"])
                        or receipt.get("unit_name") != course["units"][index] or receipt.get("topic") != course["topic"]
                        or type(receipt.get("knowledge_gain")) is not int or receipt["knowledge_gain"] <= 0):
                    yield "invalid course receipt"
                else:
                    unit_indices.setdefault((actor_id, definition["id"]), []).append(index)
            if job:
                receipt = result.get("job", {})
                if (not isinstance(receipt, dict) or receipt.get("shop_id") != job["shop_id"]
                        or receipt.get("wage") != job["wage"]
                        or type(receipt.get("payer_before")) is not int or type(receipt.get("payer_after")) is not int
                        or receipt["payer_after"] < 0 or receipt["payer_before"] - receipt["payer_after"] != job["wage"]):
                    yield "invalid wage receipt"
    for indices in unit_indices.values():
        if sorted(indices) != list(range(len(indices))):
            yield "duplicate or skipped course unit"
