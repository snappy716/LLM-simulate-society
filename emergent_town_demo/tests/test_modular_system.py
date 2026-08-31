import tempfile
import unittest
from unittest.mock import patch

from emergent_town.actions.catalog import build_action_registry
from emergent_town.intelligence import IntelligenceSystem
from emergent_town.plots.illegal_ritual import IllegalRitualEngine
from town_demo import (Config, Phase, World, advance_case_stage, advance_followup_chains,
                       advance_illegal_operations, normalize_llm_plan, restock_essential_supplies,
                       resolve_operation_consequences, sync_long_term_goals)


class ModularSystemTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.world = World(Config(core_npcs=4, simple_npcs=4, llm_mode="rule",
                                  log_dir=self.tmp.name, verbose=False))

    def tearDown(self):
        self.tmp.cleanup()

    def test_action_registry_contains_only_executable_actions(self):
        registry = build_action_registry()
        self.assertEqual([], registry.validate())
        self.assertIn("SHARE_INFORMATION", registry.ids())
        self.assertIn("PERFORM_SECRET_RITUAL", registry.ids())
        self.assertIn("STOP_RITUAL", registry.ids())

    def test_low_state_generates_competing_desires(self):
        npc = self.world.npcs["npc_003"]
        npc.states["energy"] = 5
        npc.states["satiety"] = 8
        npc.wealth = 0
        desires = {item.id:item.strength for item in self.world.desire_engine.evaluate(npc,self.world)}
        self.assertGreater(desires["restore_energy"], 90)
        self.assertGreater(desires["solve_hunger"], 90)
        self.assertIn("gain_money", desires)

    def test_npc_cannot_share_unknown_intelligence(self):
        system = IntelligenceSystem()
        speaker = self.world.npcs["npc_000"]
        listener = self.world.npcs["npc_001"]
        fact = system.create(subject_id="npc_002", predicate="visited", object_id="warehouse_3",
                             day=1, phase="evening", source_type="witness", source_id="npc_003",
                             confidence=.8, secrecy=40, known_by=["npc_003"])
        self.assertIsNone(system.share(fact.id,speaker,listener))
        self.assertNotIn(listener.id,fact.known_by)

    def test_secret_intelligence_is_not_automatically_shared(self):
        system = IntelligenceSystem()
        speaker = self.world.npcs["npc_002"]
        listener = self.world.npcs["npc_000"]
        fact = system.create(subject_id="aurora_order_tingen", predicate="plans",
                             object_id="illegal_ritual", day=1, phase="evening",
                             source_type="faction_order", source_id="aurora_order_tingen",
                             confidence=1.0, secrecy=100, known_by=[speaker.id])
        self.assertLess(system.can_share(speaker,listener,fact),35)

    def test_illegal_operation_advances_and_leaves_trace(self):
        engine = IllegalRitualEngine()
        operation = engine.create_operation(faction_id="aurora_order_tingen",
                                            leader_id="npc_002",participant_ids=["npc_002"],
                                            scene_id="warehouse_3",scheduled_day=6)
        trace = engine.advance(operation,day=2,phase="late_night",
                               action_id="SELECT_RITUAL_TARGET",actor_ids=["npc_002"],
                               outcome="success")
        self.assertIsNotNone(trace)
        self.assertEqual("collect_materials",operation.current_stage.id)
        self.assertIn(trace,engine.discoverable_at("warehouse_3"))

    def test_case_stage_uses_evidence_suspect_and_repeated_exposure(self):
        case = next(iter(self.world.cases.values()), None)
        if case is None:
            from town_demo import CaseFile
            case = CaseFile("case_test","occult_incident","open",["npc_001"],[],
                            ["trace_1"],["npc_002"],["warehouse_3"],
                            ["conflict:tingen_occult_war"],90,100)
            self.world.cases[case.id] = case
        case.evidence_ids=["trace_1"]
        case.suspect_ids=["npc_002"]
        case.progress=100
        case.exposure_counts["npc_002"]=3
        advance_case_stage(self.world,case)
        self.assertEqual("operation_planned",case.stage)

    def test_llm_strategy_chain_is_limited_and_validated(self):
        npc=self.world.npcs["npc_000"]
        phases={phase:{"scene_id":"home_quarter","intent":"休息","target_id":None,
                       "priority":40,"behavior":"REST","fallback_scene_id":"home_quarter"}
                for phase in ("morning","afternoon","evening","late_night")}
        raw={"plans":phases,"strategy_steps":[
            {"phase":"afternoon","action_id":"WATCH_LOCATION","scene_id":"warehouse_3",
             "target_id":None,"condition":"always","intent":"观察仓库"},
            {"phase":"evening","action_id":"NOT_IMPLEMENTED","scene_id":"market",
             "target_id":None,"condition":"always","intent":"无效"}]}
        normalize_llm_plan(self.world,npc,raw)
        self.assertEqual(1,len(npc.action_chain))
        self.assertEqual("WATCH_LOCATION",npc.action_chain[0]["action_id"])

    def test_deepseek_strategy_aliases_infer_phase_and_scene(self):
        npc=self.world.npcs["npc_000"]
        phases={phase:{"scene_id":"warehouse_3" if phase=="afternoon" else "home_quarter",
                       "intent":"调查" if phase=="afternoon" else "休息","target_id":None,
                       "priority":80,"behavior":"INVESTIGATE_LOCATION" if phase=="afternoon" else "REST",
                       "fallback_scene_id":"home_quarter"}
                for phase in ("morning","afternoon","evening","late_night")}
        normalize_llm_plan(self.world,npc,{"plans":phases,"strategy_steps":[
            {"behavior":"INVESTIGATE_LOCATION","condition":"always"}]})
        self.assertEqual(1,len(npc.action_chain))
        self.assertEqual("afternoon",npc.action_chain[0]["phase"])
        self.assertEqual("warehouse_3",npc.action_chain[0]["scene_id"])

    def test_operation_has_persistent_goal_and_progress(self):
        operation=next(iter(self.world.ritual_engine.operations.values()))
        goal=self.world.long_term_goals[operation.linked_goal_id]
        self.assertIn(goal.id,self.world.npcs[operation.leader_id].long_term_goal_ids)
        self.world.ritual_engine.advance(operation,day=1,phase="late_night",
                                         action_id="SELECT_RITUAL_TARGET",
                                         actor_ids=[operation.leader_id],outcome="success")
        sync_long_term_goals(self.world,emit_events=False)
        self.assertEqual(20,goal.progress)
        self.assertEqual("active",goal.status)

    def test_successful_ritual_changes_character_fates_and_spawns_successor(self):
        operation=next(iter(self.world.ritual_engine.operations.values()))
        operation.target_id="npc_003"
        operation.status="completed"
        before=len(self.world.npcs)
        events=resolve_operation_consequences(self.world,operation)
        self.assertFalse(self.world.npcs["npc_003"].alive)
        self.assertEqual("dead",self.world.npcs["npc_003"].disposition_status)
        self.assertEqual("fled",self.world.npcs[operation.leader_id].disposition_status)
        self.assertEqual(before+1,len(self.world.npcs))
        self.assertIn("RITUAL_VICTIM_KILLED",{event.event_type for event in events})
        self.assertTrue(operation.spawned_character_ids)

    def test_official_victory_arrests_leader_and_creates_rescue_goal(self):
        operation=next(iter(self.world.ritual_engine.operations.values()))
        operation.status="failed"
        operation.outcome_type="official_victory"
        resolve_operation_consequences(self.world,operation)
        leader=self.world.npcs[operation.leader_id]
        self.assertEqual("arrested",leader.disposition_status)
        goals=[goal for goal in self.world.long_term_goals.values()
               if goal.goal_type=="rescue_arrested_member"]
        self.assertEqual(1,len(goals))
        self.assertIn(goals[0].linked_plan_id,self.world.followup_engine.plans)
        self.assertEqual("rescue_arrested_member",
                         self.world.followup_engine.plans[goals[0].linked_plan_id].template_id)

    def test_successful_rescue_starts_regrouping_and_official_pursuit(self):
        operation=next(iter(self.world.ritual_engine.operations.values()))
        operation.status="failed"; operation.outcome_type="official_victory"
        resolve_operation_consequences(self.world,operation)
        with patch.object(self.world.rng,"randint",return_value=100):
            for day in range(2,5):
                self.world.day=day
                advance_followup_chains(self.world,Phase.AFTERNOON)
        leader=self.world.npcs[operation.leader_id]
        self.assertEqual("active",leader.disposition_status)
        self.assertTrue(any(item.status=="active" and item.leader_id==leader.id
                            for item in self.world.ritual_engine.operations.values()))
        self.assertTrue(any(goal.status=="active" and goal.goal_type=="hunt_ritual_leader"
                            and leader.name in goal.description
                            for goal in self.world.long_term_goals.values()))

    def test_arrested_leader_cannot_advance_illegal_operation(self):
        operation=next(iter(self.world.ritual_engine.operations.values()))
        leader=self.world.npcs[operation.leader_id]
        leader.disposition_status="arrested"
        self.world.day=operation.scheduled_day
        before=operation.current_stage_index
        advance_illegal_operations(self.world,Phase.LATE_NIGHT)
        self.assertEqual(before,operation.current_stage_index)
        self.assertEqual("active",operation.status)

    def test_daily_supply_restock_has_capacity(self):
        food=self.world.objects["object:market_food_crate"]
        medicine=self.world.objects["object:hospital_medicine"]
        food.quantity=0; medicine.quantity=0
        restock_essential_supplies(self.world)
        self.assertEqual(70,food.quantity)
        self.assertEqual(8,medicine.quantity)
        for _ in range(20):
            restock_essential_supplies(self.world)
        self.assertEqual(240,food.quantity)
        self.assertEqual(60,medicine.quantity)


if __name__ == "__main__":
    unittest.main()
