"""Persistent campus consequences derived from authoritative stock/site state.

No model-authored facts or rewards. Repeated reviews never charge the same
resolved/expired site twice; historical evidence is retained in world events.
"""
from copy import deepcopy

MAX_PRESSURE = 12


def _ledger(state):
    return state.situations.setdefault("campus_dynamics", {
        "schema_version": 1, "last_decay_day": state.clock.day, "regions": {},
        "processed_sites": {}, "shortages": {}, "sequence": 0, "recent": [],
    })


def regional_pressure(state, location_id):
    region = state.places.get(location_id, {}).get("region_id") or location_id
    return state.situations.get("campus_dynamics", {}).get("regions", {}).get(region, {}).get("pressure", 0)


def weighted_night_templates(state, templates):
    return [key for key in sorted(templates) for _ in range(1 + regional_pressure(state, templates[key]["scene_id"]) // 3)]


def _record(context, ledger, kind, identity, before, after, cause, visibility, location, actors=()):
    ledger["sequence"] += 1
    row = {"change_id": f"campus-situation:{ledger['sequence']}", "day": context.state.clock.day,
        "phase": context.state.clock.phase, "kind": kind, "subject_id": identity,
        "before": before, "after": after, "cause": cause}
    ledger["recent"].append(row)
    ledger["recent"] = ledger["recent"][-80:]
    context.emit("CAMPUS_SITUATION_CHANGED", "区域异常压力发生变化。" if kind == "night_pressure" else "校园物资供应状况发生变化。",
        actor_ids=actors, scene_id=location, payload=deepcopy(row), visibility=visibility,
        severity=2, knowledge_tags=["situation", kind])


def advance_campus_situations(context):
    state, changes = context.state, 0
    ledger = _ledger(state)
    elapsed = state.clock.day - ledger["last_decay_day"]
    if elapsed > 0:
        for region, record in ledger["regions"].items():
            before = record["pressure"]
            record["pressure"] = max(0, before - elapsed)
            if record["pressure"] != before:
                _record(context, ledger, "night_pressure", region, before, record["pressure"], "natural_settling", "secret", region)
                changes += 1
        ledger["last_decay_day"] = state.clock.day
    sites = state.situations.get("night_sites", {}).get("sites", {})
    for site_id, site in sorted(sites.items()):
        if site_id in ledger["processed_sites"] or site["status"] not in {"resolved", "expired"}:
            continue
        ledger["processed_sites"][site_id] = site["status"]
        # Old saves gain this system lazily; do not retroactively penalize weeks
        # of terminal sites. Current/previous-day consequences remain eligible.
        terminal_day = (site.get("receipt") or {}).get("day", site["expires_day"] + 1)
        if terminal_day < state.clock.day - 1:
            continue
        region = site["region_id"]
        record = ledger["regions"].setdefault(region, {"pressure": 0, "source_site_ids": []})
        before = record["pressure"]
        record["pressure"] = max(0, min(MAX_PRESSURE, before + (2 if site["status"] == "expired" else -3)))
        record["source_site_ids"] = [*record["source_site_ids"], site_id][-12:]
        actors = [(site.get("receipt") or {}).get("actor_id")]
        _record(context, ledger, "night_pressure", region, before, record["pressure"], site_id,
                "secret", site["location_id"], [a for a in actors if a in state.population])
        changes += 1
    supply = state.inventories.get("supply", {})
    reorder = supply.get("policy", {}).get("reorder_percent", 25)
    for shop_id, targets in supply.get("targets", {}).items():
        shop = state.inventories["shops"][shop_id]
        for item_id, target in targets.items():
            key = shop_id + ":" + item_id
            stock = shop["quantities"].get(item_id, 0)
            low = stock * 100 <= target * reorder
            previous = ledger["shortages"].get(key)
            if not low and (not previous or previous["status"] == "resolved"):
                continue
            if previous is None or previous["status"] == "resolved":
                previous = {"shop_id": shop_id, "item_id": item_id, "since_day": state.clock.day,
                    "status": "watch", "stock": stock, "target": target, "updated_day": state.clock.day}
                ledger["shortages"][key] = previous
                before = "normal"
            else:
                before = previous["status"]
            status = "resolved" if not low else "shortage" if state.clock.day > previous["since_day"] else "watch"
            previous.update(status=status, stock=stock, updated_day=state.clock.day)
            if status != before:
                _record(context, ledger, "supply_shortage", key, before, status, "actual_shop_stock", "public", shop["location_id"])
                changes += 1
    return {"campus_situation_changes": changes}


def shortage_age(state, shop_id, item_id):
    entry = state.situations.get("campus_dynamics", {}).get("shortages", {}).get(shop_id + ":" + item_id)
    return state.clock.day - entry["since_day"] if entry and entry["status"] != "resolved" else 0


def situation_forum_view(state, night_unlocked):
    ledger = state.situations.get("campus_dynamics", {})
    surface, night = [], []
    for entry in ledger.get("shortages", {}).values():
        shop = state.inventories["shops"][entry["shop_id"]]
        name = state.inventories["catalog"][entry["item_id"]]["name"]
        status = {"watch": "库存偏低", "shortage": "持续短缺", "resolved": "供应已恢复"}[entry["status"]]
        surface.append({"id": entry["shop_id"] + ":" + entry["item_id"], "status": entry["status"],
            "summary": f"{shop['name']} · {name}：{status}（第 {entry['since_day']} 天起）",
            "location_id": shop["location_id"], "updated_day": entry["updated_day"]})
    if night_unlocked:
        for region, entry in ledger.get("regions", {}).items():
            pressure = entry["pressure"]
            night.append({"id": region, "pressure": pressure, "exposure_bonus": pressure // 4,
                "summary": f"{state.places[region]['name']} · 异常压力 {pressure}/{MAX_PRESSURE}；夜间额外暴露 +{pressure // 4}",
                "source_site_ids": list(entry["source_site_ids"]),
                "history": [deepcopy(row) for row in ledger.get("recent", ())
                            if row["kind"] == "night_pressure" and row["subject_id"] == region][-8:]})
    return {"surface": surface, "night": night}


def campus_situations_invariant(state):
    ledger = state.situations.get("campus_dynamics")
    if ledger is None:
        return
    try:
        if ledger["schema_version"] != 1 or type(ledger["last_decay_day"]) is not int or not 1 <= ledger["last_decay_day"] <= state.clock.day:
            yield "invalid campus dynamics version/day"
        if type(ledger["sequence"]) is not int or ledger["sequence"] < len(ledger["recent"]) or len(ledger["recent"]) > 80:
            yield "invalid campus dynamics history"
        sites = state.situations.get("night_sites", {}).get("sites", {})
        for site_id, status in ledger["processed_sites"].items():
            if site_id not in sites or status not in {"resolved", "expired"} or sites[site_id]["status"] != status:
                yield "invalid campus dynamics site receipt"
        for region, row in ledger["regions"].items():
            if region not in state.places or type(row["pressure"]) is not int or not 0 <= row["pressure"] <= MAX_PRESSURE:
                yield "invalid campus regional pressure"
            if len(row["source_site_ids"]) > 12 or any(s not in sites or sites[s]["region_id"] != region for s in row["source_site_ids"]):
                yield "invalid campus pressure provenance"
        for key, row in ledger["shortages"].items():
            if (key != row["shop_id"] + ":" + row["item_id"] or row["shop_id"] not in state.inventories["shops"]
                    or row["item_id"] not in state.inventories["shops"][row["shop_id"]]["accepted_item_ids"]
                    or row["status"] not in {"watch", "shortage", "resolved"}
                    or not 1 <= row["since_day"] <= row["updated_day"] <= state.clock.day):
                yield "invalid campus shortage episode"
    except (KeyError, TypeError, AttributeError):
        yield "malformed campus dynamics ledger"
