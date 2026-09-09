"""Dated first-person experience and actual participation, never a world radar."""
from simulation.systems.campus_anomalies import INITIAL

PHASE_LABELS = {"morning": "上午", "afternoon": "下午", "evening": "晚上", "late_night": "凌晨"}
ROUTE_GUIDE = [
    {"route": "day", "label": "白天支持", "note": "需本人愿意、相关理解和实际见面；双方各一次主要行动，每事件每天一次。可持续改善体验与关系，不恢复生命或专注。"},
    {"route": "night", "label": "夜间封控", "note": "需夜相资格、持有任务、实际到场与战斗；本时段首次探索扣主要行动，后续战斗延续资源消耗。胜利仍须现场处置；只切断外壳，不能替代本人参与。"},
    {"route": "mixed", "label": "联合安排", "note": "白天支持可削弱后续残像；自己的可靠共同经历和理解可提供战斗洞察。夜间降低现场风险后，仍应重新询问本人，而非默认心结已解。"},
]


def experience_at(case, revision):
    history = case["history"][:revision]
    values = history[-1]["after"] if history else INITIAL
    return {"support_sessions": sum(r["route"] == "day_support" for r in history),
        "images": "quiet" if values["shell"] == 0 else "recurring",
        "stability": "stable" if not any(values.values()) else "easing" if history else "unsettled"}


def experience_valid(case, report):
    if "experience" not in report:
        return True  # Do not reconstruct unheard disclosures for older saves.
    value = report["experience"]
    return (isinstance(value, dict) and type(value.get("support_sessions")) is int
        and value == experience_at(case, report["revision"]))


def route_feedback(state, case, viewer):
    report = case["reports"].get(viewer)
    if not report:
        return {}
    # Only use the historical report, not today's hidden internal state.
    experience = report.get("experience")
    if experience:
        image = "反复影像已安静下来" if experience["images"] == "quiet" else "仍有反复影像"
        stability = {"stable": "已能区分眼前生活与残留体验", "easing": "有所缓和，仍需巩固", "unsettled": "仍受这段体验困扰"}[experience["stability"]]
        statement = f"本人在第 {report['day']} 天{PHASE_LABELS[report['phase']]}告知：共同支持过 {experience['support_sessions']} 次；{image}；{stability}。这是当时的陈述，不是实时状态。"
    else:
        statement = "旧记录只有当时的陈述，没有这些细节；需要重新询问本人，不补造历史信息。"
    records, day_count, night_count = [], 0, 0
    for receipt in case["history"]:
        if receipt["route"] == "day_support" and receipt["helper_id"] == viewer:
            day_count += 1
            text = "你与本人完成了" + ("深入支持" if receipt.get("anchor_id") else "现实锚定")
            gains = receipt.get("relationship_changes", {}).get("subject", {}).get("applied")
            if gains:
                text += f"；对方对你的信任增加 {gains['trust']}、亲近增加 {gains['closeness']}"
            records.append({"kind": "day_support", "text": f"第 {receipt['day']} 天{PHASE_LABELS[receipt['phase']]}：{text}。双方各消耗一次主要行动。"})
    for battle in state.battles.values():
        if (battle.get("anomaly_origin", {}).get("case_id") != case["case_id"] or viewer not in battle["participant_ids"]
                or battle.get("phase") != "resolved"):
            continue
        receipt = next((r for r in case["history"] if r.get("battle_id") == battle["battle_id"]), None)
        if receipt:
            night_count += 1
            result = "残像已击败且现场已处置；这不是本人心结已经解决的证明"
        else:
            result = {"victory": "战斗获胜，但尚无完成现场处置的记录", "defeat": "小队败北，未完成封控；救回宿舍后按原规则休息恢复",
                "escaped": "已撤退，未完成封控；既有消耗不退还"}.get(battle["result"], "战斗已结束，未确认完成封控")
        records.append({"kind": "night_battle", "text": f"你参与的夜战：{result}。结束时记录：生命 {battle['health'][viewer]}、专注 {battle['focus'][viewer]}、污染 {battle['pollution'][viewer]}（不是当前数值）。"})
    path = "白天支持＋夜间处置" if day_count and night_count else "白天支持" if day_count else "夜间处置" if night_count else "尚无已完成的支持或处置记录"
    return {"statement": statement, "own_path": path, "own_records": records[-8:],
        "scope_note": "只列你亲自参与的结果；他人的未公开行动、尚未完成的预约不计作你的成果。", "route_guide": [dict(row) for row in ROUTE_GUIDE]}
