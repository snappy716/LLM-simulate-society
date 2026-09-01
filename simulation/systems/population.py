"""Deterministic scene, resident, profession, and work-schedule generation."""
from __future__ import annotations

from simulation.domain.entities import NPC, NPCLayer, Scene


def make_scenes():
    definitions = [
        ("home_quarter", "住宅区", ["residential"], 15, 35, 70, ["burglary", "family"]),
        ("market", "市场", ["public", "trade"], 25, 35, 10, ["pickpocket", "rumor", "trade"]),
        ("red_moon_street", "红月亮街", ["public", "nightlife"], 45, 25, 15, ["crime", "rumor"]),
        ("evernight_church", "黑夜女神教堂", ["religious", "public", "sanctuary", "official_controlled", "occult_protected"], 3, 95, 55, ["religion", "aid"]),
        ("tavern", "酒馆", ["public", "social"], 40, 15, 10, ["rumor", "fight", "gambling"]),
        ("newspaper", "报社", ["work", "information"], 10, 40, 30, ["rumor", "investigation"]),
        ("police_station", "警察局", ["official"], 5, 90, 50, ["law", "investigation"]),
        ("east_dock", "东码头", ["work", "public"], 55, 25, 20, ["smuggling", "crime", "occult"]),
        ("warehouse_3", "三号仓库", ["restricted", "industrial"], 65, 35, 85, ["smuggling", "occult", "crime"]),
        ("hospital", "医院", ["medical"], 5, 60, 50, ["illness", "recovery"]),
        ("factory", "工厂区", ["work", "industrial"], 40, 30, 15, ["injury", "labor"]),
        ("underground_market", "地下市场", ["secret", "trade"], 70, 20, 80, ["occult", "crime", "trade"]),
        ("blackthorn_security", "黑荆棘安保公司", ["official", "beyonder", "restricted"], 15, 90, 75, ["law", "occult", "investigation"]),
        ("chanis_gate", "查尼斯门地下区域", ["official", "sealed", "occult"], 80, 100, 100, ["sealed_artifact", "occult"]),
        ("divination_club", "廷根占卜俱乐部", ["public", "occult", "social"], 20, 35, 30, ["divination", "rumor", "occult"]),
        ("university", "大学", ["public", "education"], 8, 45, 25, ["study", "research", "rumor"]),
        ("bank", "银行", ["public", "finance", "secure"], 18, 80, 35, ["money", "fraud", "robbery"]),
        ("detective_agency", "侦探会所", ["public", "investigation"], 20, 45, 45, ["investigation", "commission", "rumor"]),
        ("opera_house", "歌剧院", ["public", "culture", "nightlife"], 20, 40, 20, ["performance", "rumor", "social"]),
        ("asylum", "疯人院", ["medical", "restricted"], 35, 70, 65, ["illness", "occult", "recovery"]),
        ("restaurant", "餐厅", ["public", "food", "social"], 15, 30, 10, ["food", "rumor", "social"]),
    ]
    return {definition[0]: Scene(*definition) for definition in definitions}


OCCUPATIONS = [
    ("文职员工", "blackthorn_security"), ("警察", "police_station"),
    ("教士", "evernight_church"), ("摊贩", "market"), ("杂货商", "market"),
    ("裁缝", "market"), ("酒保", "tavern"), ("酒馆侍者", "tavern"),
    ("医生", "hospital"), ("护士", "hospital"), ("药剂师", "hospital"),
    ("护工", "hospital"), ("码头工人", "east_dock"),
    ("码头调度员", "east_dock"), ("货运书记员", "east_dock"),
    ("工厂工人", "factory"), ("机械师", "factory"), ("车间主管", "factory"),
    ("大学教师", "university"), ("大学生", "university"),
    ("图书管理员", "university"), ("记者", "newspaper"), ("编辑", "newspaper"),
    ("印刷工", "newspaper"), ("占卜师", "divination_club"),
    ("俱乐部接待员", "divination_club"), ("银行柜员", "bank"),
    ("会计", "bank"), ("银行警卫", "bank"), ("私家侦探", "detective_agency"),
    ("侦探助理", "detective_agency"), ("歌剧演员", "opera_house"),
    ("乐师", "opera_house"), ("舞台工", "opera_house"), ("售票员", "opera_house"),
    ("精神科医生", "asylum"), ("疯人院护士", "asylum"), ("看护员", "asylum"),
    ("厨师", "restaurant"), ("餐厅侍者", "restaurant"), ("餐厅经理", "restaurant"),
]

WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


def build_work_schedule(idx, work_scene, occupation):
    if work_scene in {"hospital", "asylum"}:
        shifts = [["morning", "afternoon"], ["afternoon", "evening"], ["evening", "late_night"]]
        phases = shifts[idx % len(shifts)]
    elif work_scene in {"tavern", "restaurant", "opera_house"}:
        phases = ["afternoon", "evening"] if idx % 3 else ["evening", "late_night"]
    elif work_scene in {"east_dock", "factory"}:
        phases = (["morning", "afternoon"] if idx % 3 == 0 else
                  ["afternoon", "evening"] if idx % 3 == 1 else
                  ["late_night", "morning"])
    else:
        phases = ["morning", "afternoon"]
    if occupation == "大学生":
        return [0, 1, 2, 3, 4], ["morning", "afternoon"]
    first_off = idx % 7
    second_off = (first_off + 1) % 7
    return [day for day in range(7) if day not in {first_off, second_off}], phases


def initialize_special_needs(npc):
    needs = {}
    if npc.sequence_pathway == "罪犯":
        needs["crime_control"] = 75
    if npc.sequence_pathway == "秘祈人":
        needs["ritual_stability"] = 70
        needs["occult_supply"] = 60
    elif npc.layer != NPCLayer.ORDINARY.value:
        needs["occult_supply"] = 65
    npc.special_needs = needs


