#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations
import argparse, json, os, random, urllib.request, uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

from simulation.actions.catalog import build_action_registry
from simulation.systems.desires import DesireEngine
from simulation.systems.intelligence import IntelligenceSystem
from simulation.narrative.illegal_ritual import IllegalRitualEngine
from simulation.narrative.consequence_chains import ConsequenceChainEngine
from simulation.domain.planning import LongTermGoal, TraceEvidence
from simulation.domain import entities as domain_entities
from simulation.cognition.contracts import build_plan_schema
from simulation.persistence.ledger import TraceLedger as PersistenceTraceLedger
from simulation.persistence.snapshot import atomic_write_json
from simulation.systems import population as population_system
from simulation.systems import relationships as relationship_system
from simulation.systems import economy as economy_system


# Canonical implementations live under simulation.domain and persistence.
Phase = domain_entities.Phase
PHASES = domain_entities.PHASES
EventLevel = domain_entities.EventLevel
NPCLayer = domain_entities.NPCLayer
GAME_EVENT_TYPES = domain_entities.GAME_EVENT_TYPES
Config = domain_entities.Config
TraceLedger = PersistenceTraceLedger
Scene = domain_entities.Scene
WorldObject = domain_entities.WorldObject
Memory = domain_entities.Memory
Relationship = domain_entities.Relationship
SocialInvitation = domain_entities.SocialInvitation
PhasePlan = domain_entities.PhasePlan
Commitment = domain_entities.Commitment
StateDelta = domain_entities.StateDelta
Observation = domain_entities.Observation
Report = domain_entities.Report
IncidentReport = domain_entities.IncidentReport
CaseFile = domain_entities.CaseFile
Faction = domain_entities.Faction
WorldConflict = domain_entities.WorldConflict
ResponseDrive = domain_entities.ResponseDrive
ActionCheckResult = domain_entities.ActionCheckResult
NPC = domain_entities.NPC
SimEvent = domain_entities.SimEvent
StoryThread = domain_entities.StoryThread
Commission = domain_entities.Commission


# Canonical population implementation lives under simulation.systems.
make_scenes = population_system.make_scenes
OCCUPATIONS = population_system.OCCUPATIONS
WEEKDAYS = population_system.WEEKDAYS
build_work_schedule = population_system.build_work_schedule
initialize_special_needs = population_system.initialize_special_needs
make_npc = population_system.make_npc


PLAN_SCHEMA = build_plan_schema(phase.value for phase in PHASES)


class OllamaClient:
    def __init__(self, base_url, model, ledger):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.ledger = ledger

    def available(self):
        try:
            with urllib.request.urlopen(self.base_url + "/api/tags", timeout=2) as resp:
                return resp.status == 200
        except Exception:
            return False

    def plan(self, context, day, npc_id):
        prompt = ("你是游戏NPC每日规划器。不能创造世界事实，只能根据已经发生的事实规划明天。"
                  "scene_id 必须来自 available_scenes。四个时段都要规划。"
                  "不要描述成功结果，只描述意图。")
        payload = {
            "model": self.model,
            "messages":[{"role":"system","content":prompt},
                        {"role":"user","content":json.dumps(context, ensure_ascii=False)}],
            "stream":False, "format":PLAN_SCHEMA, "options":{"temperature":0.6}
        }
        stem = f"day_{day:03d}_{npc_id}_{uuid.uuid4().hex[:6]}"
        (self.ledger.log_dir/"llm"/f"{stem}_request.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        req = urllib.request.Request(
            self.base_url + "/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type":"application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        (self.ledger.log_dir/"llm"/f"{stem}_response.json").write_text(
            json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        return json.loads(raw["message"]["content"])


class DeepSeekClient:
    def __init__(self, base_url, model, api_key, ledger):
        self.base_url=base_url.rstrip("/")
        self.model=model
        self.api_key=api_key
        self.ledger=ledger

    def available(self):
        return bool(self.api_key)

    def plan(self,context,day,npc_id):
        example={
            "primary_goal":"处理当前最重要且自己确实知道的问题",
            "plans":{
                phase.value:{"scene_id":"home_quarter","intent":"回家休息",
                             "target_id":None,"priority":50,"behavior":"REST",
                             "fallback_scene_id":"home_quarter"}
                for phase in PHASES
            },
            "strategy_steps":[{
                "phase":"afternoon","action_id":"INVESTIGATE_LOCATION",
                "scene_id":"warehouse_3","target_id":None,
                "condition":"always","intent":"调查已知异常地点"
            }]
        }
        prompt=("你是游戏 NPC 每日规划器。只能根据输入中该 NPC 的记忆、观察、知识、关系、"
                "状态、职责和合法候选行为规划明天；不得创造世界事实，不得假定行动成功。"
                "scene_id 必须来自 available_scenes，behavior 必须来自 allowed_behaviors。"
                "可选 strategy_steps 最多 3 步，只能组合 allowed_behaviors 中的行为，"
                "condition 只能为 always、if_exposed、if_official_has_evidence、if_low_energy。"
                "必须只输出一个合法 JSON 对象，不要输出解释或 Markdown。JSON 格式示例："
                +json.dumps(example,ensure_ascii=False))
        payload={
            "model":self.model,
            "messages":[{"role":"system","content":prompt},
                        {"role":"user","content":json.dumps(context,ensure_ascii=False)}],
            "stream":False,
            "response_format":{"type":"json_object"},
            "thinking":{"type":"disabled"},
            "max_tokens":800,
        }
        stem=f"day_{day:03d}_{npc_id}_deepseek_{uuid.uuid4().hex[:6]}"
        (self.ledger.log_dir/"llm"/f"{stem}_request.json").write_text(
            json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
        req=urllib.request.Request(
            self.base_url+"/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type":"application/json",
                     "Authorization":f"Bearer {self.api_key}"},
            method="POST")
        with urllib.request.urlopen(req,timeout=300) as resp:
            raw=json.loads(resp.read().decode("utf-8"))
        (self.ledger.log_dir/"llm"/f"{stem}_response.json").write_text(
            json.dumps(raw,ensure_ascii=False,indent=2),encoding="utf-8")
        content=raw["choices"][0]["message"]["content"]
        if not content:
            raise ValueError("DeepSeek returned empty JSON content")
        return json.loads(content)


# Canonical relationship-network implementation lives under simulation.systems.
add_mutual_relationship = relationship_system.add_mutual_relationship
build_initial_relationship_network = relationship_system.build_initial_relationship_network


class World:
    def __init__(self, cfg):
        self.cfg = cfg
        self.rng = random.Random(cfg.seed)
        self.day = 1
        self.phase = Phase.MORNING
        self.scenes = make_scenes()
        self.npcs = {}
        self.objects = {}
        self.events_by_day = defaultdict(list)
        self.story_threads = {}
        self.commissions = []
        self.observations = {}
        self.reports = {}
        self.incident_reports = {}
        self.cases = {}
        self.long_term_goals = {}
        self.state_deltas = []
        self.invitations = {}
        self.factions = {
            "nightwatchers_tingen":Faction("nightwatchers_tingen","廷根值夜者","official","blackthorn_security"),
            "evernight_church":Faction("evernight_church","黑夜女神教会","official","evernight_church"),
            "aurora_order_tingen":Faction("aurora_order_tingen","廷根极光会隐秘支部","hostile","underground_market"),
            "secret_cult_tingen":Faction("secret_cult_tingen","廷根隐秘邪教团体","hostile","warehouse_3"),
        }
        self.world_conflicts = {
            "conflict:tingen_occult_war":WorldConflict(
                "conflict:tingen_occult_war","廷根非凡秩序争夺",
                ["nightwatchers_tingen","evernight_church"],
                ["aurora_order_tingen","secret_cult_tingen"])
        }
        self.processed_response_event_ids=set()
        self.processed_incident_event_ids=set()
        self.desire_engine=DesireEngine()
        self.intelligence=IntelligenceSystem()
        self.action_registry=build_action_registry()
        self.ritual_engine=IllegalRitualEngine()
        self.followup_engine=ConsequenceChainEngine()
        self.log_dir = Path(cfg.log_dir)
        self.ledger = TraceLedger(self.log_dir)
        self.ollama = OllamaClient(cfg.ollama_url, cfg.ollama_model, self.ledger)
        self.deepseek = DeepSeekClient(cfg.deepseek_url,cfg.deepseek_model,
                                       cfg.deepseek_api_key,self.ledger)
        self.player_scene = "evernight_church"
        total = cfg.core_npcs + cfg.simple_npcs
        for i in range(total):
            self.npcs[f"npc_{i:03d}"] = make_npc(i, "core" if i < cfg.core_npcs else "simple", self.rng)

        for npc in self.npcs.values():
            self.scenes[npc.home_scene]=Scene(
                npc.home_scene,f"{npc.name}号住所",["private_home","residential"],
                8,35,100,["rest","family"])
        build_initial_relationship_network(self.npcs,self.rng)

        if "npc_000" in self.npcs:
            self.npcs["npc_000"].goals.append("调查东码头最近的失踪与异常传闻")
        if "npc_001" in self.npcs:
            self.npcs["npc_001"].occupation = "外勤员工"
            self.npcs["npc_001"].work_scene = "blackthorn_security"
            self.npcs["npc_001"].organization = "nightwatchers_tingen"
            self.npcs["npc_001"].layer = NPCLayer.OFFICIAL_BEYONDER.value
            self.npcs["npc_001"].sequence_pathway = "不眠者"
            self.npcs["npc_001"].sequence_rank = 8
            self.npcs["npc_001"].faction_ids = ["nightwatchers_tingen"]
            self.npcs["npc_001"].duties = ["响应非凡异常","保护普通人","调查邪教组织","收容危险物品"]
            self.npcs["npc_001"].goals.append("维持廷根的非凡秩序并处理异常事件")
        if "npc_002" in self.npcs:
            self.npcs["npc_002"].occupation = "仓库管理员"
            self.npcs["npc_002"].work_scene = "warehouse_3"
            self.npcs["npc_002"].organization = "aurora_cell"
            self.npcs["npc_002"].layer = NPCLayer.HOSTILE_BEYONDER.value
            self.npcs["npc_002"].sequence_pathway = "秘祈人"
            self.npcs["npc_002"].sequence_rank = 8
            self.npcs["npc_002"].organization = "aurora_order_tingen"
            self.npcs["npc_002"].faction_ids = ["aurora_order_tingen"]
            self.npcs["npc_002"].duties = ["掩盖非凡痕迹","保护组织成员","避开值夜者调查"]
            self.npcs["npc_002"].goals.append("掩盖三号仓库的违禁货物出入记录")

        for npc in self.npcs.values():
            idx = int(npc.id.split("_")[-1])
            npc.work_days, npc.work_phases = build_work_schedule(
                idx, npc.work_scene, npc.occupation)
            initialize_special_needs(npc)

        for npc in self.npcs.values():
            for faction_id in npc.faction_ids:
                if faction_id in self.factions:
                    self.factions[faction_id].member_ids.append(npc.id)

        operation = self.ritual_engine.create_operation(
            faction_id="aurora_order_tingen",leader_id="npc_002",
            participant_ids=["npc_002"],scene_id="warehouse_3",
            scheduled_day=6,scheduled_phase="late_night")
        goal = LongTermGoal(
            id=f"goal:{operation.id}", owner_id=operation.leader_id,
            goal_type="perform_illegal_ritual",
            description="在廷根秘密完成非法仪式并避免官方阻止",
            priority=95, created_day=1, deadline_day=operation.scheduled_day,
            linked_plan_id=operation.id)
        self.long_term_goals[goal.id] = goal
        operation.linked_goal_id = goal.id
        if operation.leader_id in self.npcs:
            self.npcs[operation.leader_id].long_term_goal_ids.append(goal.id)

        self.objects["object:warehouse_contraband_ledger_page"] = WorldObject(
            id="object:warehouse_contraband_ledger_page",
            name="违禁货物出入账页",
            object_type="document",
            scene_id="warehouse_3",
            owner_id="aurora_order_tingen",
            tags=["evidence", "contraband", "warehouse_3"],
            affordances=["hide", "search", "take", "read", "give"],
            custodian_id="npc_002",
            knowledge_id="knowledge:warehouse_contraband_routes",
        )
        self.objects["object:east_dock_shipping_register"] = WorldObject(
            id="object:east_dock_shipping_register",
            name="东码头公开货运登记簿",
            object_type="document",
            scene_id="east_dock",
            owner_id="dock_authority",
            tags=["shipping", "public_record", "east_dock"],
            affordances=["search", "read"],
            knowledge_id="knowledge:warehouse_3_unregistered_shipments",
        )
        seed_objects = [
            ("market_food_crate","市场食物箱","food","market",["take","buy","eat"]),
            ("tavern_wine_bottle","酒瓶","drink","tavern",["take","buy","drink","give"]),
            ("hospital_medicine","止痛药","medicine","hospital",["take","buy","use","give"]),
            ("warehouse_key","三号仓库钥匙","key","warehouse_3",["take","give","use"]),
            ("dock_rope","码头绳索","tool","east_dock",["take","use","give"]),
            ("factory_hammer","工厂铁锤","tool","factory",["take","use"]),
            ("police_report_form","警察报告表","document","police_station",["read","write","take"]),
            ("evidence_bag","证物袋","container","police_station",["take","store","give"]),
            ("newspaper_camera","记者相机","tool","newspaper",["take","use"]),
            ("church_candle","教堂蜡烛","religious","evernight_church",["take","buy","use"]),
            ("church_community_meal","教会救济餐","food","evernight_church",["give","eat"]),
            ("personal_letter","未寄出的私人信件","letter","home_quarter",["take","read","hide","give"]),
            ("market_cashbox","市场钱箱","money","market",["open","take","lock"]),
            ("rusted_knife","生锈的小刀","weapon","red_moon_street",["take","use","hide"]),
            ("occult_powder","灰白色仪式粉末","contraband","underground_market",["take","buy","use","hide"]),
            ("hospital_patient_chart","病历夹","document","hospital",["read","write","hide"]),
        ]
        for oid,name,kind,scene_id,affordances in seed_objects:
            full_id=f"object:{oid}"
            self.objects[full_id]=WorldObject(full_id,name,kind,scene_id,
                                               tags=[kind,scene_id],affordances=affordances)
        self.objects["object:market_food_crate"].quantity=100
        self.objects["object:market_food_crate"].value=3
        self.objects["object:tavern_wine_bottle"].quantity=30
        self.objects["object:tavern_wine_bottle"].value=5
        self.objects["object:hospital_medicine"].quantity=25
        self.objects["object:hospital_medicine"].value=12
        self.objects["object:church_community_meal"].quantity=60
        self.objects["object:rusted_knife"].legality="restricted"
        self.objects["object:occult_powder"].legality="contraband"

        self.scheduled_events = [{
            "day":2, "phase":"afternoon", "scene_id":"east_dock",
            "message":"警方开始对东码头进行临时检查。",
            "severity":5, "tags":["law","investigation","dock"]
        },{
            "day":1,"phase":"late_night","scene_id":"warehouse_3",
            "message":"夜间巡逻者在三号仓库外发现残缺仪式纹路和异常灵性波动。",
            "severity":8,"tags":["occult","ritual","hostile_beyonder","tingen"]
        }]


BACKGROUND_EVENT_TYPES = {
    "NPC_MOVED", "CASUAL_MEETING", "INFORMATION_EXCHANGE", "SMALL_TALK",
    "WORK_COMPLETED", "REST_COMPLETED", "SHOP_COMPLETED",
}

NARRATIVE_EVENT_TYPES = {
    "SHIPPING_RECORD_ANOMALY_FOUND", "EVIDENCE_DISCOVERED",
    "SUSPICIOUS_ENCOUNTER", "EVIDENCE_CONFRONTATION", "CONFRONTATION", "TAVERN_FIGHT",
    "OCCULT_DISTURBANCE", "MYSTERIOUS_AWAKENING", "SCHEDULED_EVENT",
}


def default_event_level(event_type):
    if event_type in BACKGROUND_EVENT_TYPES:
        return EventLevel.BACKGROUND.value
    if event_type in NARRATIVE_EVENT_TYPES:
        return EventLevel.NARRATIVE.value
    return EventLevel.SIGNIFICANT.value


def make_event(world, event_type, description, actor_ids, scene_id,
               severity=2, conflict=0, danger=0, secret=0, emotion=0,
               tags=None, trace_id=None, parent_id=None, level=None,
               object_ids=None, knowledge_ids=None, organization_ids=None,
               conflict_ids=None):
    level = level or default_event_level(event_type)
    tags=list(tags or [])
    conflict_ids=list(conflict_ids or [])
    if set(tags)&{"occult","ritual","hostile_beyonder","sealed_artifact","awakening"}:
        if "conflict:tingen_occult_war" not in conflict_ids:
            conflict_ids.append("conflict:tingen_occult_war")
    anchors = {
        "level": level,
        "object_ids": object_ids or [],
        "knowledge_ids": knowledge_ids or [],
        "organization_ids": organization_ids or [],
        "conflict_ids": conflict_ids,
    }
    trace = world.ledger.emit(
        day=world.day, phase=world.phase.value, system="simulation",
        event_type=event_type, message=description, actor_ids=actor_ids,
        scene_id=scene_id,
        payload={"severity":severity,"conflict":conflict,"danger":danger,"secret":secret,
                 "emotion":emotion,"tags":tags, **anchors},
        trace_id=trace_id, parent_id=parent_id
    )
    e = SimEvent(trace["event_id"], trace["trace_id"], world.day, world.phase.value,
                 event_type, scene_id, actor_ids, description, severity, conflict,
                 danger, secret, emotion, tags, parent_id, level,
                 object_ids or [], knowledge_ids or [], organization_ids or [],
                 conflict_ids)
    world.events_by_day[world.day].append(e)
    for conflict_id in conflict_ids:
        conflict=world.world_conflicts.get(conflict_id)
        if conflict:
            conflict.event_ids.append(e.event_id)
            conflict.pressure=min(100,conflict.pressure+max(1,int(narrative_score(e)/20)))
            if conflict.pressure>=75: conflict.stage="open_conflict"
            elif conflict.pressure>=50: conflict.stage="escalating"
    return e


def change_state(world,npc,state_name,delta,reason,source_event=None):
    old=int(npc.states.get(state_name,50))
    new=max(0,min(100,old+int(delta)))
    if new==old:
        return None
    npc.states[state_name]=new
    record=StateDelta(npc.id,state_name,old,new-old,new,
                      source_event.event_id if source_event else None,reason)
    world.state_deltas.append(record)
    world.ledger.emit(day=world.day,phase=world.phase.value,system="state_system",
                      event_type="STATE_CHANGED",
                      message=f"{npc.name} 的 {state_name} 从 {old} 变为 {new}：{reason}",
                      actor_ids=[npc.id],scene_id=npc.current_scene,payload=asdict(record),
                      trace_id=source_event.trace_id if source_event else None,
                      parent_id=source_event.event_id if source_event else None)
    return record


def create_observations(world,event,occupants):
    if event.severity<3:
        return []
    observations=[]
    for witness in occupants:
        if not witness.alive:
            continue
        if event.secret>=6 and witness.id in event.actor_ids:
            continue
        perceive=max(10,min(95,witness.states.get("alertness",50)+event.severity*5
                            -world.scenes[event.scene_id].privacy//2))
        if world.rng.uniform(0,100)>=perceive:
            continue
        accuracy=max(0.35,min(0.95,0.45+witness.states.get("alertness",50)/200))
        obs=Observation(f"obs_{uuid.uuid4().hex[:10]}",witness.id,event.event_id,
                        event.scene_id,event.description,accuracy,event.severity,
                        list(event.conflict_ids),list(event.object_ids))
        world.observations[obs.id]=obs
        observations.append(obs)
        world.intelligence.create(
            subject_id=event.actor_ids[0] if event.actor_ids else "unknown_actor",
            predicate="involved_in_event",object_id=event.event_id,
            day=world.day,phase=world.phase.value,source_type="witness",
            source_id=witness.id,confidence=accuracy,secrecy=event.secret,
            known_by=[witness.id],evidence_ids=event.object_ids,summary=event.description)
        change_state(world,witness,"fear",event.danger*2+event.conflict,
                     f"目击：{event.description}",event)
        change_state(world,witness,"stress",event.severity+event.emotion//2,
                     f"目击：{event.description}",event)
        world.ledger.emit(day=world.day,phase=world.phase.value,system="perception_system",
                          event_type="EVENT_WITNESSED",
                          message=f"{witness.name} 目击到：{event.description}",
                          actor_ids=[witness.id],scene_id=event.scene_id,
                          payload=asdict(obs),trace_id=event.trace_id,parent_id=event.event_id)
    return observations


def pending_report_observations(world,npc):
    return sorted((o for o in world.observations.values()
                   if o.observer_id==npc.id and not o.reported and o.severity>=4),
                  key=lambda o:o.severity,reverse=True)


def active_case_for_officer(world,npc):
    active=[case for case in world.cases.values()
            if case.status not in ("resolved","failed","closed")
            and npc.id in case.assigned_officer_ids]
    stage_rank={"arrest_authorized":5,"fugitive":5,"operation_planned":4,
                "surveillance":3,"suspect_identified":2,"investigating":1}
    return max(active,key=lambda case:(stage_rank.get(case.stage,0),case.priority,
                                       case.last_progress_day),default=None)


def operation_id_from_evidence(world, evidence_ids):
    for evidence_id in evidence_ids:
        trace=world.ritual_engine.traces.get(evidence_id)
        operation_id=trace.payload.get("operation_id") if trace else None
        if operation_id in world.ritual_engine.operations:
            return operation_id
    return None


def add_long_term_goal(world, owner_id, goal_type, description, priority,
                       *, linked_plan_id=None, linked_case_id=None):
    goal=LongTermGoal(
        id=f"goal:{goal_type}:{uuid.uuid4().hex[:10]}",owner_id=owner_id,
        goal_type=goal_type,description=description,priority=priority,
        created_day=world.day,linked_plan_id=linked_plan_id,
        linked_case_id=linked_case_id)
    world.long_term_goals[goal.id]=goal
    owner=world.npcs.get(owner_id)
    if owner and goal.id not in owner.long_term_goal_ids:
        owner.long_term_goal_ids.append(goal.id)
    return goal


def create_followup_goal(world, owner_id, goal_type, description, priority,
                         *, scene_id, target_id=None, linked_case_id=None):
    goal=add_long_term_goal(world,owner_id,goal_type,description,priority,
                            linked_case_id=linked_case_id)
    plan=world.followup_engine.create(
        template_id=goal_type,goal_id=goal.id,owner_id=owner_id,
        scene_id=scene_id,target_id=target_id,created_day=world.day)
    goal.linked_plan_id=plan.id
    return goal


def spawn_story_character(world, role, faction_id, reason, *, official=False):
    idx=max([int(npc_id.split("_")[-1]) for npc_id in world.npcs]+[-1])+1
    npc=make_npc(idx,"core",world.rng)
    npc.name=f"Adrian-{idx}" if not official else f"Catherine-{idx}"
    npc.current_scene="railway_station"
    npc.home_scene="home_quarter"
    npc.faction_ids=[faction_id]
    npc.organization=faction_id
    npc.sequence_rank=7
    if official:
        npc.occupation="值夜者增援"
        npc.layer=NPCLayer.OFFICIAL_BEYONDER.value
        npc.sequence_pathway="不眠者"
        npc.work_scene="blackthorn_security"
        npc.duties=["支援廷根值夜者","处理高危非凡案件"]
    else:
        npc.occupation="旅行商人"
        npc.layer=NPCLayer.HOSTILE_BEYONDER.value
        npc.sequence_pathway="秘祈人"
        npc.work_scene="underground_market"
        npc.duties=["接收仪式成果","保护组织秘密","处理暴露成员"]
    npc.goals=[reason]
    world.npcs[npc.id]=npc
    faction=world.factions.get(faction_id)
    if faction and npc.id not in faction.member_ids:
        faction.member_ids.append(npc.id)
    return npc


def set_disposition(npc,status,day,cause_event_id=None):
    npc.disposition_status=status
    npc.disposition_since_day=day
    npc.disposition_cause_event_id=cause_event_id
    if status=="dead":
        npc.alive=False


def npc_can_act(npc):
    return npc.alive and npc.disposition_status not in ("dead","missing","arrested","fled")


def health_band(npc):
    if npc.health <= 0:
        return "dead"
    if npc.health <= 15:
        return "critical"
    if npc.health <= 30:
        return "severe"
    if npc.health <= 60:
        return "injured"
    return "fit"


def health_action_modifier(npc):
    return {"critical":-35,"severe":-20,"injured":-8}.get(health_band(npc),0)


def can_perform_while_injured(npc,behavior):
    safe={"SEEK_HELP","REST","TAKE_SHORT_REST","PRAY","REQUEST_AID"}
    if health_band(npc)=="critical":
        return behavior in safe
    if health_band(npc)=="severe":
        return behavior not in {"WORK","DO_REGULAR_WORK","SEEK_TEMPORARY_WORK",
                                "COMMIT_ASSAULT","FOLLOW_TARGET","STOP_RITUAL",
                                "PATROL_SCENE","POLICE_INVESTIGATE","ARREST_SUSPECT"}
    return True


def resolve_operation_consequences(world,operation):
    if operation.consequence_resolved or operation.status not in ("completed","failed"):
        return []
    events=[]
    leader=world.npcs.get(operation.leader_id)
    scene=world.scenes.get(operation.scene_id)
    if operation.status=="completed":
        operation.outcome_type="ritual_succeeded"
        victim=world.npcs.get(operation.target_id)
        if victim and victim.alive:
            event=make_event(world,"RITUAL_VICTIM_KILLED",
                f"{victim.name} 成为非法仪式的牺牲者并死亡。",
                [victim.id,operation.leader_id],operation.scene_id,
                severity=10,conflict=10,danger=10,secret=8,emotion=10,
                tags=["death","ritual","consequence"],
                organization_ids=[operation.owner_faction_id],
                conflict_ids=["conflict:tingen_occult_war"])
            set_disposition(victim,"dead",world.day,event.event_id); events.append(event)
        if scene:
            scene.occult_contamination=min(100,scene.occult_contamination+70)
            events.append(make_event(world,"SCENE_OCCULT_CONTAMINATED",
                f"{scene.name} 因成功仪式形成持续灵性污染，污染度达到 {scene.occult_contamination}。",
                [operation.leader_id],scene.id,severity=9,conflict=8,danger=9,
                secret=7,emotion=7,tags=["occult","contamination","consequence"],
                conflict_ids=["conflict:tingen_occult_war"]))
            result_object=WorldObject(
                id=f"object:ritual_result:{operation.id}",name="凝固的仪式灵性结晶",
                object_type="occult_artifact",scene_id=scene.id,
                owner_id=operation.owner_faction_id,legality="contraband",
                tags=["ritual_result","occult","evidence"],
                affordances=["take","seal","destroy"],hidden=True,concealment=65)
            world.objects[result_object.id]=result_object
        if leader:
            event=make_event(world,"RITUAL_LEADER_ESCAPED",
                f"{leader.name} 在完成仪式后逃离廷根，官方转入追捕。",
                [leader.id],operation.scene_id,severity=9,conflict=9,danger=7,
                secret=6,emotion=7,tags=["escape","fugitive","consequence"],
                organization_ids=[operation.owner_faction_id],
                conflict_ids=["conflict:tingen_occult_war"])
            set_disposition(leader,"fled",world.day,event.event_id); events.append(event)
        envoy=spawn_story_character(world,"occult_emissary",operation.owner_faction_id,
                                     "接收仪式成果并评估廷根支部",official=False)
        operation.spawned_character_ids.append(envoy.id)
        create_followup_goal(world,envoy.id,"collect_ritual_result",
                             "接收 Thomas 留下的仪式成果并处理暴露痕迹",92,
                             scene_id=operation.scene_id,target_id=operation.target_id)
        events.append(make_event(world,"STORY_CHARACTER_ARRIVED",
            f"{envoy.name} 以旅行商人身份抵达廷根；其真实任务是接收仪式成果。",
            [envoy.id],"railway_station",severity=8,conflict=8,danger=7,
            secret=10,emotion=6,tags=["new_character","hostile_beyonder","consequence"],
            organization_ids=[operation.owner_faction_id],
            conflict_ids=["conflict:tingen_occult_war"]))
        officials=[npc for npc in world.npcs.values() if npc_can_act(npc) and is_official_responder(npc)]
        if officials:
            owner=max(officials,key=lambda npc:npc.skills.get("investigation",0))
            create_followup_goal(world,owner.id,"hunt_ritual_leader",
                                 f"追捕逃离廷根的 {leader.name if leader else operation.leader_id}",100,
                                 scene_id="railway_station",target_id=operation.leader_id)
            create_followup_goal(world,owner.id,"cleanse_occult_scene",
                                 f"封锁并净化 {scene.name if scene else operation.scene_id}",96,
                                 scene_id=operation.scene_id)
    elif operation.outcome_type=="official_victory":
        if leader:
            event=make_event(world,"HOSTILE_LEADER_ARRESTED",
                f"{leader.name} 因参与非法仪式被值夜者逮捕并关押。",
                [leader.id],"blackthorn_security",severity=10,conflict=10,danger=8,
                secret=5,emotion=9,tags=["arrest","official_victory","consequence"],
                organization_ids=[operation.owner_faction_id],
                conflict_ids=["conflict:tingen_occult_war"])
            leader.current_scene="blackthorn_security"
            set_disposition(leader,"arrested",world.day,event.event_id); events.append(event)
        rescuer=spawn_story_character(world,"hostile_rescuer",operation.owner_faction_id,
                                      "营救被捕成员并销毁官方证据",official=False)
        operation.spawned_character_ids.append(rescuer.id)
        create_followup_goal(world,rescuer.id,"rescue_arrested_member",
                             f"营救被捕的 {leader.name if leader else operation.leader_id}",95,
                             scene_id="blackthorn_security",target_id=operation.leader_id)
        events.append(make_event(world,"STORY_CHARACTER_ARRIVED",
            f"{rescuer.name} 因组织成员被捕而秘密进入廷根，准备实施营救。",
            [rescuer.id],"railway_station",severity=8,conflict=9,danger=8,
            secret=10,emotion=7,tags=["new_character","rescue_plan","consequence"],
            organization_ids=[operation.owner_faction_id],
            conflict_ids=["conflict:tingen_occult_war"]))
    operation.consequence_resolved=True
    operation.consequence_event_ids.extend(event.event_id for event in events)
    return events


def sync_long_term_goals(world, emit_events=True):
    """Keep durable goals in sync with deterministic operation/case state."""
    for operation in world.ritual_engine.operations.values():
        goal_id=operation.linked_goal_id or f"goal:{operation.id}"
        goal=world.long_term_goals.get(goal_id)
        if goal is None:
            goal=LongTermGoal(goal_id,operation.leader_id,"perform_illegal_ritual",
                              "在廷根秘密完成非法仪式并避免官方阻止",95,
                              created_day=world.day,deadline_day=operation.scheduled_day,
                              linked_plan_id=operation.id)
            world.long_term_goals[goal_id]=goal
            operation.linked_goal_id=goal_id
        owner=world.npcs.get(goal.owner_id)
        if owner and goal_id not in owner.long_term_goal_ids:
            owner.long_term_goal_ids.append(goal_id)
        old_progress,old_status=goal.progress,goal.status
        completed=sum(stage.status=="completed" for stage in operation.stages)
        goal.progress=round(100*completed/max(1,len(operation.stages)))
        goal.last_progress_day=max(goal.last_progress_day,operation.last_progress_day)
        if operation.status=="completed":
            goal.status="completed"; goal.outcome="仪式计划完成"
        elif operation.status=="failed":
            goal.status="failed"; goal.outcome="仪式被阻止或无法继续"
        else:
            goal.status="active"
        if emit_events and (goal.progress!=old_progress or goal.status!=old_status):
            make_event(world,"LONG_TERM_PLAN_PROGRESS",
                       f"{owner.name if owner else goal.owner_id} 的长期计划推进至 {goal.progress}%（{goal.status}）。",
                       [goal.owner_id],operation.scene_id,severity=8,conflict=8,danger=6,
                       secret=8,emotion=6,tags=["long_term_plan","operation",goal.status],
                       organization_ids=[operation.owner_faction_id],
                       conflict_ids=["conflict:tingen_occult_war"])

    for case in world.cases.values():
        if case.stage=="merged":
            continue
        if not case.linked_operation_id:
            case.linked_operation_id=operation_id_from_evidence(world,case.evidence_ids)
        if not case.linked_operation_id and case.suspect_ids:
            suspects=set(case.suspect_ids)
            related=next((operation for operation in world.ritual_engine.operations.values()
                          if suspects & set(operation.participant_ids+[operation.leader_id])),None)
            if related:
                case.linked_operation_id=related.id
    operation_cases=defaultdict(list)
    for case in world.cases.values():
        if case.linked_operation_id:
            operation_cases[case.linked_operation_id].append(case)
    for operation_id,cases in operation_cases.items():
        cases.sort(key=lambda item:item.id)
        canonical=next((item for item in cases if item.status=="resolved"),cases[0])
        for duplicate in cases:
            if duplicate is canonical or duplicate.status=="closed":
                continue
            canonical.assigned_officer_ids=sorted(set(canonical.assigned_officer_ids+duplicate.assigned_officer_ids))
            canonical.report_ids=sorted(set(canonical.report_ids+duplicate.report_ids))
            canonical.evidence_ids=sorted(set(canonical.evidence_ids+duplicate.evidence_ids))
            canonical.suspect_ids=sorted(set(canonical.suspect_ids+duplicate.suspect_ids))
            canonical.known_locations=sorted(set(canonical.known_locations+duplicate.known_locations))
            canonical.progress=max(canonical.progress,duplicate.progress)
            duplicate.status="closed"; duplicate.stage="merged"
            duplicate.closed_day=world.day
        operation=world.ritual_engine.operations.get(operation_id)
        if operation and operation.status=="failed" and operation.outcome_type=="official_victory":
            canonical.status="resolved"; canonical.stage="resolved"
            canonical.closed_day=canonical.closed_day or world.day
        elif operation and operation.status=="completed":
            canonical.status="failed"; canonical.stage="failed"
            canonical.closed_day=canonical.closed_day or world.day

    for case in world.cases.values():
        if case.stage=="merged":
            continue
        goal_id=case.linked_goal_id or f"goal:{case.id}"
        owner_id=case.assigned_officer_ids[0] if case.assigned_officer_ids else "nightwatchers_tingen"
        goal=world.long_term_goals.get(goal_id)
        if goal is None:
            occult_case=bool(case.linked_operation_id or
                             "conflict:tingen_occult_war" in case.conflict_ids)
            goal_type="investigate_and_stop_operation" if occult_case else "investigate_public_incident"
            description=(f"调查案件 {case.id}，确认威胁并阻止敌对非凡行动" if occult_case
                         else f"调查普通案件 {case.id}，确认责任人并恢复公共秩序")
            goal=LongTermGoal(goal_id,owner_id,goal_type,description,
                              case.priority,created_day=world.day,linked_case_id=case.id,
                              linked_plan_id=case.linked_operation_id)
            world.long_term_goals[goal_id]=goal
            case.linked_goal_id=goal_id
        elif case.linked_operation_id and not goal.linked_plan_id:
            goal.linked_plan_id=case.linked_operation_id
        for officer_id in case.assigned_officer_ids:
            officer=world.npcs.get(officer_id)
            if officer and goal_id not in officer.long_term_goal_ids:
                officer.long_term_goal_ids.append(goal_id)
        old_progress,old_status=goal.progress,goal.status
        stage_progress={"reported":10,"assessing":20,"investigating":40,
                        "suspect_identified":55,"surveillance":70,
                        "operation_planned":85,"intervention":90,
                        "resolved":100,"closed":100,"failed":100}
        goal.progress=max(goal.progress,stage_progress.get(case.stage,min(80,case.progress)))
        goal.last_progress_day=max(goal.last_progress_day,case.last_progress_day)
        if case.status in ("resolved","closed"):
            goal.status="completed"; goal.outcome="案件已解决"
        elif case.status=="failed":
            goal.status="failed"; goal.outcome="调查失败"
        else:
            goal.status="active"
        if emit_events and (goal.progress!=old_progress or goal.status!=old_status):
            make_event(world,"LONG_TERM_GOAL_PROGRESS",
                       f"官方对 {case.id} 的调查推进至 {goal.progress}%（阶段：{case.stage}）。",
                       case.assigned_officer_ids,case.known_locations[-1] if case.known_locations else None,
                       severity=7,conflict=7,danger=4,secret=5,emotion=5,
                       tags=["long_term_goal","case",case.stage],
                       conflict_ids=case.conflict_ids)


def advance_case_stage(world,case):
    old=case.stage
    if case.status in ("resolved","failed","closed"):
        case.stage=case.status
    elif case.stage in {"intervention","arrest_authorized","fugitive"}:
        return
    elif (case.suspect_ids and case.evidence_ids and case.progress>=85
          and "conflict:tingen_occult_war" not in case.conflict_ids):
        case.stage="arrest_authorized"
    elif case.suspect_ids and case.evidence_ids and case.progress>=80:
        repeated=max(case.exposure_counts.values(),default=0)
        case.stage="operation_planned" if repeated>=3 else "surveillance"
    elif case.suspect_ids:
        case.stage="suspect_identified"
    elif case.evidence_ids or case.progress>=40:
        case.stage="investigating"
    elif case.report_ids:
        case.stage="assessing"
    if case.stage!=old:
        case.last_progress_day=world.day
        case.stage_history.append(case.stage)
        world.ledger.emit(day=world.day,phase=world.phase.value,system="case_system",
                          event_type="CASE_STAGE_CHANGED",
                          message=f"案件 {case.id} 从 {old} 进入 {case.stage}阶段。",
                          actor_ids=case.assigned_officer_ids,
                          payload={"case_id":case.id,"old_stage":old,"new_stage":case.stage})
        if case.stage=="arrest_authorized":
            suspect=world.npcs.get(case.suspect_ids[0]) if case.suspect_ids else None
            make_event(world,"ARREST_AUTHORIZED",
                       f"案件 {case.id} 已形成证据链，警方获准逮捕 {suspect.name if suspect else '嫌疑人'}。",
                       case.assigned_officer_ids,suspect.current_scene if suspect else None,
                       severity=8,conflict=9,danger=7,emotion=7,
                       tags=["police","arrest","case_consequence"],object_ids=case.evidence_ids,
                       conflict_ids=case.conflict_ids)


def is_official_responder(npc):
    return npc.occupation=="警察" or npc.layer==NPCLayer.OFFICIAL_BEYONDER.value


def add_response_drive(npc,event,drive_type,scene_id,behavior,intent,priority,day):
    if any(d.active and d.source_event_id==event.event_id and d.drive_type==drive_type
           for d in npc.response_drives):
        return
    npc.response_drives.append(ResponseDrive(
        f"drive_{uuid.uuid4().hex[:10]}",event.event_id,drive_type,scene_id,
        behavior,intent,priority,"afternoon",day+2,True))


def generate_incident_response_drives(world,events):
    response_sources={"SCHEDULED_EVENT","OCCULT_DISTURBANCE","NIGHT_OCCULT_INCIDENT",
                      "RITUAL_TRACE_DISCOVERED","EVIDENCE_DISCOVERED"}
    for event in events:
        if event.event_id in world.processed_response_event_ids:
            continue
        world.processed_response_event_ids.add(event.event_id)
        is_occult=("conflict:tingen_occult_war" in event.conflict_ids
                   or bool(set(event.tags)&{"occult","ritual","hostile_beyonder","awakening"}))
        if not is_occult or not event.scene_id or event.event_type not in response_sources:
            continue
        officials=sorted((n for n in world.npcs.values() if npc_can_act(n) and is_official_responder(n)),
                         key=lambda n:(n.layer!=NPCLayer.OFFICIAL_BEYONDER.value,
                                       -n.states.get("alertness",50)))[:3]
        for npc in officials:
            add_response_drive(npc,event,"official_occult_response",event.scene_id,
                               "RESPOND_OCCULT_INCIDENT",
                               f"依职责调查异常事件：{event.description}",98,world.day)
        hostiles=sorted((n for n in world.npcs.values()
                         if npc_can_act(n) and n.layer==NPCLayer.HOSTILE_BEYONDER.value),
                        key=lambda n:-n.personality["risk"])[:2]
        for npc in hostiles:
            behavior=("HIDE_EVIDENCE" if event.scene_id=="warehouse_3"
                      and npc.id=="npc_002" else "COUNTER_INVESTIGATE")
            add_response_drive(npc,event,"hostile_coverup",event.scene_id,behavior,
                               f"确认官方是否注意到异常并保护组织秘密：{event.description}",94,world.day)
        wilds=sorted((n for n in world.npcs.values()
                      if npc_can_act(n) and n.layer==NPCLayer.WILD_BEYONDER.value),
                     key=lambda n:-n.personality["curiosity"])[:2]
        for npc in wilds:
            add_response_drive(npc,event,"wild_beyonder_interest",event.scene_id,
                               "INVESTIGATE_LOCATION",
                               f"谨慎观察可能影响自身安全的非凡异常：{event.description}",82,world.day)


def queue_incident_report(world,reporter,event,victim_ids,suspect_ids,witness_ids,source_label):
    if not npc_can_act(reporter) or reporter.id in suspect_ids:
        return None
    existing=next((report for report in world.incident_reports.values()
                   if report.source_event_id==event.event_id),None)
    if existing:
        if reporter.id!=existing.reporter_id and reporter.id not in existing.supplementary_reporter_ids:
            existing.supplementary_reporter_ids.append(reporter.id)
            existing.witness_ids=sorted(set(existing.witness_ids+witness_ids+[reporter.id]))
            world.ledger.emit(day=world.day,phase=world.phase.value,system="incident_reaction",
                              event_type="SUPPLEMENTARY_TESTIMONY_ATTACHED",
                              message=f"{reporter.name} 的证词并入报警 {existing.id}，不再创建重复报警。",
                              actor_ids=[reporter.id],scene_id=event.scene_id,
                              payload={"report_id":existing.id,"source_event_id":event.event_id},
                              trace_id=event.trace_id,parent_id=event.event_id)
        return existing
    scene=world.scenes[event.scene_id]
    account=(f"{source_label}。事发时间：Day {event.day} {event.phase}；"
             f"事发地点：{scene.name}（{scene.id}）；完整经过：{event.description}")
    report=IncidentReport(
        id=f"incident_report_{len(world.incident_reports)+1:04d}",reporter_id=reporter.id,
        source_event_id=event.event_id,incident_type=event.event_type,
        scene_id=scene.id,scene_name=scene.name,occurred_day=event.day,
        occurred_phase=event.phase,full_account=account,victim_ids=list(victim_ids),
        suspect_ids=list(suspect_ids),witness_ids=list(witness_ids))
    world.incident_reports[report.id]=report
    reporter.response_drives.append(ResponseDrive(
        f"drive_{uuid.uuid4().hex[:10]}",event.event_id,"file_incident_report",
        "police_station","FILE_INCIDENT_REPORT",
        f"前往警察局报警：{account}",97,"afternoon",world.day+2,True))
    world.ledger.emit(day=world.day,phase=world.phase.value,system="incident_reaction",
                      event_type="INCIDENT_REPORT_PREPARED",
                      message=f"{reporter.name} 决定就 {scene.name}发生的事件报警，并记录完整地点与经过。",
                      actor_ids=[reporter.id]+list(victim_ids),scene_id=scene.id,
                      payload=asdict(report),trace_id=event.trace_id,parent_id=event.event_id)
    return report


def generate_harm_and_report_reactions(world,events):
    reportable={"CRIME_COMMITTED","CRIME_ATTEMPT_EXPOSED","TAVERN_FIGHT",
                "PICKPOCKETED","HOME_BURGLARY"}
    for event in list(events):
        if event.event_id in world.processed_incident_event_ids or event.event_type not in reportable:
            continue
        world.processed_incident_event_ids.add(event.event_id)
        if not event.scene_id:
            continue
        if event.event_type in {"CRIME_COMMITTED","CRIME_ATTEMPT_EXPOSED","PICKPOCKETED"}:
            suspect_ids=event.actor_ids[:1]
            victim_ids=event.actor_ids[1:]
        elif event.event_type=="TAVERN_FIGHT":
            suspect_ids=list(event.actor_ids); victim_ids=list(event.actor_ids)
        else:
            suspect_ids=[]; victim_ids=list(event.actor_ids)
        witness_ids=[obs.observer_id for obs in world.observations.values()
                     if obs.source_event_id==event.event_id and obs.observer_id not in suspect_ids]
        reporters=[]
        for npc_id in victim_ids:
            npc=world.npcs.get(npc_id)
            if npc_can_act(npc) and npc.id not in suspect_ids and npc not in reporters:
                reporters.append(npc)
        for victim_id in victim_ids:
            victim=world.npcs.get(victim_id)
            if not victim:
                continue
            close=[]
            for friend_id,relation in victim.relationships.items():
                if set(relation.kinds)&{"朋友","爱人"}:
                    friend=world.npcs.get(friend_id)
                    if npc_can_act(friend) and friend.id not in suspect_ids:
                        close.append(friend)
            close.sort(key=lambda friend:-(friend.relationships[victim.id].trust+
                                           friend.relationships[victim.id].affection))
            for friend in close[:2]:
                if friend not in reporters:
                    reporters.append(friend)
                change_state(world,friend,"fear",18,
                             f"得知朋友或爱人 {victim.name} 遭遇袭击或死亡",event)
                change_state(world,friend,"stress",20,
                             f"担忧 {victim.name} 的安危",event)
        for npc_id in witness_ids:
            npc=world.npcs.get(npc_id)
            if npc_can_act(npc) and npc.id not in suspect_ids and npc not in reporters:
                reporters.append(npc)
        for reporter in reporters[:4]:
            source_label=("本人是受害者或现场目击者" if reporter.id in victim_ids+witness_ids
                          else "从受害者亲友与现场消息中得知事件")
            queue_incident_report(world,reporter,event,victim_ids,suspect_ids,witness_ids,source_label)


def submit_incident_report(world,reporter,scene):
    report=next((item for item in world.incident_reports.values()
                 if item.reporter_id==reporter.id and item.status=="draft"),None)
    if not report:
        return None
    related=next((item for item in world.incident_reports.values()
                  if item.source_event_id==report.source_event_id and item.case_id
                  and item.status in {"assigned","handled"}),None)
    officers=[npc for npc in world.npcs.values() if npc_can_act(npc) and npc.occupation=="警察"]
    if not officers:
        officers=[npc for npc in world.npcs.values() if npc_can_act(npc) and is_official_responder(npc)]
    if not officers:
        return make_event(world,"INCIDENT_REPORT_DELAYED",
                          f"{reporter.name} 已到警察局，但暂时没有警员接报。",
                          [reporter.id],scene.id,severity=2,tags=["report","delayed"])
    officer=(world.npcs.get(related.assigned_officer_ids[0]) if related and related.assigned_officer_ids
             else min(officers,key=lambda item:sum(item.id in case.assigned_officer_ids
                                                   for case in world.cases.values())))
    report.status="assigned"; report.assigned_officer_ids=[officer.id]
    case=world.cases.get(related.case_id) if related else None
    if case:
        case.report_ids=sorted(set(case.report_ids+[report.id]))
        case.suspect_ids=sorted(set(case.suspect_ids+report.suspect_ids))
        report.case_id=case.id
    else:
        case=CaseFile(f"case_{len(world.cases)+1:03d}",report.incident_type.lower(),"open",
                      [officer.id],[report.id],[],list(report.suspect_ids),[report.scene_id],
                      ["conflict:public_incident"],85,created_day=world.day)
        case.progress=15; case.stage="reported"
        world.cases[case.id]=case; report.case_id=case.id
        officer.response_drives.append(ResponseDrive(
            f"drive_{uuid.uuid4().hex[:10]}",report.id,"handle_incident_report",
            report.scene_id,"HANDLE_INCIDENT_REPORT",
            f"处理报警 {report.id}：{report.full_account}",100,"afternoon",world.day+3,True))
    event=make_event(world,"INCIDENT_REPORT_FILED",
        f"{reporter.name} 向警察 {officer.name} 报警。{report.full_account}",
        [reporter.id,officer.id]+report.victim_ids,"police_station",severity=6,
        conflict=6,emotion=7,tags=["report","police","incident"],
        conflict_ids=["conflict:public_incident"])
    return event


def handle_incident_report(world,officer,scene):
    report=next((item for item in world.incident_reports.values()
                 if officer.id in item.assigned_officer_ids and item.status=="assigned"
                 and item.scene_id==scene.id),None)
    if not report:
        return None
    case=world.cases.get(report.case_id)
    discovered=[]
    for trace in world.ritual_engine.discoverable_at(scene.id):
        if officer.id not in trace.discovered_by:
            trace.discovered_by.append(officer.id); discovered.append(trace.id)
    treated=[]; deaths=[]
    for victim_id in report.victim_ids:
        victim=world.npcs.get(victim_id)
        if not victim:
            continue
        if victim.disposition_status=="dead":
            deaths.append(victim.id)
        elif victim.health<100:
            victim.health=min(100,victim.health+10); treated.append(victim.id)
    if case:
        case.evidence_ids=sorted(set(case.evidence_ids+discovered))
        case.suspect_ids=sorted(set(case.suspect_ids+report.suspect_ids))
        case.progress=min(100,case.progress+35+10*len(discovered))
        if deaths and case.suspect_ids and case.evidence_ids:
            case.priority=100
            case.progress=max(case.progress,90)
        case.last_progress_day=world.day
        if not case.suspect_ids:
            case.status="resolved"; case.stage="resolved"; case.progress=100
            case.closed_day=world.day
        advance_case_stage(world,case)
    event=make_event(world,"INCIDENT_SCENE_HANDLED",
        f"警察 {officer.name} 根据报警 {report.id} 前往 {scene.name} 处理事件；"
        f"确认伤者 {len(treated)} 人、死亡 {len(deaths)} 人，收集证据 {len(discovered)} 份。"
        f" 原始报警经过：{report.full_account}",
        [officer.id]+report.victim_ids,scene.id,severity=8,conflict=7,danger=5,
        emotion=7,tags=["police","incident_response","scene_handled"],
        object_ids=discovered,conflict_ids=["conflict:public_incident"])
    for related in world.incident_reports.values():
        if related.case_id==report.case_id:
            related.status="handled"; related.handled_event_id=event.event_id
    return event


def file_police_report(world,npc,observation):
    officers=[n for n in world.npcs.values() if npc_can_act(n) and is_official_responder(n)
              and n.current_scene=="police_station"]
    if not officers:
        world.ledger.emit(day=world.day,phase=world.phase.value,system="report_system",
                          event_type="REPORT_DELAYED",
                          message=f"{npc.name} 到达警察局，但当时没有可接报的警察。",
                          actor_ids=[npc.id],scene_id="police_station",
                          payload={"observation_id":observation.id})
        return None
    existing_case=next((c for c in world.cases.values()
                        if c.status not in ("resolved","failed","closed")
                        and set(c.conflict_ids)&set(observation.conflict_ids)),None)
    if existing_case and len(existing_case.report_ids)>=4:
        observation.reported=True
        world.ledger.emit(day=world.day,phase=world.phase.value,system="report_system",
                          event_type="SUPPLEMENTARY_REPORT_NOTED",
                          message=f"警方记录了 {npc.name} 对已有案件 {existing_case.id} 的补充目击。",
                          actor_ids=[npc.id],scene_id="police_station",
                          payload={"case_id":existing_case.id,"observation_id":observation.id})
        return existing_case
    officer=min(officers,key=lambda n:len([c for c in world.cases.values()
                                          if n.id in c.assigned_officer_ids and c.status=="open"]))
    report=Report(f"report_{len(world.reports)+1:03d}",npc.id,officer.id,
                  observation.id,observation.source_event_id,observation.perceived_content,
                  observation.accuracy,world.day)
    world.reports[report.id]=report
    observation.reported=True
    for fact in world.intelligence.known_facts(npc.id):
        if fact.object_id==observation.source_event_id and officer.id not in fact.known_by:
            fact.known_by.append(officer.id)
    case=existing_case
    if case is None:
        case=CaseFile(f"case_{len(world.cases)+1:03d}","reported_anomaly","open",
                      [officer.id],[report.id],list(observation.object_ids),[],
                      [observation.scene_id],list(observation.conflict_ids),
                      min(100,40+observation.severity*6),created_day=world.day)
        world.cases[case.id]=case
    else:
        case.report_ids.append(report.id)
        case.evidence_ids=sorted(set(case.evidence_ids+observation.object_ids))
        case.known_locations=sorted(set(case.known_locations+[observation.scene_id]))
        case.priority=min(100,case.priority+5)
    self_record=npc.id==officer.id and is_official_responder(npc)
    e=make_event(world,"OFFICER_INCIDENT_RECORDED" if self_record else "WITNESS_REPORT_FILED",
                 (f"警察 {npc.name} 将自己的现场观察录入案件：{observation.perceived_content}"
                  if self_record else
                  f"{npc.name} 向警察 {officer.name} 报告：{observation.perceived_content}"),
                 [npc.id,officer.id],"police_station",severity=5,conflict=4,emotion=4,
                 tags=["report","police","witness"],object_ids=observation.object_ids,
                 conflict_ids=observation.conflict_ids,parent_id=observation.source_event_id)
    change_state(world,npc,"fear",-8,"已将目击情况报告警方",e)
    change_state(world,npc,"civic_duty",3,"履行了报告异常的公民责任",e)
    return case


def free_time_plan(world,npc,phase_name,planned_day):
    """Choose a public destination from needs first, entertainment second."""
    if npc.health<65 or npc.states.get("pain",0)>45:
        return PhasePlan("hospital","自由时间：前往医院治疗身体问题",priority=75,behavior="SEEK_HELP")
    if npc.states.get("satiety",70)<40:
        return PhasePlan("restaurant","自由时间：前往餐厅满足饮食需求",priority=72,behavior="SHOP")
    if npc.sanity<55 or npc.states.get("fear",0)>65:
        return PhasePlan("evernight_church","自由时间：前往教堂祈祷并寻求安定",priority=74,behavior="PRAY")
    if npc.wealth<12 or npc.needs.get("financial_pressure",0)>82:
        return PhasePlan("market","自由时间：寻找临时工作或便宜物资",priority=70,
                         behavior="SEEK_TEMPORARY_WORK")
    choices=[
        ("opera_house","自由时间：观看歌剧放松压力"),
        ("tavern","自由时间：在酒馆社交和打听消息"),
        ("divination_club","自由时间：参加占卜俱乐部活动"),
        ("restaurant","自由时间：在餐厅用餐和社交"),
        ("market","自由时间：逛市场和购买日用品"),
        ("university","自由时间：前往大学阅读或参加公开讲座"),
    ]
    idx=(int(npc.id.split("_")[-1])+planned_day+len(phase_name))%len(choices)
    scene_id,intent=choices[idx]
    behavior="SHOP" if scene_id=="market" else "SOCIALIZE"
    return PhasePlan(scene_id,intent,priority=48,behavior=behavior)


def rule_plan_for_npc(world, npc, planned_day=None):
    plans = {}
    schedule_day=world.day if planned_day is None else planned_day
    weekday=(schedule_day-1)%7
    if npc.layer==NPCLayer.ORDINARY.value:
        scene_name=world.scenes[npc.work_scene].name
        phase_names=[phase.value for phase in PHASES]
        working_today=weekday in npc.work_days
        working_phases=set(npc.work_phases if working_today else [])
        non_work=[phase for phase in phase_names if phase not in working_phases]
        if working_today:
            rest_phase="late_night" if "late_night" in non_work else non_work[-1]
            free_phases={phase for phase in non_work if phase!=rest_phase}
        else:
            rest_phase="late_night"
            free_phases={"afternoon","evening"}
        for phase_name in phase_names:
            if phase_name in working_phases:
                duty=professional_duty_plan(world,npc,Phase(phase_name))
                plans[phase_name]=duty or PhasePlan(
                    npc.work_scene,f"上班/上学：{npc.occupation}（隶属：{scene_name}）",
                    priority=80,behavior="WORK")
            elif phase_name in free_phases:
                plans[phase_name]=free_time_plan(world,npc,phase_name,schedule_day)
            else:
                plans[phase_name]=PhasePlan(npc.home_scene,"在自己的住所休息，不参与公共场景互动",
                                             priority=70,behavior="REST")
        return plans
    if npc.states.get("energy",70)<20:
        plans["morning"] = PhasePlan(npc.home_scene,"精力过低，继续休息",priority=90,behavior="REST")
    else:
        plans["morning"] = PhasePlan(npc.work_scene, f"进行{npc.occupation}的日常工作", priority=55, behavior="WORK")
    pending=pending_report_observations(world,npc)
    report_motivation=(npc.states.get("civic_duty",50)+npc.states.get("fear",0)
                       +(pending[0].severity*5 if pending else 0)-npc.personality["risk"]//3)
    police_case=active_case_for_officer(world,npc) if is_official_responder(npc) else None
    if pending and report_motivation>=65:
        plans["afternoon"] = PhasePlan("police_station","向警方报告自己目击的具体异常",
                                       priority=92,behavior="REPORT_TO_POLICE")
    elif police_case:
        if police_case.stage in ("suspect_identified","surveillance") and police_case.suspect_ids:
            suspect=world.npcs.get(police_case.suspect_ids[0])
            scene_id=suspect.current_scene if suspect else "police_station"
            plans["afternoon"] = PhasePlan(scene_id,f"监视案件 {police_case.id} 的嫌疑人",
                                           suspect.id if suspect else None,96,"FOLLOW_TARGET")
        elif police_case.stage=="operation_planned":
            plans["afternoon"] = PhasePlan("blackthorn_security",
                                           f"为案件 {police_case.id} 制定干预与抓捕方案",
                                           priority=100,behavior="PLAN_INTERVENTION")
        else:
            scene_id=police_case.known_locations[-1] if police_case.known_locations else "police_station"
            plans["afternoon"] = PhasePlan(scene_id,f"处理案件 {police_case.id} 的现场调查",
                                           priority=94,behavior="POLICE_INVESTIGATE")
    elif npc.states.get("satiety",70)<20 and npc.wealth>3:
        plans["afternoon"] = PhasePlan("market","饥饿已经影响行动，购买食物",
                                       priority=88,behavior="SHOP")
    elif npc.states.get("satiety",70)<20:
        plans["afternoon"] = PhasePlan("evernight_church","没有足够的钱购买食物，寻求教会救济",
                                       priority=91,behavior="SEEK_HELP")
    elif npc.states.get("energy",70)<18:
        plans["afternoon"] = PhasePlan(npc.home_scene,"精力耗尽，回家休息",
                                       priority=90,behavior="REST")
    elif npc.states.get("legal_risk",0)>=60:
        plans["afternoon"] = PhasePlan("underground_market","警方已把自己列为嫌疑人，离开公开活动区域",
                                       priority=98,behavior="FLEE")
    elif npc.wealth<10 and npc.states.get("satiety",70)<30:
        illegal=(npc.personality.get("morality",50)<35 and npc.personality.get("risk",50)>55)
        if illegal:
            targets=[other for other in world.npcs.values() if other.alive and other.id!=npc.id
                     and other.wealth>25]
            target=max(targets,key=lambda other:other.wealth,default=None)
            plans["afternoon"] = PhasePlan("market","因贫困和饥饿尝试偷窃财物",
                                           target.id if target else None,93,"STEAL_ITEM")
        elif npc.states.get("social_support",50)>=35:
            plans["afternoon"] = PhasePlan("evernight_church","向教会寻求食物和临时援助",
                                           priority=92,behavior="REQUEST_AID")
        else:
            plans["afternoon"] = PhasePlan("market","寻找一份临时工作换取收入",
                                           priority=90,behavior="SEEK_TEMPORARY_WORK")
    elif npc.wealth<20 or npc.needs["financial_pressure"]>75:
        plans["afternoon"] = PhasePlan(npc.work_scene,"经济压力促使自己额外工作",
                                       priority=78,behavior="DO_REGULAR_WORK")
    elif npc.states.get("stress",0)>75:
        plans["afternoon"] = PhasePlan(npc.home_scene,"压力过高，暂停其他行动休息",
                                       priority=89,behavior="TAKE_SHORT_REST")
    elif "调查东码头最近的失踪与异常传闻" in npc.goals:
        if "东码头货运登记簿显示多批未申报货物被送往三号仓库" in npc.knowledge:
            plans["afternoon"] = PhasePlan("warehouse_3","搜索三号仓库中的具体物证",priority=85,behavior="INVESTIGATE_LOCATION")
        else:
            plans["afternoon"] = PhasePlan("east_dock","调查东码头的异常与失踪传闻",priority=80,behavior="INVESTIGATE_LOCATION")
    elif "掩盖三号仓库的违禁货物出入记录" in npc.goals:
        plans["afternoon"] = PhasePlan("warehouse_3","藏匿三号仓库的违禁货物账页",priority=80,behavior="HIDE_EVIDENCE")
    else:
        plans["afternoon"] = PhasePlan(
            npc.work_scene if npc.needs["financial_pressure"]>55 else "market",
            "继续工作或处理个人事务", priority=50,
            behavior="WORK" if npc.needs["financial_pressure"]>55 else "SHOP"
        )
    plans["evening"] = PhasePlan("tavern" if npc.personality["social"]>45 else "home_quarter",
                                 "社交、休息或打听消息", priority=40, behavior="SOCIALIZE")
    plans["late_night"] = PhasePlan("home_quarter","回家休息",priority=70,behavior="REST")
    return plans


def professional_duty_plan(world,npc,phase):
    weekday=(world.day-1)%7
    if weekday not in npc.work_days or phase.value not in npc.work_phases:
        return None
    if npc.occupation=="警察":
        case=active_case_for_officer(world,npc)
        if case:
            if case.stage in {"arrest_authorized","fugitive"} and case.suspect_ids:
                suspect=world.npcs.get(case.suspect_ids[0])
                if suspect and npc_can_act(suspect):
                    return PhasePlan(suspect.current_scene,f"执行案件 {case.id} 的逮捕令",
                                     suspect.id,108,"ARREST_SUSPECT",npc.home_scene)
            scene_id=case.known_locations[-1] if case.known_locations else "police_station"
            return PhasePlan(scene_id,f"上班处理已分配案件 {case.id}",None,91,
                             "POLICE_INVESTIGATE",npc.home_scene)
        patrols=["market","east_dock","tavern","red_moon_street","opera_house"]
        scene_id=patrols[(world.day+int(npc.id[-3:]))%len(patrols)]
        return PhasePlan(scene_id,"警察当班巡逻并接收报警",None,86,"PATROL_SCENE",npc.home_scene)
    if npc.layer==NPCLayer.OFFICIAL_BEYONDER.value:
        case=active_case_for_officer(world,npc)
        if case and case.stage in {"arrest_authorized","fugitive"} and case.suspect_ids:
            suspect=world.npcs.get(case.suspect_ids[0])
            if suspect and npc_can_act(suspect):
                return PhasePlan(suspect.current_scene,f"执行案件 {case.id} 的非凡逮捕行动",
                                 suspect.id,109,"ARREST_SUSPECT",npc.home_scene)
        if case and "conflict:tingen_occult_war" in case.conflict_ids:
            scene_id=case.known_locations[-1] if case.known_locations else "blackthorn_security"
            return PhasePlan(scene_id,f"值夜者当班处理非凡案件 {case.id}",None,92,
                             "POLICE_INVESTIGATE",npc.home_scene)
        patrols=["blackthorn_security","evernight_church","east_dock","underground_market"]
        scene_id=patrols[(world.day+int(npc.id[-3:]))%len(patrols)]
        return PhasePlan(scene_id,"值夜者当班巡查非凡异常",None,88,"PATROL_SCENE",npc.home_scene)
    return None


def special_need_plan(world,npc,phase):
    """Turn accumulated role/pathway needs into a concrete high-priority action."""
    needs=npc.special_needs
    phase_name=phase.value
    if "crime_control" in needs and needs["crime_control"]<=30 and phase_name in {"evening","late_night"}:
        mode=(world.day+int(npc.id[-3:]))%3
        if mode==0:
            targets=[other for other in world.npcs.values() if npc_can_act(other)
                     and other.id!=npc.id and other.wealth>20]
            target=max(targets,key=lambda item:item.wealth,default=None)
            return PhasePlan(target.home_scene if target else "market","犯罪需求：尝试入室盗窃",
                             target.id if target else None,93,"COMMIT_BURGLARY",npc.home_scene)
        if mode==1:
            return PhasePlan("market","犯罪需求：在人群中尝试扒窃",None,91,
                             "COMMIT_PICKPOCKET",npc.home_scene)
        return PhasePlan("tavern","犯罪需求：寻找目标实施暴力勒索",None,90,
                         "COMMIT_ASSAULT",npc.home_scene)
    if "ritual_stability" in needs and needs["ritual_stability"]<=30 and phase_name in {"evening","late_night"}:
        legal=npc.layer==NPCLayer.OFFICIAL_BEYONDER.value or npc.states.get("legal_risk",0)>55
        return PhasePlan("evernight_church" if legal else "underground_market",
                         "仪式需求：举行受监管的合法仪式" if legal else "仪式需求：秘密举行非法仪式",
                         None,92,"PERFORM_LEGAL_RITUAL" if legal else "PERFORM_INDEPENDENT_RITUAL",
                         npc.home_scene)
    if "occult_supply" in needs and needs["occult_supply"]<=25 and phase_name in {"afternoon","evening"}:
        scene_id="divination_club" if npc.layer==NPCLayer.OFFICIAL_BEYONDER.value else "underground_market"
        return PhasePlan(scene_id,"搜集需求：寻找非凡材料、文献或物品",None,86,
                         "SEARCH_OCCULT_ITEM",npc.home_scene)
    return None


ALLOWED_BEHAVIORS = {
    "WORK", "REST", "SHOP", "SOCIALIZE", "INVESTIGATE_LOCATION",
    "MEET_PERSON", "FOLLOW_TARGET", "HIDE_EVIDENCE", "PRAY", "SEEK_HELP",
    "REPORT_TO_POLICE", "POLICE_INVESTIGATE", "RELOCATE_EVIDENCE", "FLEE",
    "RESPOND_OCCULT_INCIDENT", "COUNTER_INVESTIGATE",
    "PATROL_SCENE", "COMMIT_BURGLARY", "COMMIT_PICKPOCKET", "COMMIT_ASSAULT",
    "PERFORM_LEGAL_RITUAL", "PERFORM_INDEPENDENT_RITUAL", "SEARCH_OCCULT_ITEM",
    "FILE_INCIDENT_REPORT", "HANDLE_INCIDENT_REPORT",
    "ARREST_SUSPECT",
}


def build_decision_context(world, npc):
    rels = []
    for target_id, rel in list(npc.relationships.items())[:5]:
        target = world.npcs.get(target_id)
        if target:
            rels.append({"npc_id":target_id,"name":target.name,"trust":rel.trust,
                         "affection":rel.affection,"suspicion":rel.suspicion,"fear":rel.fear})
    known_threads = []
    for t in world.story_threads.values():
        if npc.id in t.participants:
            known_threads.append({"id":t.id,"title":t.title,"pressure":t.pressure,
                                  "questions":t.unresolved_questions})
    known_objects=[]
    for obj in world.objects.values():
        if obj.holder_id==npc.id or npc.id in obj.discovered_by:
            known_objects.append({"object_id":obj.id,"name":obj.name,"type":obj.object_type,
                                  "scene_id":obj.scene_id,"holder_id":obj.holder_id,
                                  "affordances":obj.affordances})
    durable_goals=[asdict(world.long_term_goals[goal_id])
                   for goal_id in npc.long_term_goal_ids
                   if goal_id in world.long_term_goals]
    active_operations=[]
    for goal in durable_goals:
        operation=world.ritual_engine.operations.get(goal.get("linked_plan_id"))
        if operation:
            active_operations.append({
                "operation_id":operation.id,"objective":operation.objective,
                "status":operation.status,"exposure":operation.exposure,
                "current_stage":operation.current_stage.id if operation.current_stage else None,
                "completed_stages":[stage.id for stage in operation.stages if stage.status=="completed"]})
        followup=world.followup_engine.plans.get(goal.get("linked_plan_id"))
        if followup:
            active_operations.append({
                "operation_id":followup.id,"objective":followup.template_id,
                "status":followup.status,"exposure":None,
                "current_stage":followup.current_stage.id if followup.current_stage else None,
                "completed_stages":[stage.id for stage in followup.stages if stage.status=="completed"]})
    return {
        "npc_id":npc.id,"name":npc.name,"occupation":npc.occupation,
        "organization":npc.organization,"layer":npc.layer,
        "sequence_pathway":npc.sequence_pathway,"sequence_rank":npc.sequence_rank,
        "faction_ids":npc.faction_ids,"duties":npc.duties,"personality":npc.personality,
        "needs":npc.needs,"emotions":npc.emotions,"health":npc.health,
        "states":npc.states,"skills":npc.skills,"sanity":npc.sanity,"wealth":npc.wealth,"goals":npc.goals,
        "special_needs":npc.special_needs,
        "long_term_goals":durable_goals,"active_long_term_plans":active_operations,
        "dominant_desires":[asdict(d) for d in world.desire_engine.dominant(npc,world)],
        "structured_intel":[asdict(f) for f in world.intelligence.known_facts(npc.id)[:12]],
        "recent_important_memories":npc.relevant_memories(10),
        "important_relationships":rels,"known_story_threads":known_threads,
        "known_objects":known_objects,
        "unreported_observations":[asdict(o) for o in pending_report_observations(world,npc)[:5]],
        "assigned_cases":[asdict(c) for c in world.cases.values()
                          if npc.id in c.assigned_officer_ids and c.status=="open"],
        "open_commitments":[asdict(c) for c in npc.commitments if c.active],
        "active_response_drives":[asdict(d) for d in npc.response_drives
                                  if d.active and d.expires_day>=world.day],
        "available_scenes":[{"scene_id":s.id,"name":s.name,"tags":s.tags} for s in world.scenes.values()
                            if "private_home" not in s.tags or s.id==npc.home_scene],
        "allowed_behaviors":sorted(ALLOWED_BEHAVIORS|set(world.action_registry.ids()))
    }


def normalize_llm_plan(world, npc, raw):
    raw=raw if isinstance(raw,dict) else {}
    out = {}
    valid = set(world.scenes)
    for phase in PHASES:
        p = raw.get("plans",{}).get(phase.value,{})
        sid = p.get("scene_id", npc.home_scene)
        if sid not in valid: sid = npc.home_scene
        tid = p.get("target_id")
        if tid not in world.npcs: tid = None
        fallback = p.get("fallback_scene_id")
        if fallback not in valid: fallback = npc.home_scene
        behavior=str(p.get("behavior","REST")).upper()[:80]
        intent=str(p.get("intent","处理日常事务"))[:300]
        priority=max(0,min(100,int(p.get("priority",50))))
        if behavior not in ALLOWED_BEHAVIORS and world.action_registry.get(behavior) is None:
            sid=npc.home_scene
            tid=None
            fallback=npc.home_scene
            behavior="REST"
            intent="原计划包含未注册行为，改为回家休息"
            priority=30
        if behavior=="MEET_PERSON":
            behavior="SOCIALIZE"
            tid=None
            intent="希望安排共同活动，等待邀请系统确认"
        out[phase.value] = PhasePlan(sid,intent,tid,priority,behavior,fallback)
    npc.action_chain=[]
    valid_conditions={"always","if_exposed","if_official_has_evidence","if_low_energy"}
    for step in raw.get("strategy_steps",[])[:3]:
        if not isinstance(step,dict):
            continue
        action_id=str(step.get("action_id") or step.get("behavior") or "").upper()
        phase=step.get("phase")
        scene_id=step.get("scene_id") or step.get("target_scene")
        target_id=step.get("target_id")
        condition=str(step.get("condition","always"))
        if (action_id not in ALLOWED_BEHAVIORS and world.action_registry.get(action_id) is None):
            continue
        matching=[phase_name for phase_name,plan in out.items()
                  if plan.behavior==action_id and (scene_id is None or plan.scene_id==scene_id)]
        if phase not in {item.value for item in PHASES}:
            phase=matching[0] if matching else "afternoon"
        if scene_id not in world.scenes:
            scene_id=out[phase].scene_id
        if scene_id not in world.scenes:
            continue
        if target_id not in world.npcs: target_id=None
        if condition not in valid_conditions: condition="always"
        npc.action_chain.append({"phase":phase,"action_id":action_id,"scene_id":scene_id,
                                 "target_id":target_id,"condition":condition,
                                 "intent":str(step.get("intent","执行策略步骤"))[:180],
                                 "active":True})
    return out


def strategy_condition_met(world,npc,condition):
    if condition=="always": return True
    if condition=="if_exposed": return npc.states.get("legal_risk",0)>=25
    if condition=="if_low_energy": return npc.states.get("energy",70)<30
    if condition=="if_official_has_evidence":
        return any(case.evidence_ids and npc.id in case.suspect_ids for case in world.cases.values())
    return False


def resolve_phase_plan(world, npc, phase):
    if health_band(npc)=="critical":
        return PhasePlan("hospital","危重伤势使其无法继续活动，需要立即住院治疗",
                         priority=110,behavior="SEEK_HELP")
    if health_band(npc)=="severe":
        return PhasePlan("hospital","重伤使其停止工作与危险行动，前往医院治疗",
                         priority=105,behavior="SEEK_HELP")
    base = npc.daily_plan.get(phase.value) or rule_plan_for_npc(world,npc)[phase.value]
    candidates = [base]
    for step in npc.action_chain:
        if (step.get("active") and step.get("phase")==phase.value
                and strategy_condition_met(world,npc,step.get("condition","always"))):
            candidates.append(PhasePlan(step["scene_id"],step["intent"],step.get("target_id"),
                                        88,step["action_id"],npc.home_scene))
    for c in npc.commitments:
        if c.active and c.execute_phase == phase.value:
            candidates.append(PhasePlan(c.scene_id,c.promise,
                                        c.source_id if c.source_id in world.npcs else None,
                                        c.priority,"MEET_PERSON",npc.home_scene))
    for drive in npc.response_drives:
        if drive.active and drive.expires_day>=world.day and drive.execute_phase==phase.value:
            candidates.append(PhasePlan(drive.scene_id,drive.intent,None,drive.priority,
                                        drive.behavior,npc.home_scene))
    special=special_need_plan(world,npc,phase)
    if special:
        candidates.append(special)
    duty=professional_duty_plan(world,npc,phase)
    if duty:
        candidates.append(duty)
    case=active_case_for_officer(world,npc) if is_official_responder(npc) else None
    if case and phase==Phase.AFTERNOON and case.stage=="operation_planned":
        candidates.append(PhasePlan("blackthorn_security",
                                    f"为案件 {case.id} 制定干预行动",
                                    None,100,"PLAN_INTERVENTION",npc.home_scene))
    elif case and phase==Phase.AFTERNOON and case.stage in ("suspect_identified","surveillance") and case.suspect_ids:
        suspect=world.npcs.get(case.suspect_ids[0])
        if suspect:
            candidates.append(PhasePlan(suspect.current_scene,
                                        f"监视案件 {case.id} 的嫌疑人 {suspect.name}",
                                        suspect.id,96,"FOLLOW_TARGET",npc.home_scene))
    if npc.health < 61:
        return PhasePlan("hospital","前往医院处理严重健康问题",priority=95,behavior="SEEK_HELP")
    if npc.sanity < 25:
        return PhasePlan("evernight_church","寻求精神或宗教帮助",priority=92,behavior="SEEK_HELP")
    return max(candidates, key=lambda p:p.priority)


def relationship_between(a,b):
    if b.id not in a.relationships: a.relationships[b.id] = Relationship()
    return a.relationships[b.id]


def interaction_score(world,a,b,scene):
    ra, rb = relationship_between(a,b), relationship_between(b,a)
    score = (a.personality["social"]+b.personality["social"])*0.12
    score += max(0,ra.trust-50)*0.25 + max(0,rb.trust-50)*0.25
    score += ra.suspicion*0.35 + rb.suspicion*0.35
    pa, pb = resolve_phase_plan(world,a,world.phase), resolve_phase_plan(world,b,world.phase)
    if pa.target_id==b.id: score += 45
    if pb.target_id==a.id: score += 45
    for t in world.story_threads.values():
        if t.active and a.id in t.participants and b.id in t.participants: score += 25
    if scene.id in ("east_dock","warehouse_3"):
        conflict = (("调查东码头最近的失踪与异常传闻" in a.goals and "掩盖三号仓库的违禁货物出入记录" in b.goals)
                    or ("调查东码头最近的失踪与异常传闻" in b.goals and "掩盖三号仓库的违禁货物出入记录" in a.goals))
        if conflict: score += 50
    return score + world.rng.uniform(0,20)


def hide_warehouse_evidence(world,npc,scene):
    obj=world.objects["object:warehouse_contraband_ledger_page"]
    if obj.destroyed or obj.hidden:
        return
    has_access=(obj.scene_id==scene.id or obj.holder_id==npc.id)
    organization_aliases={"aurora_cell":"aurora_order_tingen"}
    authorized=(npc.organization==obj.owner_id
                or organization_aliases.get(npc.organization)==obj.owner_id
                or obj.owner_id in npc.faction_ids or obj.holder_id==npc.id)
    if not has_access or not authorized or "hide" not in obj.affordances:
        make_event(world,"BEHAVIOR_FAILED",
                   f"{npc.name} 无法接触或无权藏匿 {obj.name}。",
                   [npc.id],scene.id,severity=1,tags=["behavior_failure"],
                   level=EventLevel.BACKGROUND.value,object_ids=[obj.id])
        return
    obj.hidden=True
    obj.holder_id=None
    obj.scene_id=scene.id
    obj.container_id="container:warehouse_3:discarded_medicine_cabinet"
    obj.concealment=min(95,scene.privacy//2+npc.abilities["dexterity"]*6)
    if npc.id not in obj.known_location_by:
        obj.known_location_by.append(npc.id)
    hidden_event=make_event(world,"EVIDENCE_HIDDEN",
                            f"{npc.name} 将 {obj.name} 藏进 {scene.name} 的废弃药柜。",
                            [npc.id],scene.id,severity=5,conflict=4,secret=8,danger=3,emotion=2,
                            tags=["secret","evidence","concealment"],object_ids=[obj.id],
                            organization_ids=[npc.organization] if npc.organization else [],
                            conflict_ids=["conflict:warehouse_anomaly"],
                            level=EventLevel.SIGNIFICANT.value)
    obj.hidden_event_id=hidden_event.event_id
    return hidden_event


def search_hidden_objects(world,npc,scene):
    candidates=[obj for obj in world.objects.values()
                if not obj.destroyed and obj.hidden and obj.scene_id==scene.id
                and npc.id not in obj.discovered_by
                and npc.id not in obj.known_location_by
                and npc.id!=obj.custodian_id and "search" in obj.affordances]
    for obj in candidates:
        attempts=obj.search_attempts.get(npc.id,0)
        search_power=(npc.abilities["knowledge"]*7+npc.abilities["inspiration"]*6
                      +npc.personality["curiosity"]*0.35)
        success_chance=max(10,min(90,50+search_power-obj.concealment+attempts*12))
        obj.search_attempts[npc.id]=attempts+1
        if world.rng.uniform(0,100)>=success_chance:
            continue
        obj.discovered_by.append(npc.id)
        fact=f"{obj.name} 被藏在{scene.name}的废弃药柜中"
        if fact not in npc.knowledge:
            npc.knowledge.append(fact)
        discovery=make_event(world,"EVIDENCE_DISCOVERED",
                             f"{npc.name} 搜查 {scene.name} 时在废弃药柜中发现了 {obj.name}。",
                             [npc.id],scene.id,severity=7,conflict=7,secret=8,danger=4,emotion=7,
                             tags=["investigation","evidence","discovery"],object_ids=[obj.id],
                             knowledge_ids=[obj.knowledge_id] if obj.knowledge_id else [],
                             organization_ids=[obj.owner_id] if obj.owner_id else [],
                             conflict_ids=["conflict:warehouse_anomaly"],parent_id=obj.hidden_event_id)
        obs=Observation(f"obs_{uuid.uuid4().hex[:10]}",npc.id,discovery.event_id,scene.id,
                        discovery.description,0.95,discovery.severity,
                        list(discovery.conflict_ids),[obj.id])
        world.observations[obs.id]=obs
        if is_official_responder(npc):
            obs.reported=True
            assigned=active_case_for_officer(world,npc)
            if assigned:
                assigned.evidence_ids=sorted(set(assigned.evidence_ids+[obj.id]))
        change_state(world,npc,"fear",12,"发现被刻意藏匿的违禁货物账页",discovery)
        change_state(world,npc,"stress",10,"意识到调查涉及有组织的违禁活动",discovery)
        custodian=world.npcs.get(obj.custodian_id)
        if custodian and custodian.id!=npc.id:
            rel=relationship_between(npc,custodian)
            rel.suspicion=min(100,rel.suspicion+25)
            rel.trust=max(0,rel.trust-15)
            belief=f"{custodian.name} 可能藏匿了违禁货物账页"
            if belief not in npc.beliefs:
                npc.beliefs.append(belief)
            make_event(world,"RELATIONSHIP_CHANGED",
                       f"{npc.name} 将发现的账页与保管人 {custodian.name} 联系起来，对其信任下降并产生怀疑。",
                       [npc.id,custodian.id],scene.id,severity=3,conflict=5,secret=4,emotion=6,
                       tags=["relationship","suspicion","evidence"],object_ids=[obj.id],
                       knowledge_ids=[obj.knowledge_id] if obj.knowledge_id else [],
                       organization_ids=[obj.owner_id] if obj.owner_id else [],
                       conflict_ids=["conflict:warehouse_anomaly"],trace_id=discovery.trace_id,
                       parent_id=discovery.event_id,level=EventLevel.SIGNIFICANT.value)


PATHWAY_AFFINITY = {
    "不眠者":{"tracking":100,"observation":120,"counter_tracking":80,"investigation":90},
    "收尸人":{"tracking":70,"observation":100,"investigation":110,"mysticism":100},
    "阅读者":{"observation":80,"investigation":120,"insight":110,"mysticism":100},
    "占卜家":{"tracking":70,"observation":90,"counter_tracking":90,"investigation":110},
    "学徒":{"tracking":80,"stealth":100,"counter_tracking":100,"observation":80},
    "怪物":{"observation":110,"insight":110,"counter_tracking":80,"tracking":70},
    "猎人":{"tracking":120,"observation":100,"counter_tracking":110,"combat":120},
    "罪犯":{"stealth":110,"counter_tracking":100,"deception":110,"combat":100},
    "囚犯":{"combat":110,"willpower":120,"counter_tracking":80,"stealth":70},
    "秘祈人":{"ritual":120,"mysticism":120,"stealth":90,"counter_tracking":100},
}


def sequence_modifier(npc,skill):
    """廷根的非凡者只使用序列 9、8、7；数字越小，基础加值越高。"""
    if npc.sequence_rank not in (7,8,9):
        return 0
    base=(10-npc.sequence_rank)*8
    affinity=PATHWAY_AFFINITY.get(npc.sequence_pathway,{}).get(skill,60)
    return round(base*affinity/100)


def check_outcome(margin):
    if margin>=40: return "complete_success"
    if margin>=15: return "success"
    if margin>-15: return "partial"
    if margin>-40: return "failure"
    return "critical_failure"


def resolve_opposed_check(world,check_type,actor,opponent,actor_skill,opponent_skill,
                           actor_context=0,opponent_context=0,scene_id=None):
    actor_roll=world.rng.randint(1,100)
    opponent_roll=world.rng.randint(1,100)
    actor_modifiers={"skill":actor.skills.get(actor_skill,0),
                     "sequence":sequence_modifier(actor,actor_skill),
                     "context":actor_context,
                     "health":health_action_modifier(actor)}
    opponent_modifiers={"skill":opponent.skills.get(opponent_skill,0),
                        "sequence":sequence_modifier(opponent,opponent_skill),
                        "context":opponent_context,
                        "health":health_action_modifier(opponent)}
    actor_total=actor_roll+sum(actor_modifiers.values())
    opponent_total=opponent_roll+sum(opponent_modifiers.values())
    margin=actor_total-opponent_total
    result=ActionCheckResult(check_type,actor.id,opponent.id,actor_roll,opponent_roll,
                             actor_modifiers,opponent_modifiers,actor_total,opponent_total,
                             margin,check_outcome(margin))
    world.ledger.emit(day=world.day,phase=world.phase.value,system="action_check",
                      event_type="ACTION_CHECK_RESOLVED",
                      message=f"{actor.name} 对 {opponent.name} 的{check_type}检定：{result.outcome}（差值 {margin}）。",
                      actor_ids=[actor.id,opponent.id],scene_id=scene_id,payload=asdict(result))
    return result


def action_context(world,scene):
    def emit(event_type,message,actor_ids,scene_id,**kwargs):
        return make_event(world,event_type,message,actor_ids,scene_id,**kwargs)
    def opposed(actor,opponent,actor_skill,opponent_skill,label):
        return resolve_opposed_check(world,label,actor,opponent,actor_skill,opponent_skill,
                                     scene_id=scene.id)
    return {"world":world,"scene_id":scene.id,"make_event":emit,
            "opposed_check":opposed,"intelligence":world.intelligence}


def discover_trace_evidence(world,npc,scene):
    discovered_ids=[]
    for trace in world.ritual_engine.discoverable_at(scene.id):
        if npc.id in trace.discovered_by:
            continue
        search_total=(world.rng.randint(1,100)+npc.skills.get("investigation",0)
                      +sequence_modifier(npc,"investigation"))
        if search_total < 115-trace.discoverability:
            continue
        trace.discovered_by.append(npc.id)
        discovered_ids.append(trace.id)
        fact=world.intelligence.create(
            subject_id=trace.source_actor_ids[0] if trace.source_actor_ids else "unknown_actor",
            predicate="left_trace",object_id=trace.id,day=world.day,phase=world.phase.value,
            source_type="physical_evidence",source_id=npc.id,confidence=0.9,
            secrecy=75,known_by=[npc.id],evidence_ids=[trace.id],
            summary=f"{npc.name} 在 {scene.name} 发现了{trace.trace_type}")
        make_event(world,"RITUAL_TRACE_DISCOVERED",
            f"{npc.name} 在 {scene.name} 发现了{trace.trace_type}，确认这里发生过可疑活动。",
            [npc.id],scene.id,severity=7,conflict=7,danger=5,secret=8,emotion=6,
            tags=["investigation","trace","occult" if trace.occult else "crime"],
            object_ids=[trace.id],knowledge_ids=[fact.id],
            conflict_ids=["conflict:tingen_occult_war"] if trace.occult else [])
    if discovered_ids and is_official_responder(npc):
        case=active_case_for_officer(world,npc)
        if case:
            new_case_evidence=[trace_id for trace_id in discovered_ids if trace_id not in case.evidence_ids]
            case.evidence_ids=sorted(set(case.evidence_ids+new_case_evidence))
            case.progress=min(100,case.progress+25*len(new_case_evidence))
            for trace_id in new_case_evidence:
                trace=world.ritual_engine.traces[trace_id]
                for actor_id in trace.source_actor_ids:
                    case.suspect_ids=sorted(set(case.suspect_ids+[actor_id]))
                    case.exposure_counts[actor_id]=case.exposure_counts.get(actor_id,0)+1
            advance_case_stage(world,case)
    return discovered_ids


def operation_known_to_case(world,case):
    for evidence_id in case.evidence_ids:
        trace=world.ritual_engine.traces.get(evidence_id)
        if trace and trace.payload.get("operation_id") in world.ritual_engine.operations:
            return world.ritual_engine.operations[trace.payload["operation_id"]]
    return None


def plan_official_intervention(world,npc,scene):
    case=active_case_for_officer(world,npc)
    operation=operation_known_to_case(world,case) if case else None
    if not case or not operation:
        return make_event(world,"INTERVENTION_PLANNING_FAILED",
                          f"{npc.name} 缺少足够情报，无法制定具体干预方案。",
                          [npc.id],scene.id,severity=2,tags=["official","planning","failure"],
                          level=EventLevel.BACKGROUND.value)
    if operation.status!="active":
        case.status="resolved"; case.stage="resolved"
        if not case.stage_history or case.stage_history[-1]!="resolved":
            case.stage_history.append("resolved")
        return make_event(world,"CASE_LINKED_OPERATION_ALREADY_RESOLVED",
                          f"{npc.name} 确认与案件 {case.id} 相关的非法仪式已被阻止。",
                          [npc.id],scene.id,severity=4,tags=["official","case","resolved"],
                          conflict_ids=["conflict:tingen_occult_war"])
    event=make_event(world,"OFFICIAL_INTERVENTION_PLANNED",
        f"{npc.name} 根据已发现的仪式痕迹，决定在 {operation.scene_id} 部署阻止行动。",
        [npc.id],scene.id,severity=8,conflict=8,danger=6,secret=8,emotion=6,
        tags=["official","intervention","operation"],object_ids=case.evidence_ids,
        conflict_ids=["conflict:tingen_occult_war"])
    case.stage="intervention"
    case.stage_history.append("intervention")
    npc.response_drives.append(ResponseDrive(
        f"drive_{uuid.uuid4().hex[:10]}",event.event_id,"stop_illegal_ritual",
        operation.scene_id,"STOP_RITUAL",f"按照方案阻止 {operation.id} 的非法仪式",
        100,"late_night",operation.scheduled_day+1,True))
    return event


def stop_illegal_ritual(world,npc,scene):
    case=active_case_for_officer(world,npc)
    operation=operation_known_to_case(world,case) if case else None
    if not operation or operation.status!="active":
        return make_event(world,"INTERVENTION_FOUND_NOTHING",
                          f"{npc.name} 到达 {scene.name}，但没有找到仍在进行的仪式。",
                          [npc.id],scene.id,severity=3,tags=["official","intervention"],
                          level=EventLevel.BACKGROUND.value)
    leader=world.npcs.get(operation.leader_id)
    if not leader or not leader.alive:
        operation.status="failed"
        return None
    result=resolve_opposed_check(world,"阻止非法仪式",npc,leader,
                                 "investigation","ritual",10,-operation.exposure//5,scene.id)
    if result.margin>=15:
        operation.status="failed"
        operation.outcome_type="official_victory"
        case.status="resolved"; case.stage="resolved"; case.stage_history.append("resolved")
        case.closed_day=world.day
        leader.states["legal_risk"]=min(100,leader.states.get("legal_risk",0)+45)
        event=make_event(world,"ILLEGAL_RITUAL_STOPPED",
            f"{npc.name} 破坏了 {leader.name} 的非法仪式，官方开始封锁现场并追捕参与者。",
            [npc.id,leader.id],scene.id,severity=10,conflict=10,danger=9,secret=7,emotion=9,
            tags=["official","ritual","intervention","conflict"],
            conflict_ids=["conflict:tingen_occult_war"])
        resolve_operation_consequences(world,operation)
        return event
    operation.exposure=min(100,operation.exposure+25)
    operation.intervention_failures+=1
    event=make_event(world,"ILLEGAL_RITUAL_INTERVENTION_FAILED",
        f"{leader.name} 利用仪式准备逼退了 {npc.name}，官方的第一次阻止行动失败。",
        [npc.id,leader.id],scene.id,severity=10,conflict=10,danger=9,secret=8,emotion=9,
        tags=["official","ritual","intervention","conflict","failure"],
        conflict_ids=["conflict:tingen_occult_war"])
    npc.health=max(1,npc.health-world.rng.randint(12,28))
    change_state(world,npc,"pain",25,"阻止非法仪式失败并受伤",event)
    if operation.intervention_failures==1:
        reinforcement=spawn_story_character(world,"official_reinforcement","nightwatchers_tingen",
                                             "支援失败的仪式阻止行动",official=True)
        operation.spawned_character_ids.append(reinforcement.id)
        create_followup_goal(world,reinforcement.id,"reinforce_ritual_case",
                             f"增援案件 {case.id} 并再次阻止非法仪式",100,
                             scene_id=operation.scene_id,target_id=operation.leader_id,
                             linked_case_id=case.id)
        make_event(world,"STORY_CHARACTER_ARRIVED",
            f"{reinforcement.name} 因首次干预失败而从外地抵达廷根，加入后续阻止行动。",
            [reinforcement.id],"railway_station",severity=8,conflict=9,danger=7,
            secret=6,emotion=7,tags=["new_character","official","reinforcement"],
            organization_ids=["nightwatchers_tingen"],
            conflict_ids=["conflict:tingen_occult_war"])
    if operation.intervention_failures<3:
        npc.response_drives.append(ResponseDrive(
            f"drive_{uuid.uuid4().hex[:10]}",event.event_id,"retry_stop_illegal_ritual",
            operation.scene_id,"STOP_RITUAL",f"重新组织力量阻止 {operation.id}",
            100,"late_night",world.day+2,True))
    return event


def create_crime_trace(world,npc,scene,crime_type):
    trace=TraceEvidence(
        id=f"trace_evidence_{uuid.uuid4().hex[:10]}",trace_type=crime_type,
        scene_id=scene.id,created_day=world.day,created_phase=world.phase.value,
        source_action_id=crime_type.upper(),source_actor_ids=[npc.id],
        discoverability=world.rng.randint(35,80),occult=False,
        payload={"suspect_id":npc.id,"crime_type":crime_type})
    world.ritual_engine.traces[trace.id]=trace
    return trace


def schedule_injury_response(world, victim, injury_event):
    """Turn an injury into a future action instead of leaving it as flavor text."""
    change_state(world, victim, "pain", 25, "遭到袭击后疼痛加剧", injury_event)
    change_state(world, victim, "fear", 12, "袭击造成持续恐惧", injury_event)
    if victim.health <= 55:
        add_response_drive(
            victim, injury_event, "seek_injury_treatment", "hospital", "SEEK_HELP",
            f"前往医院治疗由袭击造成的伤势：{injury_event.description}", 99, world.day)
    if victim.health <= 15:
        victim.investigation_progress["critical_injury_day"] = world.day


def resolve_untreated_injuries(world):
    """Critical injuries may kill after a full day unless hospital treatment cleared them."""
    for victim in list(world.npcs.values()):
        injured_day = victim.investigation_progress.get("critical_injury_day")
        if injured_day is None or not npc_can_act(victim) or world.day <= injured_day:
            continue
        if victim.health > 15:
            victim.investigation_progress.pop("critical_injury_day", None)
            continue
        if world.rng.random() >= 0.35:
            continue
        relatives = [world.npcs[other_id] for other_id, relation in victim.relationships.items()
                     if other_id in world.npcs
                     and set(relation.kinds) & {"朋友", "爱人"}]
        witness = next((other for other in relatives if npc_can_act(other)), None)
        actor_ids = [victim.id] + ([witness.id] if witness else [])
        event = make_event(
            world, "DEATH_FROM_UNTREATED_INJURY",
            f"{victim.name} 的重伤未得到及时治疗，在住所中伤势恶化死亡。",
            actor_ids, victim.home_scene, severity=10, conflict=8, danger=10,
            emotion=10, tags=["death", "injury", "untreated", "consequence"],
            conflict_ids=["conflict:public_incident"])
        victim.health = 0
        set_disposition(victim, "dead", world.day, event.event_id)
        victim.investigation_progress.pop("critical_injury_day", None)


def execute_special_need_behavior(world,npc,scene,plan):
    b=plan.behavior.upper()
    if b in {"COMMIT_BURGLARY","COMMIT_PICKPOCKET","COMMIT_ASSAULT"}:
        victim=world.npcs.get(plan.target_id)
        if b!="COMMIT_BURGLARY":
            present=[other for other in world.npcs.values()
                     if npc_can_act(other) and other.id!=npc.id and other.current_scene==scene.id]
            victim=max(present,key=lambda item:item.wealth,default=None)
        trace=create_crime_trace(world,npc,scene,b.lower())
        difficulty=58+scene.security//4
        skill="combat" if b=="COMMIT_ASSAULT" else "stealth"
        total=world.rng.randint(1,100)+npc.skills.get(skill,0)+sequence_modifier(npc,skill)
        success=total>=difficulty and victim is not None
        labels={"COMMIT_BURGLARY":"入室盗窃","COMMIT_PICKPOCKET":"扒窃",
                "COMMIT_ASSAULT":"暴力勒索"}
        if success:
            amount=min(victim.wealth,world.rng.randint(4,15))
            victim.wealth-=amount; npc.wealth+=amount
            if b=="COMMIT_ASSAULT":
                victim.health=max(0,victim.health-world.rng.randint(20,110))
                change_state(world,victim,"fear",20,"遭到暴力勒索")
            event=make_event(world,"CRIME_COMMITTED",
                f"{npc.name} 对 {victim.name} 实施{labels[b]}并取得价值 {amount} 的财物。",
                [npc.id,victim.id],scene.id,severity=7,conflict=8,danger=7,
                secret=7,emotion=8,tags=["crime",b.lower(),"consequence"],
                object_ids=[trace.id])
            npc.special_needs["crime_control"]=min(100,npc.special_needs.get("crime_control",0)+65)
            change_state(world,npc,"legal_risk",8,"犯罪留下可调查痕迹",event)
            if b=="COMMIT_ASSAULT":
                if victim.health<=0:
                    set_disposition(victim,"dead",world.day,event.event_id)
                    make_event(world,"DEATH_FROM_ASSAULT",
                               f"{victim.name} 因 {npc.name} 的袭击伤势过重死亡。",
                               [victim.id,npc.id],scene.id,severity=10,conflict=10,danger=10,
                               emotion=10,tags=["death","assault","crime"],parent_id=event.event_id,
                               conflict_ids=["conflict:public_incident"])
                else:
                    injury_event=make_event(world,"INJURED_IN_ASSAULT",
                               f"{victim.name} 在 {npc.name} 的袭击中受伤，当前健康为 {victim.health}。",
                               [victim.id,npc.id],scene.id,severity=7,conflict=8,danger=8,
                               emotion=8,tags=["injury","assault","crime"],parent_id=event.event_id,
                               conflict_ids=["conflict:public_incident"])
                    schedule_injury_response(world,victim,injury_event)
            return event
        event=make_event(world,"CRIME_ATTEMPT_EXPOSED",
            f"{npc.name} 尝试{labels[b]}失败，被受害者或现场人员察觉。",
            [npc.id]+([victim.id] if victim else []),scene.id,severity=7,conflict=8,
            danger=6,secret=3,emotion=8,tags=["crime","exposure","witness"],
            object_ids=[trace.id])
        npc.special_needs["crime_control"]=min(100,npc.special_needs.get("crime_control",0)+35)
        change_state(world,npc,"legal_risk",32,"犯罪未遂被目击",event)
        case=CaseFile(f"case_{len(world.cases)+1:03d}",b.lower(),"open",[],[],[trace.id],
                      [npc.id],[scene.id],["conflict:street_crime"],70,created_day=world.day)
        world.cases[case.id]=case
        return event
    if b=="PATROL_SCENE":
        found=[trace for trace in world.ritual_engine.discoverable_at(scene.id)
               if npc.id not in trace.discovered_by and
               (not trace.occult or npc.layer==NPCLayer.OFFICIAL_BEYONDER.value)]
        discovered=[]
        for trace in found:
            score=world.rng.randint(1,100)+npc.skills.get("observation",0)+sequence_modifier(npc,"observation")
            if score>=110-trace.discoverability:
                trace.discovered_by.append(npc.id); discovered.append(trace)
                suspect=trace.source_actor_ids[0] if trace.source_actor_ids else None
                case=CaseFile(f"case_{len(world.cases)+1:03d}","patrol_discovery","open",
                              [npc.id],[],[trace.id],[suspect] if suspect else [],[scene.id],
                              ["conflict:tingen_occult_war"] if trace.occult else ["conflict:street_crime"],65,
                              created_day=world.day)
                world.cases[case.id]=case
        event=make_event(world,"PATROL_COMPLETED",
            f"{npc.name} 完成对 {scene.name} 的巡逻，发现 {len(discovered)} 份可调查痕迹。",
            [npc.id],scene.id,severity=4+min(3,len(discovered)),conflict=4,
            tags=["police","patrol","investigation"],object_ids=[t.id for t in discovered])
        return event
    if b in {"PERFORM_LEGAL_RITUAL","PERFORM_INDEPENDENT_RITUAL"}:
        illegal=b=="PERFORM_INDEPENDENT_RITUAL"
        total=world.rng.randint(1,100)+npc.skills.get("ritual",0)+sequence_modifier(npc,"ritual")
        success=total>=72
        trace=TraceEvidence(
            f"trace_evidence_{uuid.uuid4().hex[:10]}","spiritual_residue",scene.id,
            world.day,world.phase.value,b,[npc.id],65 if illegal else 25,True,
            payload={"legal":not illegal,"success":success})
        world.ritual_engine.traces[trace.id]=trace
        event=make_event(world,"RITUAL_PERFORMED" if success else "RITUAL_FAILED",
            f"{npc.name} 举行了{'非法秘密' if illegal else '受监管的合法'}仪式，结果为{'成功' if success else '失败'}。",
            [npc.id],scene.id,severity=8 if illegal else 4,conflict=7 if illegal else 1,
            danger=7 if illegal else 3,secret=9 if illegal else 3,emotion=6,
            tags=["ritual","illegal" if illegal else "legal","occult"],object_ids=[trace.id],
            conflict_ids=["conflict:tingen_occult_war"] if illegal else [])
        npc.special_needs["ritual_stability"]=min(100,npc.special_needs.get("ritual_stability",0)+70)
        if illegal: change_state(world,npc,"legal_risk",18,"非法仪式留下灵性痕迹",event)
        if not success:
            npc.sanity=max(1,npc.sanity-world.rng.randint(3,12))
        return event
    if b=="SEARCH_OCCULT_ITEM":
        total=world.rng.randint(1,100)+npc.skills.get("mysticism",0)+sequence_modifier(npc,"mysticism")
        success=total>=78
        object_ids=[]
        if success:
            item=WorldObject(f"object:occult_{uuid.uuid4().hex[:8]}","来源不明的非凡材料",
                             "occult_material",None,holder_id=npc.id,value=25,
                             legality="restricted",tags=["occult","material"],
                             affordances=["trade","ritual","hide"])
            world.objects[item.id]=item; object_ids=[item.id]
        event=make_event(world,"OCCULT_ITEM_FOUND" if success else "OCCULT_SEARCH_FAILED",
            f"{npc.name} 在 {scene.name} {'找到了一份来源不明的非凡材料' if success else '没有找到可靠的非凡物品'}。",
            [npc.id],scene.id,severity=6 if success else 2,secret=8,emotion=5,
            tags=["occult","collection","success" if success else "failure"],object_ids=object_ids)
        if success:
            npc.special_needs["occult_supply"]=min(100,npc.special_needs.get("occult_supply",0)+60)
        return event
    return None


def arrest_suspect(world,officer,scene,plan):
    suspect=world.npcs.get(plan.target_id)
    case=active_case_for_officer(world,officer)
    if not suspect or not case or suspect.id not in case.suspect_ids:
        return None
    if not npc_can_act(suspect):
        return None
    if any(event.event_type in {"SUSPECT_ARRESTED","SUSPECT_ESCAPED_ARREST"}
           and suspect.id in event.actor_ids
           for event in world.events_by_day.get(world.day,[])):
        return None
    result=resolve_opposed_check(world,"逮捕",officer,suspect,"combat","stealth",
                                 len(case.evidence_ids)*6,0,scene.id)
    if result.margin>=0:
        event=make_event(world,"SUSPECT_ARRESTED",
            f"{officer.name} 依据案件 {case.id} 的逮捕令控制了 {suspect.name}，案件进入结案。",
            [officer.id,suspect.id],scene.id,severity=10,conflict=10,danger=8,
            emotion=9,tags=["police","arrest","case_resolved"],object_ids=case.evidence_ids,
            conflict_ids=case.conflict_ids)
        suspect.current_scene="police_station"
        set_disposition(suspect,"arrested",world.day,event.event_id)
        case.status="resolved"; case.stage="resolved"; case.progress=100
        case.closed_day=world.day; case.stage_history.append("resolved")
        return event
    event=make_event(world,"SUSPECT_ESCAPED_ARREST",
        f"{suspect.name} 逃过 {officer.name} 的逮捕行动，警方将其列为在逃嫌疑人。",
        [officer.id,suspect.id],scene.id,severity=9,conflict=10,danger=8,
        secret=5,emotion=9,tags=["police","arrest","escape","fugitive"],
        object_ids=case.evidence_ids,conflict_ids=case.conflict_ids)
    case.stage="fugitive"; case.stage_history.append("fugitive")
    case.last_progress_day=world.day
    suspect.current_scene="underground_market"
    set_disposition(suspect,"wanted",world.day,event.event_id)
    change_state(world,suspect,"legal_risk",35,"逃避警方逮捕",event)
    return event


def execute_behavior(world,npc,scene,plan):
    b = plan.behavior.upper()
    if not can_perform_while_injured(npc,b):
        scene=world.scenes["hospital"]
        npc.current_scene="hospital"
        plan=PhasePlan("hospital","伤势迫使其停止原行动并接受治疗",
                       priority=110,behavior="SEEK_HELP")
        b="SEEK_HELP"
    if b in {"COMMIT_BURGLARY","COMMIT_PICKPOCKET","COMMIT_ASSAULT","PATROL_SCENE",
             "PERFORM_LEGAL_RITUAL","PERFORM_INDEPENDENT_RITUAL","SEARCH_OCCULT_ITEM"}:
        return execute_special_need_behavior(world,npc,scene,plan)
    if b=="FILE_INCIDENT_REPORT":
        return submit_incident_report(world,npc,scene)
    if b=="HANDLE_INCIDENT_REPORT":
        return handle_incident_report(world,npc,scene)
    if b=="ARREST_SUSPECT":
        return arrest_suspect(world,npc,scene,plan)
    if b=="PLAN_INTERVENTION":
        return plan_official_intervention(world,npc,scene)
    if b=="STOP_RITUAL":
        return stop_illegal_ritual(world,npc,scene)
    registered=world.action_registry.get(b)
    if registered:
        target=world.npcs.get(plan.target_id)
        fact_id=None
        if b in ("SHARE_INFORMATION","LIE_ABOUT_INFORMATION") and target:
            candidates=[fact for fact in world.intelligence.known_facts(npc.id)
                        if target.id not in fact.known_by]
            if candidates:
                fact_id=max(candidates,key=lambda fact:(fact.confidence,fact.day)).id
        result=world.action_registry.execute(b,npc=npc,context=action_context(world,scene),
                                             target=target,fact_id=fact_id)
        world.ledger.emit(day=world.day,phase=world.phase.value,system="action_registry",
                          event_type="REGISTERED_ACTION_RESOLVED",message=result.message,
                          actor_ids=[npc.id]+([target.id] if target else []),scene_id=scene.id,
                          payload=asdict(result))
        return next((event for event in reversed(world.events_by_day[world.day])
                     if event.event_id==result.event_id),None)
    if b=="WORK":
        npc.wealth += 1
        change_state(world,npc,"energy",-5,"完成一个时段的工作")
        change_state(world,npc,"morale",2,"工作带来稳定感")
    elif b=="REST":
        change_state(world,npc,"energy",50,"休息恢复精力")
        change_state(world,npc,"stress",-15,"休息缓解压力")
        change_state(world,npc,"pain",-5,"休息缓解轻微疼痛")
    elif b in {"SOCIALIZE","MEET_PERSON"}:
        change_state(world,npc,"loneliness",-18,"与他人共同活动")
        change_state(world,npc,"stress",-5,"社交活动缓解压力")
    elif b=="SHOP":
        if npc.wealth>5:
            food=world.objects["object:market_food_crate"]
            price=max(1,food.value)
            npc.wealth -= price
            food.quantity=max(0,food.quantity-1)
            purchase=make_event(world,"ITEM_BOUGHT_AND_USED",
                                f"{npc.name} 在 {scene.name} 购买并食用了一份 {food.name} 中的食物。",
                                [npc.id],scene.id,severity=1,emotion=2,tags=["trade","food"],
                                object_ids=[food.id],level=EventLevel.BACKGROUND.value)
            change_state(world,npc,"satiety",50,"购买并食用食物",purchase)
    elif b=="INVESTIGATE_LOCATION":
        before={obj.id for obj in world.objects.values() if npc.id in obj.discovered_by}
        search_hidden_objects(world,npc,scene)
        if is_official_responder(npc):
            newly_found={obj.id for obj in world.objects.values() if npc.id in obj.discovered_by}-before
            case=active_case_for_officer(world,npc)
            if case:
                case.evidence_ids=sorted(set(case.evidence_ids)|newly_found)
        discover_trace_evidence(world,npc,scene)
        chance = npc.abilities["knowledge"]*5+npc.abilities["inspiration"]*5+npc.personality["curiosity"]*0.25-scene.privacy*0.15
        fact="东码头货运登记簿显示多批未申报货物被送往三号仓库"
        progress_key="object:east_dock_shipping_register"
        attempts=npc.investigation_progress.get(progress_key,0)
        if scene.id=="east_dock" and fact not in npc.knowledge:
            npc.investigation_progress[progress_key]=attempts+1
        if (scene.id=="east_dock" and fact not in npc.knowledge
                and world.rng.uniform(0,100)<min(90,chance+attempts*8)):
            register=world.objects["object:east_dock_shipping_register"]
            make_event(world,"SHIPPING_RECORD_ANOMALY_FOUND",
                       f"{npc.name} 查阅 {register.name}，发现多批未申报货物都被送往三号仓库。",
                       [npc.id],scene.id,severity=5,secret=4,conflict=4,emotion=4,
                       tags=["investigation","shipping_record","warehouse_3"],
                       object_ids=[register.id],knowledge_ids=[register.knowledge_id],
                       conflict_ids=["conflict:warehouse_anomaly"])
            npc.knowledge.append(fact)
    elif b=="FOLLOW_TARGET":
        target=world.npcs.get(plan.target_id)
        if not target or not target.alive:
            return make_event(world,"TRACKING_ABORTED",f"{npc.name} 没有可追踪的具体目标。",
                              [npc.id],scene.id,severity=1,tags=["tracking","failure"],
                              level=EventLevel.BACKGROUND.value)
        clue_bonus=10 if any(target.name in belief for belief in npc.beliefs) else 0
        result=resolve_opposed_check(world,"追踪",npc,target,"tracking","counter_tracking",
                                     clue_bonus,scene.privacy//5,scene.id)
        if result.margin>=15:
            fact=f"{target.name} 在 Day {world.day} 曾前往 {scene.name}"
            if fact not in npc.knowledge: npc.knowledge.append(fact)
            case=active_case_for_officer(world,npc)
            if case and target.id in case.suspect_ids:
                case.exposure_counts[target.id]=case.exposure_counts.get(target.id,0)+1
                case.progress=min(100,case.progress+10)
                case.last_progress_day=world.day
                advance_case_stage(world,case)
            return make_event(world,"TARGET_FOLLOWED",
                f"{npc.name} 成功跟踪 {target.name} 至 {scene.name}，掌握了其行踪。",
                [npc.id,target.id],scene.id,severity=5,conflict=5,secret=7,emotion=4,
                tags=["tracking","success"],knowledge_ids=[f"knowledge:location:{target.id}:{world.day}"],
                conflict_ids=["conflict:tingen_occult_war"])
        if result.margin<=-15:
            belief=f"{npc.name} 可能正在跟踪自己"
            if belief not in target.beliefs: target.beliefs.append(belief)
            change_state(world,target,"alertness",12,"发现可疑的跟踪者")
            return make_event(world,"TRACKER_EXPOSED",
                f"{target.name} 识破了 {npc.name} 的跟踪，开始警惕并改变行动。",
                [npc.id,target.id],scene.id,severity=6,conflict=7,danger=5,secret=5,emotion=6,
                tags=["tracking","exposure"],conflict_ids=["conflict:tingen_occult_war"])
        return make_event(world,"TRACKING_INCONCLUSIVE",
            f"{npc.name} 尝试跟踪 {target.name}，但未能确认其去向。",
            [npc.id,target.id],scene.id,severity=2,secret=6,tags=["tracking","partial"],
            level=EventLevel.BACKGROUND.value)
    elif b=="HIDE_EVIDENCE":
        return hide_warehouse_evidence(world,npc,scene)
    elif b=="REPORT_TO_POLICE":
        pending=pending_report_observations(world,npc)
        if pending:
            file_police_report(world,npc,pending[0])
    elif b=="POLICE_INVESTIGATE":
        case=active_case_for_officer(world,npc)
        if case:
            investigation=make_event(world,"POLICE_CASE_INVESTIGATED",
                                     f"警察 {npc.name} 根据 {len(case.report_ids)} 份报告调查 {scene.name}。",
                                     [npc.id],scene.id,severity=5,conflict=5,danger=3,emotion=3,
                                     tags=["police","case","investigation"],object_ids=case.evidence_ids,
                                     conflict_ids=case.conflict_ids)
            before={obj.id for obj in world.objects.values() if npc.id in obj.discovered_by}
            search_hidden_objects(world,npc,scene)
            discover_trace_evidence(world,npc,scene)
            after={obj.id for obj in world.objects.values() if npc.id in obj.discovered_by}
            newly_found=after-before
            case.evidence_ids=sorted(set(case.evidence_ids)|newly_found)
            for object_id in newly_found:
                obj=world.objects[object_id]
                obj.hidden=False
                obj.holder_id=npc.id
                obj.scene_id=None
                obj.container_id="object:evidence_bag"
                custodian=world.npcs.get(obj.custodian_id)
                if custodian:
                    case.suspect_ids=sorted(set(case.suspect_ids+[custodian.id]))
                    case.conflict_ids=sorted(set(case.conflict_ids+["conflict:warehouse_anomaly"]))
                    if custodian.current_scene==scene.id:
                        questioned=make_event(world,"CUSTODIAN_QUESTIONED",
                                             f"警察 {npc.name} 出示查获的 {obj.name}，要求保管人 {custodian.name} 解释来源。",
                                             [npc.id,custodian.id],scene.id,severity=7,conflict=8,
                                             danger=3,secret=6,emotion=8,
                                             tags=["police","suspect","evidence"],object_ids=[obj.id],
                                             conflict_ids=case.conflict_ids)
                        change_state(world,custodian,"legal_risk",65,"被警方依据实物证据列为嫌疑人",questioned)
                        change_state(world,custodian,"fear",20,"警方开始正式询问",questioned)
                    elif not any(c.active and c.source_id==npc.id for c in custodian.commitments):
                        custodian.commitments.append(Commitment(
                            "afternoon","police_station",npc.id,96,
                            f"接受警察 {npc.name} 关于 {obj.name} 来源的正式询问。"))
                        make_event(world,"POLICE_SUMMONS_ISSUED",
                                   f"警察 {npc.name} 传唤 {custodian.name} 次日下午到警察局说明 {obj.name} 的来源。",
                                   [npc.id,custodian.id],"police_station",severity=6,conflict=6,
                                   secret=3,emotion=5,tags=["police","summons","suspect"],
                                   object_ids=[obj.id],conflict_ids=case.conflict_ids)
            case.progress=min(100,case.progress+20+len(newly_found)*35)
            if case.progress>=80:
                case.status="evidence_found"
            change_state(world,npc,"morale",4,"履行警察职责并推进案件",investigation)
    elif b=="RESPOND_OCCULT_INCIDENT":
        drive=next((d for d in npc.response_drives if d.active and d.behavior==b
                    and d.scene_id==scene.id),None)
        source_event=next((e for e in world.events_by_day.get(world.day-1,[])
                           if drive and e.event_id==drive.source_event_id),None)
        conflict_ids=list(source_event.conflict_ids) if source_event else ["conflict:tingen_occult_war"]
        response_action=(f"启动 {scene.name}内部戒备并秘密排查"
                         if "official_controlled" in scene.tags
                         else f"封锁 {scene.name}并检查灵性残留、目击者与可疑物品")
        response=make_event(world,"OFFICIAL_OCCULT_RESPONSE",
            f"值夜者 {npc.name} {response_action}。",
            [npc.id],scene.id,severity=7,conflict=7,danger=5,secret=6,emotion=5,
            tags=["official","nighthawk","occult","investigation"],conflict_ids=conflict_ids,
            parent_id=source_event.event_id if source_event else None)
        case=active_case_for_officer(world,npc)
        if case is None:
            case=next((existing for existing in world.cases.values()
                       if existing.case_type=="occult_incident"
                       and existing.status not in ("resolved","failed","closed")
                       and set(existing.conflict_ids)&set(conflict_ids)),None)
            if case:
                case.assigned_officer_ids=sorted(set(case.assigned_officer_ids+[npc.id]))
                case.known_locations=sorted(set(case.known_locations+[scene.id]))
            else:
                case=CaseFile(f"case_{len(world.cases)+1:03d}","occult_incident","open",
                              [npc.id],[],[],[],[scene.id],conflict_ids,90,created_day=world.day)
                world.cases[case.id]=case
        before={obj.id for obj in world.objects.values() if npc.id in obj.discovered_by}
        search_hidden_objects(world,npc,scene)
        discover_trace_evidence(world,npc,scene)
        newly_found={obj.id for obj in world.objects.values() if npc.id in obj.discovered_by}-before
        case.evidence_ids=sorted(set(case.evidence_ids)|newly_found)
        case.progress=min(100,case.progress+25+30*len(newly_found))
        for object_id in newly_found:
            obj=world.objects[object_id]
            obj.hidden=False; obj.holder_id=npc.id; obj.scene_id=None
            obj.container_id="object:evidence_bag"
            if obj.custodian_id:
                case.suspect_ids=sorted(set(case.suspect_ids+[obj.custodian_id]))
        change_state(world,npc,"alertness",8,"官方非凡者介入异常事件",response)
    elif b=="COUNTER_INVESTIGATE":
        officials=[other for other in world.npcs.values()
                   if other.alive and other.current_scene==scene.id
                   and other.id!=npc.id and is_official_responder(other)]
        if not officials:
            return make_event(world,"COUNTER_INVESTIGATION_INCONCLUSIVE",
                f"{npc.name} 在 {scene.name}没有观察到可确认的官方行动。",
                [npc.id],scene.id,severity=2,secret=8,tags=["counter_investigation","partial"],
                level=EventLevel.BACKGROUND.value)
        defender=max(officials,key=lambda other:other.skills.get("observation",0)
                     +sequence_modifier(other,"observation"))
        sanctuary_penalty=-25 if "official_controlled" in scene.tags else 0
        result=resolve_opposed_check(world,"反侦察",npc,defender,"counter_tracking","observation",
                                     sanctuary_penalty,scene.security//8,scene.id)
        if result.margin>=15:
            fact=f"官方非凡者 {defender.name} 正在 {scene.name} 调查"
            if fact not in npc.knowledge: npc.knowledge.append(fact)
            event=make_event(world,"HOSTILE_COUNTER_INVESTIGATION_SUCCEEDED",
                f"{npc.name} 避开 {defender.name} 的注意，确认了 {scene.name}的官方调查强度。",
                [npc.id,defender.id],scene.id,severity=6,conflict=8,danger=6,secret=9,emotion=5,
                tags=["hostile_beyonder","counter_investigation","success"],
                organization_ids=npc.faction_ids,conflict_ids=["conflict:tingen_occult_war"])
            change_state(world,npc,"alertness",10,"掌握官方调查强度",event)
            return event
        if result.margin<=-15:
            belief=f"{npc.name} 在 {scene.name}附近窥探官方调查"
            if belief not in defender.beliefs: defender.beliefs.append(belief)
            relationship_between(defender,npc).suspicion=min(100,relationship_between(defender,npc).suspicion+25)
            related_case=active_case_for_officer(world,defender)
            if related_case:
                related_case.suspect_ids=sorted(set(related_case.suspect_ids+[npc.id]))
                related_case.exposure_counts[npc.id]=related_case.exposure_counts.get(npc.id,0)+1
                related_case.progress=min(100,related_case.progress+10)
                advance_case_stage(world,related_case)
            event=make_event(world,"HOSTILE_COUNTER_INVESTIGATION_EXPOSED",
                f"{defender.name} 发现 {npc.name} 正在窥探官方调查，将其列为可疑对象。",
                [npc.id,defender.id],scene.id,severity=7,conflict=8,danger=7,secret=5,emotion=7,
                tags=["hostile_beyonder","counter_investigation","exposure"],
                organization_ids=npc.faction_ids,conflict_ids=["conflict:tingen_occult_war"])
            change_state(world,npc,"legal_risk",18,"反侦察时被官方非凡者发现",event)
            return event
        return make_event(world,"COUNTER_INVESTIGATION_INCONCLUSIVE",
            f"{npc.name} 与 {defender.name} 彼此试探，双方都没有获得可确认的情报。",
            [npc.id,defender.id],scene.id,severity=3,conflict=4,secret=8,emotion=4,
            tags=["counter_investigation","partial"],conflict_ids=["conflict:tingen_occult_war"])
    elif b=="SEEK_HELP":
        if scene.id=="evernight_church" and npc.states.get("satiety",50)<30:
            meal=world.objects["object:church_community_meal"]
            if meal.quantity>0:
                meal.quantity-=1
                aid=make_event(world,"AID_RECEIVED",
                               f"{npc.name} 在 {scene.name} 获得并吃下了一份 {meal.name}。",
                               [npc.id],scene.id,severity=2,emotion=4,tags=["aid","food","community"],
                               object_ids=[meal.id],level=EventLevel.BACKGROUND.value)
                change_state(world,npc,"satiety",40,"接受教会食物救济",aid)
                change_state(world,npc,"social_support",5,"社区在困难时提供帮助",aid)
        elif scene.id=="hospital" and npc.health<100:
            medicine=world.objects["object:hospital_medicine"]
            if medicine.quantity>0:
                medicine.quantity-=1
                old_health=npc.health
                npc.health=min(100,npc.health+25)
                npc.investigation_progress.pop("critical_injury_day",None)
                change_state(world,npc,"pain",-30,"医院治疗缓解伤痛")
                change_state(world,npc,"stress",-8,"伤势得到专业处理")
                make_event(world,"MEDICAL_AID_RECEIVED",
                           f"{npc.name} 在医院接受治疗，健康从 {old_health} 恢复到 {npc.health}。",
                           [npc.id],scene.id,severity=2,emotion=3,tags=["medical","aid"],
                           object_ids=[medicine.id],level=EventLevel.BACKGROUND.value)
        elif scene.id=="evernight_church" and npc.sanity<100:
            old_sanity=npc.sanity
            npc.sanity=min(100,npc.sanity+12)
            make_event(world,"SPIRITUAL_AID_RECEIVED",
                       f"{npc.name} 在教堂接受安抚，理智从 {old_sanity} 恢复到 {npc.sanity}。",
                       [npc.id],scene.id,severity=2,emotion=3,tags=["spiritual","aid"],
                       level=EventLevel.BACKGROUND.value)
    elif b=="FLEE":
        recent=any(e.event_type=="SUSPECT_FLED" and npc.id in e.actor_ids
                   for day in range(max(1,world.day-2),world.day+1)
                   for e in world.events_by_day.get(day,[]))
        if not recent:
            flight=make_event(world,"SUSPECT_FLED",
                              f"{npc.name} 因法律风险过高而逃往 {scene.name}，暂时避开公开活动。",
                              [npc.id],scene.id,severity=7,conflict=7,danger=5,secret=7,emotion=8,
                              tags=["suspect","flight","police"],
                              conflict_ids=["conflict:warehouse_anomaly"])
            change_state(world,npc,"stress",12,"逃避警方追查",flight)
    elif b=="PRAY":
        npc.sanity=min(100,npc.sanity+2)


def pair_event_recent(world,event_type,a_id,b_id,days=2):
    pair={a_id,b_id}
    start=max(1,world.day-days+1)
    for day in range(start,world.day+1):
        for event in world.events_by_day.get(day,[]):
            if event.event_type==event_type and pair.issubset(set(event.actor_ids)):
                return True
    return False


def legacy_information_share_score(speaker,listener,topic):
    secret_markers=("藏","违禁","仪式","非凡","官方调查","极光会","嫌疑人")
    secrecy=80 if any(marker in topic for marker in secret_markers) else 25
    relation=speaker.relationships.get(listener.id,Relationship(trust=35))
    same_faction=bool(set(speaker.faction_ids)&set(listener.faction_ids))
    score=(relation.trust+speaker.states.get("civic_duty",50)*0.2
           +speaker.personality.get("social",50)*0.15-relation.suspicion*0.4-secrecy*0.55)
    if same_faction: score+=35
    if speaker.layer==NPCLayer.HOSTILE_BEYONDER.value and not same_faction: score-=35
    return max(0,min(100,score))


def resolve_interaction(world,scene,a,b,score):
    ra, rb = relationship_between(a,b), relationship_between(b,a)
    investigator=secret_holder=None
    if "调查东码头最近的失踪与异常传闻" in a.goals and "掩盖三号仓库的违禁货物出入记录" in b.goals:
        investigator,secret_holder=a,b
    elif "调查东码头最近的失踪与异常传闻" in b.goals and "掩盖三号仓库的违禁货物出入记录" in a.goals:
        investigator,secret_holder=b,a
    evidence=world.objects["object:warehouse_contraband_ledger_page"]
    evidence_known=(investigator is not None and investigator.id in evidence.discovered_by)
    if evidence_known and not pair_event_recent(world,"EVIDENCE_CONFRONTATION",
                                                 investigator.id,secret_holder.id,days=3):
        make_event(world,"EVIDENCE_CONFRONTATION",
                   f"{investigator.name} 当面质问 {secret_holder.name}：为何把 {evidence.name} 藏在三号仓库的废弃药柜中？",
                   [investigator.id,secret_holder.id],scene.id,
                   severity=7,conflict=9,secret=7,danger=4,emotion=8,
                   tags=["investigation","evidence","confrontation"],object_ids=[evidence.id],
                   knowledge_ids=[evidence.knowledge_id] if evidence.knowledge_id else [],
                   organization_ids=[secret_holder.organization] if secret_holder.organization else [],
                   conflict_ids=["conflict:warehouse_anomaly"])
        relationship_between(investigator,secret_holder).trust=max(
            0,relationship_between(investigator,secret_holder).trust-8)
        relationship_between(secret_holder,investigator).fear=min(
            100,relationship_between(secret_holder,investigator).fear+10)
        return
    if investigator and evidence_known:
        return
    if investigator and scene.id in ("east_dock","warehouse_3"):
        if not pair_event_recent(world,"SUSPICIOUS_ENCOUNTER",investigator.id,secret_holder.id,days=3):
            make_event(world,"SUSPICIOUS_ENCOUNTER",
                       f"{investigator.name} 在 {scene.name} 看见 {secret_holder.name} 反复检查废弃药柜并回避询问。",
                       [investigator.id,secret_holder.id],scene.id,
                       severity=6,conflict=8,secret=7,danger=4,emotion=5,
                       tags=["investigation","secret","conflict","dock"],
                       knowledge_ids=[f"suspicion:{secret_holder.id}:warehouse"],
                       organization_ids=[secret_holder.organization] if secret_holder.organization else [],
                       conflict_ids=["conflict:warehouse_anomaly"])
            relationship_between(investigator,secret_holder).suspicion += 18
            relationship_between(secret_holder,investigator).suspicion += 12
            fact=f"{secret_holder.name} 反复检查三号仓库的废弃药柜并回避询问"
            if fact not in investigator.knowledge: investigator.knowledge.append(fact)
        return
    if max(ra.suspicion,rb.suspicion)>40 and not pair_event_recent(
            world,"CONFRONTATION",a.id,b.id,days=3):
        make_event(world,"CONFRONTATION",f"{a.name} 与 {b.name} 在 {scene.name} 发生了紧张的对峙。",
                   [a.id,b.id],scene.id,severity=4,conflict=6,danger=2,emotion=6,
                   tags=["relationship","conflict"],
                   conflict_ids=["conflict:relationship:" + ":".join(sorted([a.id,b.id]))])
        return
    if "social" in scene.tags or "information" in scene.tags or scene.id=="market":
        structured=[]
        for speaker,listener in ((a,b),(b,a)):
            for fact in world.intelligence.known_facts(speaker.id):
                if listener.id not in fact.known_by:
                    structured.append((speaker,listener,fact))
        if structured:
            speaker,listener,fact=world.rng.choice(structured)
            willingness=world.intelligence.can_share(speaker,listener,fact)
            if world.rng.uniform(0,100)<willingness:
                world.intelligence.share(fact.id,speaker,listener,truthful=True)
                content=fact.summary or f"{fact.subject_id} {fact.predicate} {fact.object_id}"
                make_event(world,"INFORMATION_SHARED",
                           f"{speaker.name} 向 {listener.name} 透露了一条情报：{content}。",
                           [speaker.id,listener.id],scene.id,severity=3,emotion=2,
                           secret=fact.secrecy,tags=["social","information","structured_intel"],
                           knowledge_ids=[fact.id])
                return
        choices=[]
        choices.extend((a,b,k) for k in a.knowledge if k not in b.knowledge
                       and world.rng.uniform(0,100)<legacy_information_share_score(a,b,k))
        choices.extend((b,a,k) for k in b.knowledge if k not in a.knowledge
                       and world.rng.uniform(0,100)<legacy_information_share_score(b,a,k))
        if choices:
            speaker,listener,topic=world.rng.choice(choices)
            listener.knowledge.append(topic)
            make_event(world,"INFORMATION_SHARED",
                       f"{speaker.name} 告诉 {listener.name}：{topic}",
                       [speaker.id,listener.id],scene.id,severity=3,emotion=2,
                       tags=["social","information"],
                       knowledge_ids=["knowledge:statement:"+uuid.uuid5(uuid.NAMESPACE_DNS,topic).hex[:10]])
        else:
            make_event(world,"SMALL_TALK",f"{a.name} 与 {b.name} 在 {scene.name} 进行了一次普通闲聊。",
                       [a.id,b.id],scene.id,severity=1,emotion=1,tags=["social"])
        return
    make_event(world,"CASUAL_MEETING",f"{a.name} 与 {b.name} 在 {scene.name} 偶遇。",
               [a.id,b.id],scene.id,severity=1,emotion=1,tags=["social"])


def trigger_scene_event(world,scene,occupants):
    if not occupants: return
    target=world.rng.choice(occupants)
    criminals=[npc for npc in occupants if npc.sequence_pathway=="罪犯"]
    if "pickpocket" in scene.event_tags and criminals:
        offender=world.rng.choice(criminals)
        victims=[npc for npc in occupants if npc.id!=offender.id and npc.wealth>15]
        if not victims:
            return
        target=world.rng.choice(victims)
        loss=min(target.wealth,world.rng.randint(5,20))
        target.wealth-=loss
        event=make_event(world,"PICKPOCKETED",f"{offender.name} 在 {scene.name} 扒窃 {target.name}，使其损失 {loss} 财富。",
                         [offender.id,target.id],scene.id,severity=5,conflict=5,emotion=5,
                         tags=["crime","wealth","interaction"],
                         conflict_ids=[f"conflict:pickpocket:{world.day}:{target.id}"])
        create_crime_trace(world,offender,scene,"pickpocket")
        create_observations(world,event,occupants)
    elif "fight" in scene.event_tags and len(occupants)>=2:
        a,b=world.rng.sample(occupants,2)
        a.health=max(0,a.health-world.rng.randint(5,35))
        b.health=max(0,b.health-world.rng.randint(5,35))
        event=make_event(world,"TAVERN_FIGHT",f"{a.name} 与 {b.name} 在 {scene.name} 的冲突演变成斗殴。",
                         [a.id,b.id],scene.id,severity=4,conflict=7,danger=5,emotion=6,
                         tags=["fight","crime"],
                         conflict_ids=["conflict:fight:"+":".join(sorted([a.id,b.id]))])
        create_observations(world,event,occupants)
        for victim,opponent in ((a,b),(b,a)):
            if victim.health<=0:
                set_disposition(victim,"dead",world.day,event.event_id)
                make_event(world,"DEATH_FROM_ASSAULT",
                           f"{victim.name} 在与 {opponent.name} 的斗殴中伤势过重死亡。",
                           [victim.id,opponent.id],scene.id,severity=10,conflict=10,danger=10,
                           emotion=10,tags=["death","assault","crime"],parent_id=event.event_id,
                           conflict_ids=event.conflict_ids)
            else:
                injury_event=make_event(world,"INJURED_IN_ASSAULT",
                           f"{victim.name} 在斗殴中受伤，当前健康为 {victim.health}。",
                           [victim.id,opponent.id],scene.id,severity=6,conflict=7,danger=6,
                           emotion=7,tags=["injury","assault","crime"],parent_id=event.event_id,
                           conflict_ids=event.conflict_ids)
                schedule_injury_response(world,victim,injury_event)
    elif "occult" in scene.event_tags and world.rng.random()<0.35:
        target.sanity=max(0,target.sanity-world.rng.randint(2,8))
        event=make_event(world,"OCCULT_DISTURBANCE",f"{target.name} 在 {scene.name} 感受到一次难以解释的神秘异常。",
                         [target.id],scene.id,severity=5,danger=4,secret=8,emotion=6,
                         tags=["occult","mystery"],
                         conflict_ids=[f"conflict:occult_disturbance:{scene.id}"])
        create_observations(world,event,occupants)


def fire_scheduled_phase_events(world,phase):
    for item in world.scheduled_events:
        if item["day"]==world.day and item["phase"]==phase.value:
            make_event(world,"SCHEDULED_EVENT",item["message"],[],item["scene_id"],
                       severity=item["severity"],conflict=3,danger=2,secret=2,emotion=2,tags=item["tags"],
                       conflict_ids=["conflict:warehouse_anomaly"] if item["scene_id"]=="east_dock" else [])


def advance_illegal_operations(world,phase):
    if phase!=Phase.LATE_NIGHT:
        return
    stage_days=[-4,-3,-2,0,1]
    action_ids=["SELECT_RITUAL_TARGET","COLLECT_RITUAL_MATERIALS","PREPARE_RITUAL_SITE",
                "PERFORM_SECRET_RITUAL","CLEAN_TRACE_OR_ESCAPE"]
    for operation in world.ritual_engine.active():
        stage=operation.current_stage
        if not stage:
            continue
        due_day=operation.scheduled_day+stage_days[operation.current_stage_index]
        if world.day<due_day:
            continue
        leader=world.npcs.get(operation.leader_id)
        if not leader or not leader.alive:
            operation.status="failed"
            continue
        if not npc_can_act(leader) or leader.health<=30:
            world.ledger.emit(day=world.day,phase=phase.value,system="plot_module",
                              event_type="LONG_TERM_PLAN_PAUSED",
                              message=f"{leader.name} 当前处于 {leader.disposition_status} 或重伤状态，"
                                      f"长期行动 {operation.id} 暂停。",
                              actor_ids=[leader.id],scene_id=leader.current_scene,
                              payload={"operation_id":operation.id,"reason":"unable_to_act"})
            continue
        action_id=action_ids[operation.current_stage_index]
        if action_id=="SELECT_RITUAL_TARGET" and not operation.target_id:
            target_layer=(NPCLayer.OFFICIAL_BEYONDER.value
                          if operation.objective=="ritual_ambush" else NPCLayer.ORDINARY.value)
            candidates=[npc for npc in world.npcs.values()
                        if npc_can_act(npc) and npc.id not in operation.participant_ids
                        and npc.layer==target_layer]
            if candidates:
                operation.target_id=world.rng.choice(candidates).id
        roll=world.rng.randint(1,100)
        modifier=(leader.skills.get("ritual",0)+sequence_modifier(leader,"ritual")
                  +leader.skills.get("stealth",0)//2)
        difficulty=[45,55,65,75,60][operation.current_stage_index]
        margin=roll+modifier-difficulty
        outcome=check_outcome(margin)
        trace=world.ritual_engine.advance(operation,day=world.day,phase=phase.value,
                                          action_id=action_id,actor_ids=[leader.id],outcome=outcome)
        descriptions={
            "SELECT_RITUAL_TARGET":"秘密筛选适合仪式的目标",
            "COLLECT_RITUAL_MATERIALS":"通过隐蔽渠道收集仪式材料",
            "PREPARE_RITUAL_SITE":f"在{world.scenes[operation.scene_id].name}准备非法仪式场地",
            "PERFORM_SECRET_RITUAL":"尝试举行危险的秘密仪式",
            "CLEAN_TRACE_OR_ESCAPE":"清理仪式痕迹并准备撤离",
        }
        event=make_event(world,"ILLEGAL_OPERATION_STAGE",
            f"{leader.name} {descriptions[action_id]}：{outcome}。",
            [leader.id],operation.scene_id,severity=6 if action_id!="PERFORM_SECRET_RITUAL" else 9,
            conflict=7,danger=8 if action_id=="PERFORM_SECRET_RITUAL" else 4,secret=9,emotion=6,
            tags=["hostile_beyonder","illegal_operation","ritual",action_id.lower()],
            object_ids=[trace.id] if trace else [],organization_ids=[operation.owner_faction_id],
            conflict_ids=["conflict:tingen_occult_war"])
        operation.result_event_ids.append(event.event_id)
        world.ledger.emit(day=world.day,phase=phase.value,system="plot_module",
                          event_type="OPERATION_STAGE_RESOLVED",message=event.description,
                          actor_ids=[leader.id],scene_id=operation.scene_id,
                          payload={"operation_id":operation.id,"stage":stage.id,"roll":roll,
                                   "modifier":modifier,"difficulty":difficulty,"margin":margin,
                                   "outcome":outcome,"trace_id":trace.id if trace else None})
        if operation.status=="completed":
            operation.outcome_type="ritual_succeeded"
            resolve_operation_consequences(world,operation)


def advance_followup_chains(world,phase):
    if phase!=Phase.AFTERNOON:
        return
    stage_labels={
        "gather_escape_leads":"收集逃亡路线线索","track_fugitive":"追踪逃犯",
        "confront_fugitive":"截获逃犯","secure_scene":"封锁污染现场",
        "analyze_contamination":"分析污染结构","cleanse_scene":"净化现场",
        "inspect_ritual_site":"勘察仪式现场","recover_ritual_result":"回收仪式成果",
        "erase_remaining_traces":"清除组织痕迹","gather_custody_intel":"收集关押情报",
        "infiltrate_custody":"潜入关押地点","free_prisoner":"释放被捕成员",
        "review_failed_intervention":"复盘失败行动","prepare_second_assault":"准备第二次突击",
        "stop_active_ritual":"再次阻止仪式"}
    plans=sorted(world.followup_engine.active(),
                 key=lambda plan:world.long_term_goals.get(plan.goal_id).priority
                 if world.long_term_goals.get(plan.goal_id) else 0,reverse=True)
    acted=set()
    for plan in plans:
        if plan.owner_id in acted:
            continue
        owner=world.npcs.get(plan.owner_id)
        goal=world.long_term_goals.get(plan.goal_id)
        stage=plan.current_stage
        if not owner or not npc_can_act(owner) or not goal or not stage:
            continue
        acted.add(plan.owner_id)
        skill_name={"hunt_ritual_leader":"tracking","cleanse_occult_scene":"mysticism",
                    "collect_ritual_result":"stealth","rescue_arrested_member":"stealth",
                    "reinforce_ritual_case":"combat"}.get(plan.template_id,"investigation")
        roll=world.rng.randint(1,100)
        total=roll+owner.skills.get(skill_name,0)+sequence_modifier(owner,skill_name)
        difficulty=58+plan.current_stage_index*5
        blocked_reason=None
        artifact=next((obj for obj in world.objects.values()
                       if "ritual_result" in obj.tags and not obj.destroyed),None)
        if stage.id=="recover_ritual_result" and (not artifact or artifact.holder_id not in (None,owner.id)):
            blocked_reason="仪式成果已经被其他势力取走"
        target=world.npcs.get(plan.target_id)
        if stage.id=="free_prisoner" and (not target or target.disposition_status!="arrested"):
            blocked_reason="目标已不在关押状态"
        success=total>=difficulty and blocked_reason is None
        world.followup_engine.advance(plan,day=world.day,success=success)
        outcome="success" if success else "failure"
        event=make_event(world,"FOLLOWUP_PLAN_STAGE",
            f"{owner.name} 尝试{stage_labels.get(stage.id,stage.id)}：{outcome}。"
            + (f" 原因：{blocked_reason}。" if blocked_reason else ""),
            [owner.id]+([target.id] if target else []),plan.scene_id,
            severity=7 if success else 5,conflict=7,danger=5,secret=7,emotion=6,
            tags=["followup_plan",plan.template_id,stage.id,outcome],
            conflict_ids=["conflict:tingen_occult_war"])
        plan.result_event_ids.append(event.event_id)
        completed=sum(item.status=="completed" for item in plan.stages)
        goal.progress=round(100*completed/max(1,len(plan.stages)))
        goal.last_progress_day=world.day if success else goal.last_progress_day
        if not success and plan.attempts>=9:
            plan.status="failed"; plan.outcome_type="repeated_failure"
            goal.status="failed"; goal.outcome=blocked_reason or "多次行动失败"
        if plan.status!="completed":
            continue
        goal.status="completed"; goal.progress=100
        if plan.template_id=="hunt_ritual_leader" and target:
            target.current_scene="blackthorn_security"
            set_disposition(target,"arrested",world.day,event.event_id)
            plan.outcome_type="fugitive_captured"; goal.outcome="逃犯被捕"
            make_event(world,"FUGITIVE_CAPTURED",
                f"{owner.name} 在追捕行动中截获 {target.name}，并将其押回黑荆棘安保公司。",
                [owner.id,target.id],plan.scene_id,severity=10,conflict=10,danger=8,
                secret=5,emotion=9,tags=["capture","followup_consequence"],
                conflict_ids=["conflict:tingen_occult_war"])
        elif plan.template_id=="cleanse_occult_scene":
            scene=world.scenes.get(plan.scene_id)
            if scene: scene.occult_contamination=0
            if artifact and artifact.holder_id is None:
                artifact.holder_id=owner.id; artifact.scene_id=None; artifact.hidden=False
            plan.outcome_type="scene_cleansed"; goal.outcome="污染现场已净化"
            make_event(world,"OCCULT_SCENE_CLEANSED",
                f"{owner.name} 完成对 {scene.name if scene else plan.scene_id} 的净化与收容。",
                [owner.id],plan.scene_id,severity=9,conflict=7,danger=8,
                secret=6,emotion=8,tags=["cleanse","followup_consequence"],
                object_ids=[artifact.id] if artifact and artifact.holder_id==owner.id else [],
                conflict_ids=["conflict:tingen_occult_war"])
        elif plan.template_id=="collect_ritual_result":
            if artifact:
                artifact.holder_id=owner.id; artifact.scene_id=None; artifact.hidden=False
            plan.outcome_type="ritual_result_recovered"; goal.outcome="仪式成果已被组织回收"
            make_event(world,"RITUAL_RESULT_RECOVERED",
                f"{owner.name} 取得仪式灵性结晶并清除了组织留下的主要痕迹。",
                [owner.id],plan.scene_id,severity=9,conflict=9,danger=8,
                secret=10,emotion=7,tags=["artifact","hostile_success","followup_consequence"],
                object_ids=[artifact.id] if artifact else [],organization_ids=[owner.organization],
                conflict_ids=["conflict:tingen_occult_war"])
        elif plan.template_id=="rescue_arrested_member" and target:
            target.current_scene="underground_market"
            set_disposition(target,"active",world.day,event.event_id)
            plan.outcome_type="prisoner_freed"; goal.outcome="被捕成员获救"
            make_event(world,"ARRESTED_MEMBER_RESCUED",
                f"{owner.name} 成功将 {target.name} 从关押中救出。",
                [owner.id,target.id],plan.scene_id,severity=10,conflict=10,danger=9,
                secret=9,emotion=9,tags=["rescue","hostile_success","followup_consequence"],
                conflict_ids=["conflict:tingen_occult_war"])
            if not any(operation.status=="active" and operation.leader_id==target.id
                       for operation in world.ritual_engine.operations.values()):
                prior_operations=sum(operation.leader_id==target.id
                                     for operation in world.ritual_engine.operations.values())
                escalated=prior_operations>=2
                operation=world.ritual_engine.create_operation(
                    faction_id=owner.organization or "aurora_order_tingen",
                    leader_id=target.id,participant_ids=[target.id,owner.id],
                    scene_id="red_moon_street" if not escalated else "underground_market",
                    scheduled_day=world.day+8,
                    scheduled_phase="late_night")
                operation.objective="ritual_ambush" if escalated else "establish_occult_safehouse"
                new_goal=LongTermGoal(
                    id=f"goal:{operation.id}",owner_id=target.id,
                    goal_type="ritual_ambush" if escalated else "rebuild_hostile_cell",
                    description=("利用仪式伏击追捕自己的官方非凡者"
                                 if escalated else "与营救者建立新安全屋并恢复组织网络"),
                    priority=98,created_day=world.day,deadline_day=operation.scheduled_day,
                    linked_plan_id=operation.id)
                world.long_term_goals[new_goal.id]=new_goal
                operation.linked_goal_id=new_goal.id
                target.long_term_goal_ids.append(new_goal.id)
                make_event(world,"HOSTILE_CELL_REGROUPED",
                    (f"{target.name} 与 {owner.name} 在反复被捕后决定设下仪式伏击，主动攻击追捕者。"
                     if escalated else
                     f"{target.name} 与 {owner.name} 在获救后转入红月亮街，开始建立新的隐秘安全屋。"),
                    [target.id,owner.id],operation.scene_id,severity=9,conflict=10,
                    danger=9,secret=10,emotion=8,tags=["hostile_beyonder","regroup","new_operation"],
                    organization_ids=[owner.organization] if owner.organization else [],
                    conflict_ids=["conflict:tingen_occult_war"])
            officials=[npc for npc in world.npcs.values()
                       if npc_can_act(npc) and is_official_responder(npc)]
            if officials and not any(goal.status=="active" and goal.goal_type=="hunt_ritual_leader"
                                     and goal.description.endswith(target.name)
                                     for goal in world.long_term_goals.values()):
                hunter=max(officials,key=lambda npc:npc.skills.get("tracking",0))
                create_followup_goal(world,hunter.id,"hunt_ritual_leader",
                                     f"追捕被营救后再次潜逃的 {target.name}",100,
                                     scene_id="underground_market",target_id=target.id)


def simulate_scene(world,scene,occupants,detailed):
    world.ledger.emit(day=world.day,phase=world.phase.value,system="scene_simulation",
                      event_type="VISIBLE_SCENE_SIM" if detailed else "OFFSCREEN_SCENE_SIM",
                      message=f"{'详细' if detailed else '抽象'}模拟场景 {scene.name}。",
                      actor_ids=[n.id for n in occupants],scene_id=scene.id)
    for npc in occupants:
        plan=resolve_phase_plan(world,npc,world.phase)
        result=execute_behavior(world,npc,scene,plan)
        for step in npc.action_chain:
            if (step.get("active") and step.get("phase")==world.phase.value
                    and step.get("scene_id")==scene.id and step.get("action_id")==plan.behavior):
                step["active"]=False
                break
        for drive in npc.response_drives:
            if (drive.active and drive.execute_phase==world.phase.value
                    and drive.scene_id==scene.id and drive.behavior==plan.behavior):
                drive.active=False
                break
        if result and result.severity>=4:
            create_observations(world,result,occupants)
    pairs=[]
    for i in range(len(occupants)):
        for j in range(i+1,len(occupants)):
            a,b=occupants[i],occupants[j]
            s=interaction_score(world,a,b,scene)
            if s>35: pairs.append((s,a,b))
    pairs.sort(key=lambda x:x[0],reverse=True)
    for score,a,b in pairs[:world.cfg.max_interactions_per_scene]:
        resolve_interaction(world,scene,a,b,score)
    if "private_home" not in scene.tags and world.rng.random()<0.08:
        trigger_scene_event(world,scene,occupants)


def simulate_phase(world,phase):
    world.phase=phase
    phase_event_start=len(world.events_by_day[world.day])
    if world.cfg.verbose: print(f"\n=== Day {world.day} / {phase.value} ===")
    fire_scheduled_phase_events(world,phase)
    advance_illegal_operations(world,phase)
    advance_followup_chains(world,phase)
    groups=defaultdict(list)
    for npc in world.npcs.values():
        if not npc_can_act(npc): continue
        plan=resolve_phase_plan(world,npc,phase)
        npc.current_scene=plan.scene_id
        make_event(world,"NPC_MOVED",f"{npc.name} 前往 {world.scenes[plan.scene_id].name}，计划：{plan.intent}",
                   [npc.id],plan.scene_id,severity=1,tags=["movement","plan"])
        if plan.behavior=="MEET_PERSON":
            for commitment in npc.commitments:
                if (commitment.active and commitment.execute_phase==phase.value
                        and commitment.scene_id==plan.scene_id):
                    commitment.active=False
                    world.ledger.emit(day=world.day,phase=phase.value,system="commitment_system",
                                      event_type="COMMITMENT_FULFILLED",
                                      message=f"{npc.name} 已履行约定：{commitment.promise}",
                                      actor_ids=[npc.id],scene_id=plan.scene_id)
                    source=world.npcs.get(commitment.source_id)
                    related_case=next((case for case in world.cases.values()
                                       if npc.id in case.suspect_ids),None)
                    if source and is_official_responder(source) and related_case:
                        questioned=make_event(world,"CUSTODIAN_QUESTIONED",
                                             f"警察 {source.name} 在警察局依据扣押物证正式询问 {npc.name}。",
                                             [source.id,npc.id],plan.scene_id,severity=7,conflict=8,
                                             secret=5,emotion=8,tags=["police","suspect","questioning"],
                                             object_ids=related_case.evidence_ids,
                                             conflict_ids=related_case.conflict_ids)
                        change_state(world,npc,"legal_risk",65,"被警方依据实物证据列为嫌疑人",questioned)
                        change_state(world,npc,"fear",20,"接受警方正式询问",questioned)
        groups[plan.scene_id].append(npc)
    for sid,scene in world.scenes.items():
        if groups.get(sid):
            simulate_scene(world,scene,groups[sid],sid==world.player_scene)
    for npc in world.npcs.values():
        if npc_can_act(npc):
            npc.states["energy"]=max(0,npc.states.get("energy",70)-3)
            npc.states["satiety"]=max(0,npc.states.get("satiety",70)-4)
            npc.needs["hunger"]=100-npc.states["satiety"]
            npc.needs["fatigue"]=100-npc.states["energy"]
            if npc.states["energy"]<20:
                npc.states["stress"]=min(100,npc.states.get("stress",20)+3)
            if npc.states["satiety"]<20:
                npc.states["morale"]=max(0,npc.states.get("morale",50)-2)
            if npc.states["satiety"]==0:
                npc.states["energy"]=max(0,npc.states["energy"]-5)
                npc.health=max(1,npc.health-2)
    generate_harm_and_report_reactions(world,world.events_by_day[world.day][phase_event_start:])


def run_night_fate_events(world):
    world.phase=Phase.LATE_NIGHT
    distressed=sorted((npc for npc in world.npcs.values() if npc_can_act(npc) and npc.sanity<30),
                      key=lambda npc:npc.sanity)[:2]
    for npc in distressed:
        helpers=[]
        for helper_id,relation in npc.relationships.items():
            helper=world.npcs.get(helper_id)
            if helper and npc_can_act(helper) and set(relation.kinds)&{"朋友","爱人"}:
                helpers.append(helper)
        if not helpers:
            continue
        helper=max(helpers,key=lambda item:item.relationships[npc.id].trust)
        if pair_event_recent(world,"FRIEND_CRISIS_INTERVENTION",npc.id,helper.id,days=3):
            continue
        event=make_event(world,"FRIEND_CRISIS_INTERVENTION",
            f"{helper.name} 察觉 {npc.name} 精神状态恶化，夜间前往其住所陪伴，并劝其次日寻求治疗。",
            [npc.id,helper.id],npc.home_scene,severity=6,danger=4,emotion=9,
            tags=["mental_health","friend","intervention","interactive"],
            conflict_ids=[f"conflict:mental_health:{npc.id}"])
        npc.response_drives.append(ResponseDrive(
            f"drive_{uuid.uuid4().hex[:10]}",event.event_id,"seek_mental_treatment",
            "evernight_church","SEEK_HELP","在亲友劝说下寻求精神与宗教帮助",
            96,"afternoon",world.day+2,True))
        change_state(world,helper,"stress",8,f"照顾精神状态恶化的 {npc.name}",event)

    public_groups=defaultdict(list)
    for npc in world.npcs.values():
        scene=world.scenes.get(npc.current_scene)
        if npc_can_act(npc) and scene and "private_home" not in scene.tags:
            public_groups[scene.id].append(npc)
    possible=[(scene_id,people) for scene_id,people in public_groups.items() if len(people)>=2]
    if possible and world.rng.random()<0.18:
        scene_id,people=world.rng.choice(possible)
        affected,witness=world.rng.sample(people,2)
        loss=world.rng.randint(4,12); affected.sanity=max(0,affected.sanity-loss)
        event=make_event(world,"NIGHT_OCCULT_INCIDENT",
            f"{affected.name} 在 {world.scenes[scene_id].name} 遭遇异常灵性现象；"
            f"{witness.name} 目击其短暂失控并将其带离现场。",
            [affected.id,witness.id],scene_id,severity=7,danger=6,secret=7,emotion=8,
            tags=["occult","witness","rescue","interactive"],
            conflict_ids=[f"conflict:night_occult:{scene_id}"])
        create_observations(world,event,people)
        opposed_layers={affected.layer,witness.layer}
        if (NPCLayer.OFFICIAL_BEYONDER.value in opposed_layers
                and NPCLayer.HOSTILE_BEYONDER.value in opposed_layers):
            rescued_rel=relationship_between(affected,witness)
            rescuer_rel=relationship_between(witness,affected)
            rescued_rel.trust=min(100,rescued_rel.trust+12)
            rescued_rel.suspicion=min(100,rescued_rel.suspicion+18)
            rescued_rel.affection=min(100,rescued_rel.affection+6)
            rescuer_rel.trust=min(100,rescuer_rel.trust+5)
            fact=world.intelligence.create(
                subject_id=witness.id,predicate="rescued_rival",object_id=affected.id,
                day=world.day,phase=world.phase.value,source_type="direct_experience",
                source_id=affected.id,confidence=1.0,secrecy=85,
                known_by=[affected.id,witness.id],evidence_ids=[],
                summary=f"{witness.name} 在灵性异常中救助了敌对阵营的 {affected.name}")
            debt=make_event(world,"CROSS_FACTION_DEBT_CREATED",
                f"{affected.name} 知道自己欠敌对阵营的 {witness.name} 一次救命人情；"
                f"双方的信任与怀疑同时上升。",
                [affected.id,witness.id],scene_id,severity=8,conflict=9,danger=5,
                secret=9,emotion=9,tags=["relationship","cross_faction","debt","secret"],
                knowledge_ids=[fact.id],conflict_ids=["conflict:tingen_occult_war"],
                parent_id=event.event_id)
            belief=f"{witness.name} 曾在灵性异常中救过自己，这份人情可能影响未来选择"
            if belief not in affected.beliefs:
                affected.beliefs.append(belief)
        affected.response_drives.append(ResponseDrive(
            f"drive_{uuid.uuid4().hex[:10]}",event.event_id,"understand_occult_incident",
            "divination_club","INVESTIGATE_LOCATION","调查昨夜自己亲历的灵性异常",
            88,"afternoon",world.day+2,True))


def narrative_score(e):
    if e.level == EventLevel.BACKGROUND.value:
        return 0.0
    return e.severity*2+e.conflict*2+e.danger*1.5+e.secret*1.8+e.emotion*1.2


def find_related_thread(world,e):
    if e.level == EventLevel.BACKGROUND.value:
        return None
    best=None; best_score=0
    for t in world.story_threads.values():
        if not t.active: continue
        score = 0
        if e.parent_id and e.parent_id in t.event_ids:
            score += 100
        score += len(set(e.object_ids) & set(t.object_ids)) * 30
        score += len(set(e.knowledge_ids) & set(t.knowledge_ids)) * 25
        score += len(set(e.conflict_ids) & set(t.conflict_ids)) * 40
        score += len(set(e.organization_ids) & set(t.organization_ids)) * 15

        # These are deliberately weak signals: neither a shared person, scene nor
        # broad genre tag is sufficient to merge two causal stories.
        score += len(set(e.actor_ids) & set(t.participants)) * 2
        if e.scene_id and e.scene_id in t.scenes:
            score += 1
        score += len(set(e.tags) & set(t.specific_tags))
        if score > best_score:
            best_score,best=score,t
    return best if best_score>=20 else None


def specific_story_tags(tags):
    broad = {"secret","crime","occult","social","information","conflict",
             "plan","movement","night_fate","organization","relationship"}
    return sorted(tag for tag in set(tags) if tag not in broad)


def repetition_multiplier(thread,e):
    previous = thread.event_type_counts.get(e.event_type,0)
    return max(0.15, 1.0-previous*0.20)


def update_thread_stage(thread):
    old_stage=thread.stage
    if thread.pressure>=80 and thread.escalation_level>=3:
        thread.stage="crisis"
    elif thread.pressure>=55 and thread.escalation_level>=2:
        thread.stage="escalating"
    elif len(thread.event_ids)>=3:
        thread.stage="active"
    else:
        thread.stage="emerging"
    return old_stage!=thread.stage


def make_thread_title(e):
    if "occult" in e.tags: return "无法解释的神秘异常"
    if "crime" in e.tags: return "正在扩大的犯罪冲突"
    if "investigation" in e.tags: return "未解决的调查线索"
    if "secret" in e.tags: return "被隐藏的秘密"
    return f"围绕{e.event_type}的冲突"


def make_open_questions(e):
    qs=["这件事真正的原因是什么？"]
    if e.secret>5: qs.append("谁在隐藏信息？")
    if e.conflict>5: qs.append("冲突双方接下来会做什么？")
    if e.danger>5: qs.append("危险是否还会升级？")
    return qs


def maybe_publish_commission(world,t):
    if t.quest_published or t.score<world.cfg.quest_threshold: return
    possible=[world.npcs[x] for x in t.participants if x in world.npcs and world.npcs[x].alive]
    if not possible: return
    giver=max(possible,key=lambda n:n.personality["morality"]+n.personality["social"]-(25 if n.organization=="aurora_cell" else 0))
    c=Commission(f"commission_{len(world.commissions)+1:03d}",t.id,giver.id,
                 f"委托：{t.title}",f"{giver.name} 希望有人帮助调查或处理：{t.unresolved_questions[0]}",
                 max(10,int(t.score)),world.day)
    world.commissions.append(c); t.quest_published=True
    world.ledger.emit(day=world.day,phase="night_resolution",system="quest_system",
                      event_type="COMMISSION_PUBLISHED",message=f"{giver.name} 因剧情线“{t.title}”发布了一个委托。",
                      actor_ids=[giver.id],payload=asdict(c))


def update_story_threads_from_events(world,events):
    for e in events:
        if e.level == EventLevel.BACKGROUND.value:
            continue
        score=narrative_score(e); t=find_related_thread(world,e)
        if t:
            multiplier=repetition_multiplier(t,e)
            effective_score=score*multiplier
            t.event_ids.append(e.event_id)
            t.participants=sorted(set(t.participants+e.actor_ids))
            if e.scene_id: t.scenes=sorted(set(t.scenes+[e.scene_id]))
            t.tags=sorted(set(t.tags+e.tags))
            t.object_ids=sorted(set(t.object_ids+e.object_ids))
            t.knowledge_ids=sorted(set(t.knowledge_ids+e.knowledge_ids))
            t.organization_ids=sorted(set(t.organization_ids+e.organization_ids))
            t.conflict_ids=sorted(set(t.conflict_ids+e.conflict_ids))
            t.specific_tags=sorted(set(t.specific_tags+specific_story_tags(e.tags)))
            t.score += effective_score*0.2
            t.pressure=min(100,t.pressure+max(1,int(effective_score/10)))
            previous=t.event_type_counts.get(e.event_type,0)
            t.event_type_counts[e.event_type]=previous+1
            t.repetition_count=previous+1 if previous else 0
            if score>=world.cfg.story_create_threshold and previous==0:
                t.escalation_level+=1
                t.last_major_event_day=world.day
            stage_changed=update_thread_stage(t)
            world.ledger.log_story_line(t.id,f"Day {world.day} {e.phase}: {e.description} [{e.event_id}]")
            if stage_changed:
                world.ledger.emit(day=world.day,phase="night_resolution",system="story_system",
                                  event_type="STORY_THREAD_STAGE_CHANGED",
                                  message=f"剧情线“{t.title}”进入 {t.stage} 阶段。",
                                  actor_ids=t.participants,payload={"thread_id":t.id,"stage":t.stage})
        elif e.level==EventLevel.NARRATIVE.value and score>=world.cfg.story_create_threshold:
            tid=f"thread_{len(world.story_threads)+1:03d}"
            t=StoryThread(tid,make_thread_title(e),[e.event_id],list(e.actor_ids),
                          [e.scene_id] if e.scene_id else [],list(e.tags),score,min(100,int(score/2)),
                          make_open_questions(e),object_ids=list(e.object_ids),
                          knowledge_ids=list(e.knowledge_ids),organization_ids=list(e.organization_ids),
                          conflict_ids=list(e.conflict_ids),specific_tags=specific_story_tags(e.tags),
                          last_major_event_day=world.day,event_type_counts={e.event_type:1})
            world.story_threads[tid]=t
            world.ledger.emit(day=world.day,phase="night_resolution",system="story_system",
                              event_type="STORY_THREAD_CREATED",message=f"创建剧情线 {t.title}，初始分数 {score:.1f}。",
                              actor_ids=e.actor_ids,scene_id=e.scene_id,
                              payload={"thread_id":tid,"source_event":e.event_id})
            world.ledger.log_story_line(t.id,f"Day {world.day} {e.phase}: {e.description} [{e.event_id}]")
    for t in world.story_threads.values():
        if t.active:
            maybe_publish_commission(world,t)


def write_memories_from_events(world,events):
    for e in events:
        if e.level == EventLevel.BACKGROUND.value or narrative_score(e) <= 0:
            continue
        importance=int(min(10,max(1,narrative_score(e)/10)))
        for npc_id in e.actor_ids:
            npc=world.npcs.get(npc_id)
            if not npc: continue
            npc.memories.append(Memory(world.day,e.phase,e.description,importance,e.event_id,list(e.tags)))
            world.ledger.emit(day=world.day,phase="night_resolution",system="memory_system",
                              event_type="MEMORY_WRITTEN",message=f"将事件写入 {npc.name} 的记忆：{e.description}",
                              actor_ids=[npc.id],scene_id=e.scene_id,
                              payload={"source_event":e.event_id,"importance":importance},
                              trace_id=e.trace_id,parent_id=e.event_id)


def update_beliefs_from_events(world,events):
    for e in events:
        if e.event_type=="SUSPICIOUS_ENCOUNTER" and len(e.actor_ids)>=2:
            observer=world.npcs[e.actor_ids[0]]; target=world.npcs[e.actor_ids[1]]
            belief=f"{target.name} 可能参与了某些需要隐藏的异常活动"
            if belief not in observer.beliefs: observer.beliefs.append(belief)


def maintain_case_backlog(world):
    """Merge repeated minor reports and prevent ordinary cases from living forever."""
    active=[case for case in world.cases.values()
            if case.status not in {"resolved","closed","failed"} and case.stage!="merged"]
    grouped=defaultdict(list)
    for case in active:
        occult="conflict:tingen_occult_war" in case.conflict_ids
        if not occult:
            grouped[(case.case_type,tuple(sorted(case.known_locations)))].append(case)
    for cases in grouped.values():
        cases.sort(key=lambda item:(item.created_day,item.id))
        canonical=cases[0]
        for duplicate in cases[1:]:
            if duplicate.created_day-canonical.created_day>2:
                canonical=duplicate
                continue
            canonical.report_ids=sorted(set(canonical.report_ids+duplicate.report_ids))
            canonical.evidence_ids=sorted(set(canonical.evidence_ids+duplicate.evidence_ids))
            canonical.suspect_ids=sorted(set(canonical.suspect_ids+duplicate.suspect_ids))
            canonical.progress=max(canonical.progress,duplicate.progress)
            duplicate.status="closed"; duplicate.stage="merged"; duplicate.closed_day=world.day
            for report in world.incident_reports.values():
                if report.case_id==duplicate.id:
                    report.case_id=canonical.id
    for case in world.cases.values():
        if case.status in {"resolved","closed","failed"} or case.stage=="merged":
            continue
        occult="conflict:tingen_occult_war" in case.conflict_ids
        age=world.day-case.created_day
        if not occult and not case.suspect_ids and age>=3:
            case.status="resolved"; case.stage="resolved"; case.progress=100; case.closed_day=world.day
        elif not occult and age>=7 and case.progress<40:
            case.status="closed"; case.stage="closed"; case.closed_day=world.day


def update_daily_character_states(world,npc):
    """Apply slow recovery/decay so event states do not remain saturated forever."""
    change_state(world,npc,"stress",-4,"一夜休整带来自然恢复")
    change_state(world,npc,"fear",-3,"远离即时危险后恐惧逐渐消退")
    change_state(world,npc,"pain",-3,"伤势随时间缓慢恢复")
    change_state(world,npc,"alertness",-2,"没有持续刺激时警觉回落")
    change_state(world,npc,"legal_risk",-2,"未出现新证据时短期关注度下降")
    change_state(world,npc,"loneliness",3,"日常时间流逝增加陪伴需求")
    morale=npc.states.get("morale",50)
    if morale!=50:
        change_state(world,npc,"morale",-2 if morale>50 else 2,"士气缓慢回归日常水平")
    duty=npc.states.get("civic_duty",50)
    if duty!=50:
        change_state(world,npc,"civic_duty",-1 if duty>50 else 1,"公民责任感回归个人基线")
    npc.needs["financial_pressure"]=max(0,min(100,100-npc.wealth))
    if 30<npc.health<100:
        npc.health=min(100,npc.health+1)
    npc.emotions["fear"]=npc.states.get("fear",0)
    npc.emotions["anxiety"]=npc.states.get("stress",0)
    npc.emotions["happiness"]=npc.states.get("morale",50)


restock_essential_supplies = economy_system.restock_essential_supplies


def resolve_end_of_day(world):
    resolve_untreated_injuries(world)
    events=list(world.events_by_day[world.day])
    world.ledger.emit(day=world.day,phase="night_resolution",system="night_resolution",
                      event_type="DAY_RESOLUTION_START",message=f"开始结算 Day {world.day}，共 {len(events)} 条白天事件。")
    write_memories_from_events(world,events)
    update_beliefs_from_events(world,events)
    update_story_threads_from_events(world,events)
    for case in world.cases.values():
        advance_case_stage(world,case)
    maintain_case_backlog(world)
    restock_essential_supplies(world)
    for npc in world.npcs.values():
        if npc.alive:
            update_daily_character_states(world,npc)
            npc.needs["hunger"]=100-npc.states.get("satiety",70)
            npc.needs["fatigue"]=100-npc.states.get("energy",70)
            if npc.disposition_status not in {"active","wanted"} or npc.health<=30:
                continue
            crime_decay=6 if npc.states.get("legal_risk",0)>=60 else 12
            decay={"crime_control":crime_decay,"ritual_stability":10,"occult_supply":7}
            for need_id,amount in decay.items():
                if need_id in npc.special_needs:
                    npc.special_needs[need_id]=max(0,npc.special_needs[need_id]-amount)
    world.ledger.emit(day=world.day,phase="night_resolution",system="night_resolution",
                      event_type="DAY_RESOLUTION_END",message=f"Day {world.day} 白天事件结算完成。")


def mutual_relationship_kind(a,b):
    left=a.relationships.get(b.id)
    right=b.relationships.get(a.id)
    if not left or not right:
        return None
    for kind in ("爱人","朋友","同事","前同事"):
        if kind in left.kinds and kind in right.kinds:
            return kind
    return None


def arrange_social_invitations(world,planned_day,max_invitations=30):
    """Invite, evaluate and only then write a shared activity into both plans."""
    free_behaviors={"SOCIALIZE","SHOP","PRAY"}
    occupied=set()
    attempted_pairs=set()
    created=0
    residents=sorted((npc for npc in world.npcs.values() if npc_can_act(npc)),key=lambda n:n.id)
    for inviter in residents:
        if created>=max_invitations:
            break
        related=[]
        for target_id in inviter.relationships:
            invitee=world.npcs.get(target_id)
            if invitee and npc_can_act(invitee):
                kind=mutual_relationship_kind(inviter,invitee)
                if kind:
                    related.append((kind,invitee))
        related.sort(key=lambda item:(("爱人","朋友","同事","前同事").index(item[0]),item[1].id))
        for kind,invitee in related:
            pair=tuple(sorted((inviter.id,invitee.id)))
            if pair in attempted_pairs:
                continue
            accepted_this_pair=False
            for phase in PHASES:
                phase_name=phase.value
                key_a=(inviter.id,phase_name); key_b=(invitee.id,phase_name)
                plan_a=inviter.daily_plan.get(phase_name); plan_b=invitee.daily_plan.get(phase_name)
                if (key_a in occupied or key_b in occupied or not plan_a or not plan_b
                        or plan_a.behavior not in free_behaviors or plan_b.behavior not in free_behaviors):
                    continue
                if kind=="爱人":
                    scene_id="restaurant" if (planned_day+int(inviter.id[-3:]))%2 else "opera_house"
                    activity="约会"
                elif kind=="朋友":
                    options=["tavern","opera_house","divination_club","restaurant"]
                    scene_id=options[(planned_day+int(inviter.id[-3:]))%len(options)]
                    activity="结伴娱乐"
                else:
                    scene_id="tavern" if phase_name in {"evening","late_night"} else "restaurant"
                    activity="同事聚会" if kind=="同事" else "前同事叙旧"
                invitation=SocialInvitation(
                    id=f"invite_{planned_day:03d}_{len(world.invitations)+1:04d}",
                    inviter_id=inviter.id,invitee_id=invitee.id,day=planned_day,
                    phase=phase_name,scene_id=scene_id,activity=activity,
                    required_relationship=kind)
                relation=invitee.relationships[inviter.id]
                acceptance=(relation.trust+relation.affection*0.45
                            +invitee.personality.get("social",50)*0.25
                            -invitee.states.get("stress",0)*0.18)
                variation=((int(inviter.id[-3:])+int(invitee.id[-3:]))*17+planned_day*13)%31-15
                acceptance+=variation
                threshold={"爱人":68,"朋友":92,"同事":78,"前同事":82}[kind]
                if acceptance>=threshold:
                    invitation.status="accepted"
                    invitation.response_reason=f"双方互为{kind}且该时段都有自由计划"
                    inviter.daily_plan[phase_name]=PhasePlan(
                        scene_id,f"邀请 {invitee.name} 一起{activity}，对方已经接受",
                        invitee.id,68,"MEET_PERSON",plan_a.scene_id)
                    invitee.daily_plan[phase_name]=PhasePlan(
                        scene_id,f"接受 {inviter.name} 的邀请，一起{activity}",
                        inviter.id,68,"MEET_PERSON",plan_b.scene_id)
                    occupied.update({key_a,key_b})
                    accepted_this_pair=True
                else:
                    invitation.status="rejected"
                    invitation.response_reason="关系强度或当前状态不足以接受邀请"
                world.invitations[invitation.id]=invitation
                attempted_pairs.add(pair)
                world.ledger.emit(day=world.day,phase="planning",system="invitation_system",
                                  event_type=f"INVITATION_{invitation.status.upper()}",
                                  message=f"{inviter.name} 邀请 {invitee.name} {activity}：{invitation.status}。",
                                  actor_ids=[inviter.id,invitee.id],scene_id=scene_id,
                                  payload=asdict(invitation))
                created+=1
                break
            if accepted_this_pair or created>=max_invitations:
                break


def plan_tomorrow(world):
    if world.cfg.llm_mode=="deepseek":
        planner_client=world.deepseek
        provider_name="DeepSeek"
        enabled=planner_client.available()
    elif world.cfg.llm_mode in ("auto","ollama"):
        planner_client=world.ollama
        provider_name="Ollama/Qwen"
        enabled=planner_client.available() if world.cfg.llm_mode=="auto" else True
    else:
        planner_client=None
        provider_name="rule"
        enabled=False
    world.ledger.emit(day=world.day,phase="night_planning",system="planner",
                      event_type="PLANNING_START",
                      message=f"开始为 Day {world.day+1} 制定计划。provider={provider_name} enabled={enabled}")
    operation_members={npc_id for operation in world.ritual_engine.active()
                       for npc_id in operation.participant_ids}
    def importance(npc):
        score=40 if npc.tier=="core" else 0
        score+=35 if npc.id in operation_members else 0
        score+=25 if any(d.active and d.expires_day>=world.day for d in npc.response_drives) else 0
        score+=25 if any(npc.id in case.assigned_officer_ids+case.suspect_ids
                         for case in world.cases.values()) else 0
        score+=min(20,len(npc.memories))
        return score
    alive=[npc for npc in world.npcs.values() if npc_can_act(npc)]
    beyonder_npcs=[npc for npc in alive if npc.layer!=NPCLayer.ORDINARY.value]
    llm_npcs=(sorted(beyonder_npcs,key=importance,reverse=True)[:world.cfg.max_llm_core_npcs]
              if enabled else [])
    llm_ids={npc.id for npc in llm_npcs}
    contexts={npc.id:build_decision_context(world,npc) for npc in llm_npcs}
    for npc in llm_npcs:
        ctx=contexts[npc.id]
        world.ledger.emit(day=world.day,phase="night_planning",system="planner",
                          event_type="LLM_CONTEXT_BUILT",message=f"为 {npc.name} 构造结算后决策上下文。",
                          actor_ids=[npc.id],payload={"memory_count":len(ctx["recent_important_memories"]),
                          "thread_count":len(ctx["known_story_threads"]),
                          "commitment_count":len(ctx["open_commitments"]),
                          "dominant_desires":ctx["dominant_desires"]})
    results={}
    concurrency=world.cfg.llm_concurrency if provider_name=="DeepSeek" else 1
    if llm_npcs:
        with ThreadPoolExecutor(max_workers=max(1,concurrency)) as pool:
            futures={pool.submit(planner_client.plan,contexts[npc.id],world.day,npc.id):npc
                     for npc in llm_npcs}
            for future in as_completed(futures):
                npc=futures[future]
                try: results[npc.id]=(future.result(),None)
                except Exception as exc: results[npc.id]=(None,exc)
    llm_count=0
    for npc in alive:
        raw,exc=results.get(npc.id,(None,None))
        if npc.id in llm_ids and exc is None:
            npc.daily_plan=normalize_llm_plan(world,npc,raw)
            llm_count+=1
            world.ledger.emit(day=world.day,phase="night_planning",system="planner",
                              event_type="LLM_PLAN_ACCEPTED",
                              message=f"{npc.name} 的 Day {world.day+1} 计划由 {provider_name} 生成并通过校验。",
                              actor_ids=[npc.id],payload={k:asdict(v) for k,v in npc.daily_plan.items()})
        else:
            npc.daily_plan=rule_plan_for_npc(world,npc,planned_day=world.day+1)
            event_type="LLM_PLAN_FALLBACK" if exc else "RULE_PLAN_CREATED"
            message=(f"{npc.name} 的 LLM 规划失败，改用规则规划：{type(exc).__name__}: {exc}"
                     if exc else f"{npc.name} 的 Day {world.day+1} 计划由规则系统生成。")
            world.ledger.emit(day=world.day,phase="night_planning",system="planner",
                              event_type=event_type,message=message,actor_ids=[npc.id],
                              payload={k:asdict(v) for k,v in npc.daily_plan.items()})
    arrange_social_invitations(world,world.day+1)
    world.ledger.emit(day=world.day,phase="night_planning",system="planner",
                      event_type="PLANNING_END",message=f"Day {world.day+1} 计划生成完成；实际使用 LLM 的核心 NPC 数：{llm_count}。")


def save_snapshot(world):
    data={
        "day":world.day,"player_scene":world.player_scene,
        "long_term_goals":{gid:asdict(goal) for gid,goal in world.long_term_goals.items()},
        "scenes":{sid:asdict(scene) for sid,scene in world.scenes.items()},
        "objects":{oid:asdict(obj) for oid,obj in world.objects.items()},
        "observations":{oid:asdict(obs) for oid,obs in world.observations.items()},
        "reports":{rid:asdict(report) for rid,report in world.reports.items()},
        "incident_reports":{rid:asdict(report) for rid,report in world.incident_reports.items()},
        "cases":{cid:asdict(case) for cid,case in world.cases.items()},
        "factions":{fid:asdict(faction) for fid,faction in world.factions.items()},
        "world_conflicts":{cid:asdict(conflict) for cid,conflict in world.world_conflicts.items()},
        "intelligence":{iid:asdict(fact) for iid,fact in world.intelligence.facts.items()},
        "trace_evidence":{tid:asdict(trace) for tid,trace in world.ritual_engine.traces.items()},
        "operations":{oid:asdict(operation) for oid,operation in world.ritual_engine.operations.items()},
        "followup_plans":{pid:asdict(plan) for pid,plan in world.followup_engine.plans.items()},
        "social_invitations":{iid:asdict(invitation) for iid,invitation in world.invitations.items()},
        "state_deltas":[asdict(delta) for delta in world.state_deltas[-500:]],
        "npcs":{nid:{
            "id":n.id,"name":n.name,"tier":n.tier,"occupation":n.occupation,
            "organization":n.organization,"current_scene":n.current_scene,
            "home_scene":n.home_scene,"work_scene":n.work_scene,
            "work_days":n.work_days,"work_phases":n.work_phases,
            "relationships":{target_id:asdict(relation)
                             for target_id,relation in n.relationships.items()},
            "layer":n.layer,"sequence_pathway":n.sequence_pathway,
            "sequence_rank":n.sequence_rank,"faction_ids":n.faction_ids,"duties":n.duties,
            "skills":n.skills,
            "wealth":n.wealth,"sanity":n.sanity,"health":n.health,"alive":n.alive,
            "disposition_status":n.disposition_status,
            "disposition_since_day":n.disposition_since_day,
            "disposition_cause_event_id":n.disposition_cause_event_id,
            "states":n.states,
            "special_needs":n.special_needs,
            "goals":n.goals,"knowledge":n.knowledge,"beliefs":n.beliefs,
            "investigation_progress":n.investigation_progress,
            "response_drives":[asdict(d) for d in n.response_drives],
            "dominant_desires":[asdict(d) for d in world.desire_engine.dominant(n,world)],
            "memories":[asdict(m) for m in n.memories[-20:]],
            "daily_plan":{k:asdict(v) for k,v in n.daily_plan.items()},
            "action_chain":n.action_chain,"long_term_goal_ids":n.long_term_goal_ids
        } for nid,n in world.npcs.items()},
        "story_threads":{k:asdict(v) for k,v in world.story_threads.items()},
        "commissions":[asdict(c) for c in world.commissions]
    }
    atomic_write_json(world.log_dir/f"snapshot_day_{world.day:03d}.json", data)


def inject_demo_player_commitment(world):
    if world.day!=2 or "npc_000" not in world.npcs: return
    npc=world.npcs["npc_000"]
    npc.commitments.append(Commitment("afternoon","evernight_church","player",95,
                                      "按照与玩家的约定，下午前往黑夜女神教堂见面。"))
    world.ledger.emit(day=world.day,phase="morning",system="player_interaction",
                      event_type="COMMITMENT_CREATED",
                      message=f"玩家上午与 {npc.name} 约定：下午前往黑夜女神教堂。",
                      actor_ids=[npc.id],scene_id=world.player_scene,
                      payload={"execute_phase":"afternoon","priority":95})


def print_day_summary(world):
    events=world.events_by_day[world.day]
    print(f"\n--- Day {world.day} Summary ---")
    print(f"events={len(events)} story_threads={len(world.story_threads)} commissions={len(world.commissions)}")
    conflict=world.world_conflicts.get("conflict:tingen_occult_war")
    if conflict:
        print(f"主矛盾={conflict.title} pressure={conflict.pressure} stage={conflict.stage}")
    stage_names={"select_target":"选择目标","collect_materials":"收集仪式材料",
                 "prepare_site":"布置仪式场地","perform_ritual":"举行秘密仪式",
                 "cleanup_or_escape":"清理痕迹或撤离",
                 "gather_escape_leads":"收集逃亡线索","track_fugitive":"追踪逃犯",
                 "confront_fugitive":"截获逃犯","secure_scene":"封锁现场",
                 "analyze_contamination":"分析污染","cleanse_scene":"净化现场",
                 "inspect_ritual_site":"勘察仪式现场","recover_ritual_result":"回收仪式成果",
                 "erase_remaining_traces":"清除组织痕迹","gather_custody_intel":"收集关押情报",
                 "infiltrate_custody":"潜入关押地","free_prisoner":"释放被捕成员"}
    case_stages={"reported":"收到报告","assessing":"评估报告","investigating":"收集证据",
                 "suspect_identified":"锁定嫌疑人","surveillance":"监视嫌疑人",
                 "operation_planned":"准备干预","intervention":"执行干预",
                 "resolved":"已解决","failed":"失败"}
    print("【长期计划】")
    shown=0
    for operation in world.ritual_engine.operations.values():
        leader=world.npcs.get(operation.leader_id)
        goal=world.long_term_goals.get(operation.linked_goal_id)
        stage=operation.current_stage
        status={"active":"进行中","completed":"已完成","failed":"已失败"}.get(operation.status,operation.status)
        print(f"  - {leader.name if leader else operation.leader_id}：非法仪式计划{status}；"
              f"进度={goal.progress if goal else 0}% 当前阶段="
              f"{stage_names.get(stage.id,stage.id) if stage else '结束'} 暴露度={operation.exposure}")
        shown+=1
    for plan in world.followup_engine.plans.values():
        if plan.status!="active": continue
        owner=world.npcs.get(plan.owner_id); goal=world.long_term_goals.get(plan.goal_id)
        stage=plan.current_stage
        print(f"  - {owner.name if owner else plan.owner_id}：{goal.description if goal else plan.template_id}；"
              f"进度={goal.progress if goal else 0}% 当前阶段={stage_names.get(stage.id,stage.id) if stage else '结束'}")
        shown+=1
        if shown>=4: break
    for case in sorted(world.cases.values(),key=lambda item:item.id):
        if case.stage=="merged" or (case.status in ("resolved","closed") and case.closed_day!=world.day):
            continue
        suspects=", ".join(world.npcs[nid].name for nid in case.suspect_ids if nid in world.npcs) or "尚未锁定"
        print(f"  - 官方案件 {case.id}：{case_stages.get(case.stage,case.stage)}；"
              f"进度={case.progress}% 证据={len(case.evidence_ids)} 嫌疑人={suspects}")
        shown+=1
        if shown>=4: break
    if shown==0: print("  - 暂无活跃长期计划")

    new_goals=[goal for goal in world.long_term_goals.values()
               if goal.created_day==world.day and goal.goal_type not in
               ("perform_illegal_ritual","investigate_and_stop_operation","investigate_public_incident")]
    if new_goals:
        print("【新产生的目标】")
        for goal in sorted(new_goals,key=lambda item:item.priority,reverse=True)[:5]:
            owner=world.npcs.get(goal.owner_id)
            print(f"  - {owner.name if owner else goal.owner_id}：{goal.description}")

    causal_types={"LONG_TERM_PLAN_PROGRESS","LONG_TERM_GOAL_PROGRESS","CASE_STAGE_CHANGED",
                  "ILLEGAL_OPERATION_STAGE","OFFICIAL_INTERVENTION_PLANNED",
                  "ILLEGAL_RITUAL_STOPPED","ILLEGAL_RITUAL_INTERVENTION_FAILED","TARGET_FOLLOWED",
                  "TRACKER_EXPOSED","EVIDENCE_DISCOVERED","WITNESS_REPORT_FILED",
                  "HOSTILE_COUNTER_INVESTIGATION_EXPOSED","HOSTILE_COUNTER_INVESTIGATION_SUCCEEDED",
                  "RITUAL_VICTIM_KILLED","SCENE_OCCULT_CONTAMINATED","RITUAL_LEADER_ESCAPED",
                  "HOSTILE_LEADER_ARRESTED","STORY_CHARACTER_ARRIVED"}
    causal_types|={"FOLLOWUP_PLAN_STAGE","FUGITIVE_CAPTURED","OCCULT_SCENE_CLEANSED",
                   "RITUAL_RESULT_RECOVERED","ARRESTED_MEMBER_RESCUED"}
    causal=[]; seen=set()
    for event in sorted(events,key=narrative_score,reverse=True):
        if event.event_type not in causal_types: continue
        key=(event.event_type,event.scene_id,tuple(event.actor_ids))
        if key in seen: continue
        seen.add(key); causal.append(event)
        if len(causal)>=5: break
    print("【关键因果事件】")
    if causal:
        for event in causal: print(f"  - {event.description}")
    else: print("  - 今天没有推动主线阶段的事件")

    print("【下一步】")
    next_lines=[]
    for operation in world.ritual_engine.active():
        leader=world.npcs.get(operation.leader_id); stage=operation.current_stage
        if stage: next_lines.append(f"{leader.name if leader else operation.leader_id}：{stage_names.get(stage.id,stage.id)}")
    for plan in world.followup_engine.active():
        owner=world.npcs.get(plan.owner_id); stage=plan.current_stage
        if stage: next_lines.append(f"{owner.name if owner else plan.owner_id}：{stage_names.get(stage.id,stage.id)}")
    for case in world.cases.values():
        if case.status in ("resolved","closed","failed") or case.stage=="merged": continue
        action={"reported":"核验报告","assessing":"前往现场调查","investigating":"关联物证与嫌疑人",
                "suspect_identified":"监视嫌疑人","surveillance":"积累证据并制定干预",
                "operation_planned":"制定干预方案","intervention":"阻止敌对行动"}.get(case.stage,"继续调查")
        next_lines.append(f"官方案件 {case.id}：{action}")
    if next_lines:
        for line in next_lines[:4]: print(f"  - {line}")
    else: print("  - 当前主线行动均已结束")

    excluded=causal_types|{"RITUAL_TRACE_DISCOVERED","OCCULT_DISTURBANCE","NPC_MOVED"}
    secondary=[]; secondary_seen=set()
    for event in sorted(events,key=narrative_score,reverse=True):
        if event.event_type in excluded or narrative_score(event)<=0: continue
        key=(event.event_type,event.scene_id)
        if key in secondary_seen: continue
        secondary_seen.add(key); secondary.append(event)
        if len(secondary)>=3: break
    if secondary:
        print("【次要事件】")
        for event in secondary: print(f"  - {event.description}")


def run(world):
    sync_long_term_goals(world,emit_events=False)
    for npc in world.npcs.values():
        npc.daily_plan=rule_plan_for_npc(world,npc)
    arrange_social_invitations(world,world.day)

    for _ in range(world.cfg.days):
        for phase in PHASES:
            if phase==Phase.MORNING: inject_demo_player_commitment(world)
            simulate_phase(world,phase)

        resolve_end_of_day(world)

        before=len(world.events_by_day[world.day])
        run_night_fate_events(world)
        night_events=world.events_by_day[world.day][before:]
        if night_events:
            write_memories_from_events(world,night_events)
            update_beliefs_from_events(world,night_events)
            update_story_threads_from_events(world,night_events)
            generate_harm_and_report_reactions(world,night_events)

        generate_incident_response_drives(world,world.events_by_day[world.day])
        sync_long_term_goals(world)

        save_snapshot(world)
        print_day_summary(world)
        plan_tomorrow(world)

        world.day+=1
        world.phase=Phase.MORNING

    print("\nSimulation complete.")
    print("Readable history :", world.ledger.world_log)
    print("Trace JSONL      :", world.ledger.trace_jsonl)


def load_runtime_settings():
    project_dir=Path(__file__).resolve().parent
    settings={}
    for filename in ("config.json","config.local.json"):
        path=project_dir/filename
        if not path.exists():
            continue
        try:
            loaded=json.loads(path.read_text(encoding="utf-8"))
        except (OSError,json.JSONDecodeError) as exc:
            raise RuntimeError(f"无法读取运行配置 {path}: {exc}") from exc
        if not isinstance(loaded,dict):
            raise RuntimeError(f"运行配置 {path} 必须是 JSON 对象")
        settings.update(loaded)
    return settings


def parse_args(settings=None):
    settings=settings or {}
    p=argparse.ArgumentParser()
    p.add_argument("--days",type=int,default=settings.get("days",7))
    p.add_argument("--core",type=int,default=settings.get("core_npcs",20))
    p.add_argument("--simple",type=int,default=settings.get("simple_npcs",180))
    p.add_argument("--seed",type=int,default=settings.get("seed",42))
    p.add_argument("--llm",choices=["auto","ollama","deepseek","rule"],
                   default=settings.get("llm_mode","deepseek"))
    p.add_argument("--model",default=settings.get("ollama_model","qwen3:8b"))
    p.add_argument("--ollama-url",default=settings.get("ollama_url","http://127.0.0.1:11434"))
    p.add_argument("--deepseek-model",default=settings.get("deepseek_model","deepseek-v4-flash"))
    p.add_argument("--deepseek-url",default=settings.get("deepseek_url","https://api.deepseek.com"))
    p.add_argument("--max-llm-npcs",type=int,default=settings.get("max_llm_npcs",20))
    p.add_argument("--llm-concurrency",type=int,default=settings.get("llm_concurrency",5))
    p.add_argument("--log-dir",default=settings.get("log_dir","runs/latest"))
    p.add_argument("--quiet",action="store_true",default=settings.get("quiet",False))
    return p.parse_args()


def main():
    settings=load_runtime_settings()
    a=parse_args(settings)
    project_dir=Path(__file__).resolve().parent
    log_dir=Path(a.log_dir)
    if not log_dir.is_absolute():
        log_dir=project_dir/log_dir
    cfg=Config(seed=a.seed,days=a.days,core_npcs=a.core,simple_npcs=a.simple,
               llm_mode=a.llm,ollama_model=a.model,ollama_url=a.ollama_url,
               deepseek_model=a.deepseek_model,deepseek_url=a.deepseek_url,
               deepseek_api_key=os.environ.get("DEEPSEEK_API_KEY") or settings.get("deepseek_api_key"),
               max_llm_core_npcs=max(0,a.max_llm_npcs),
               llm_concurrency=max(1,a.llm_concurrency),
               log_dir=str(log_dir),verbose=not a.quiet)
    run(World(cfg))


if __name__=="__main__":
    main()