def make_npc(idx, tier, rng):
    occupation, work_scene = rng.choice(OCCUPATIONS)
    organization = None
    if occupation == "教会职员":
        organization = "evernight_church"
    elif occupation == "警察":
        organization = "police"
    elif rng.random() < 0.10:
        organization = rng.choice(["secret_order", "aurora_cell", "merchant_guild"])

    npc = NPC(
        id=f"npc_{idx:03d}", name=str(idx + 1), tier=tier, occupation=occupation,
        home_scene=f"home_{idx + 1:03d}", work_scene=work_scene,
        personality={"curiosity": rng.randint(20, 90), "risk": rng.randint(10, 90),
                     "social": rng.randint(15, 90), "morality": rng.randint(20, 95),
                     "ambition": rng.randint(15, 95)},
        needs={"hunger": rng.randint(5, 35), "fatigue": rng.randint(5, 35),
               "financial_pressure": rng.randint(10, 80)},
        emotions={"anger": rng.randint(0, 20), "anxiety": rng.randint(0, 25),
                  "happiness": rng.randint(20, 70), "fear": rng.randint(0, 20)},
        abilities={"knowledge": rng.randint(2, 8), "inspiration": rng.randint(2, 8),
                   "dexterity": rng.randint(2, 8), "strength": rng.randint(2, 8),
                   "luck": rng.randint(2, 8), "charm": rng.randint(2, 8)},
        organization=organization, current_scene="home_quarter",
        skills={"observation": rng.randint(2, 12), "tracking": rng.randint(1, 10),
                "stealth": rng.randint(1, 10), "counter_tracking": rng.randint(1, 10),
                "investigation": rng.randint(2, 12), "deception": rng.randint(1, 10),
                "insight": rng.randint(2, 12), "combat": rng.randint(1, 10),
                "ritual": rng.randint(0, 8), "mysticism": rng.randint(0, 8),
                "willpower": rng.randint(2, 12)},
        states={"energy": rng.randint(60, 95), "satiety": rng.randint(55, 95),
                "stress": rng.randint(5, 30), "fear": rng.randint(0, 20), "pain": 0,
                "alertness": rng.randint(35, 85), "morale": rng.randint(45, 85),
                "loneliness": rng.randint(5, 45), "reputation": 50, "legal_risk": 0,
                "social_support": rng.randint(20, 70), "civic_duty": rng.randint(20, 90)},
        wealth=rng.randint(20, 100), sanity=rng.randint(65, 95),
    )
    npc.goals = [
        f"维持自己的{occupation}生活",
        rng.choice(["改善财富状况", "保护家人与朋友", "获得社会地位", "了解最近的异常传闻", "避免惹上危险"]),
    ]
    if idx < 8:
        npc.layer = NPCLayer.OFFICIAL_BEYONDER.value
        npc.sequence_pathway = "不眠者"
        npc.sequence_rank = rng.choice([7, 8, 9])
        npc.organization = "nightwatchers_tingen"
        npc.faction_ids = ["nightwatchers_tingen"]
        npc.duties = ["响应非凡异常", "保护普通人", "收容危险物品", "调查邪教组织"]
        if idx < 6:
            npc.occupation, npc.work_scene = "外勤员工", "blackthorn_security"
        else:
            npc.occupation, npc.work_scene = "教士", "evernight_church"
            npc.organization = "evernight_church"
            npc.faction_ids = ["evernight_church"]
            npc.duties = ["主持教会事务", "安抚信徒", "响应非凡异常", "保护普通人"]
    elif idx < 15:
        npc.layer = NPCLayer.WILD_BEYONDER.value
        npc.sequence_pathway = rng.choice(["占卜家", "学徒", "怪物", "猎人"])
        npc.sequence_rank = rng.choice([7, 8, 9])
        npc.faction_ids = []
        npc.duties = ["隐藏非凡身份", "维持生存"]
    elif idx < 20:
        npc.layer = NPCLayer.HOSTILE_BEYONDER.value
        npc.sequence_pathway = {15: "罪犯", 16: "囚犯", 17: "秘祈人", 18: "罪犯", 19: "秘祈人"}.get(
            idx, rng.choice(["罪犯", "囚犯", "秘祈人"])
        )
        npc.sequence_rank = rng.choice([7, 8, 9])
        npc.organization = rng.choice(["aurora_order_tingen", "secret_cult_tingen"])
        npc.faction_ids = [npc.organization]
        npc.duties = ["服从隐秘组织命令", "掩盖非凡痕迹", "避开官方调查"]

    occupation_bonuses = {
        "警察": {"investigation": 5, "observation": 4, "tracking": 3},
        "记者": {"investigation": 4, "insight": 4, "observation": 3},
        "码头工人": {"observation": 2, "combat": 2},
        "律师": {"insight": 5, "deception": 3},
        "医生": {"observation": 3, "willpower": 3},
        "教会职员": {"mysticism": 4, "ritual": 3, "willpower": 3},
        "教士": {"mysticism": 4, "ritual": 3, "willpower": 3},
        "外勤员工": {"investigation": 5, "observation": 4, "tracking": 4, "combat": 3},
    }
    for skill, bonus in occupation_bonuses.get(npc.occupation, {}).items():
        npc.skills[skill] = min(30, npc.skills[skill] + bonus)
    npc.work_days, npc.work_phases = build_work_schedule(idx, npc.work_scene, npc.occupation)
    return npc


__all__ = [
    "OCCUPATIONS", "WEEKDAYS", "build_work_schedule", "initialize_special_needs",
    "make_npc", "make_scenes",
]
