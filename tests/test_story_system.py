import tempfile
import unittest

from simulation.runtime import (
    Config,
    EventLevel,
    NPCLayer,
    Phase,
    Observation,
    SimEvent,
    StoryThread,
    World,
    change_state,
    find_related_thread,
    file_police_report,
    generate_incident_response_drives,
    hide_warehouse_evidence,
    normalize_llm_plan,
    resolve_phase_plan,
    resolve_opposed_check,
    rule_plan_for_npc,
    search_hidden_objects,
    sequence_modifier,
    update_story_threads_from_events,
)


def event(event_id, event_type, *, level="narrative", actors=None, scene="market",
          tags=None, parent_id=None, object_ids=None, conflict_ids=None):
    return SimEvent(
        event_id=event_id,
        trace_id=f"trace_{event_id}",
        day=1,
        phase="morning",
        event_type=event_type,
        scene_id=scene,
        actor_ids=actors or [],
        description=event_type,
        severity=8,
        conflict=7,
        danger=5,
        secret=6,
        emotion=5,
        tags=tags or [],
        parent_id=parent_id,
        level=level,
        object_ids=object_ids or [],
        conflict_ids=conflict_ids or [],
    )


class StorySystemTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.world = World(Config(core_npcs=2, simple_npcs=0, llm_mode="rule",
                                  log_dir=self.tmp.name, verbose=False))

    def tearDown(self):
        self.tmp.cleanup()

    def test_background_event_never_enters_story_thread(self):
        update_story_threads_from_events(self.world, [
            event("move", "NPC_MOVED", level=EventLevel.BACKGROUND.value,
                  actors=["npc_000"])
        ])
        self.assertEqual({}, self.world.story_threads)

    def test_significant_event_cannot_start_thread_by_itself(self):
        update_story_threads_from_events(self.world, [
            event("breakdown", "MENTAL_BREAKDOWN", level=EventLevel.SIGNIFICANT.value,
                  actors=["npc_000"], conflict_ids=["conflict:mental_health:npc_000"])
        ])
        self.assertEqual({}, self.world.story_threads)

    def test_same_actor_and_scene_do_not_merge_unrelated_events(self):
        first = event("one", "HOME_BURGLARY", actors=["npc_000"],
                      conflict_ids=["conflict:burglary:npc_000"])
        update_story_threads_from_events(self.world, [first])
        unrelated = event("two", "MENTAL_BREAKDOWN", actors=["npc_000"],
                          scene="market", tags=["night_fate"])
        self.assertIsNone(find_related_thread(self.world, unrelated))

    def test_generic_tag_does_not_merge_threads(self):
        update_story_threads_from_events(self.world, [
            event("one", "SECRET_ACTIVITY", tags=["secret", "occult"],
                  conflict_ids=["conflict:group:a"])
        ])
        unrelated = event("two", "SECRET_ACTIVITY", tags=["secret", "occult"],
                          conflict_ids=["conflict:group:b"])
        self.assertIsNone(find_related_thread(self.world, unrelated))

    def test_shared_object_is_a_strong_causal_anchor(self):
        update_story_threads_from_events(self.world, [
            event("one", "EVIDENCE_HIDDEN", object_ids=["object:ledger"])
        ])
        related = event("two", "CLUE_DISCOVERED", object_ids=["object:ledger"])
        self.assertIsNotNone(find_related_thread(self.world, related))

    def test_repeated_event_has_diminishing_score(self):
        events = [
            event("one", "EVIDENCE_HIDDEN", conflict_ids=["conflict:a"]),
            event("two", "EVIDENCE_HIDDEN", conflict_ids=["conflict:a"]),
            event("three", "EVIDENCE_HIDDEN", conflict_ids=["conflict:a"]),
        ]
        update_story_threads_from_events(self.world, events)
        thread = next(iter(self.world.story_threads.values()))
        full_score = sum(2 * e.severity + 2 * e.conflict + 1.5 * e.danger
                         + 1.8 * e.secret + 1.2 * e.emotion for e in events)
        self.assertLess(thread.score, full_score)
        self.assertEqual(3, thread.event_type_counts["EVIDENCE_HIDDEN"])

    def test_removed_secret_activity_falls_back_to_rest(self):
        raw = {"plans": {
            phase: {
                "scene_id": "underground_market",
                "intent": "进行秘密活动",
                "target_id": None,
                "priority": 90,
                "behavior": "SECRET_ACTIVITY",
                "fallback_scene_id": "home_quarter",
            }
            for phase in ("morning", "afternoon", "evening", "late_night")
        }}
        plans = normalize_llm_plan(self.world, self.world.npcs["npc_000"], raw)
        self.assertTrue(all(plan.behavior == "REST" for plan in plans.values()))
        self.assertTrue(all(plan.scene_id == self.world.npcs["npc_000"].home_scene
                            for plan in plans.values()))

    def test_evidence_is_a_persistent_searchable_object(self):
        keeper = self.world.npcs["npc_002"] if "npc_002" in self.world.npcs else self.world.npcs["npc_001"]
        keeper.organization = "aurora_cell"
        investigator = self.world.npcs["npc_000"]
        investigator.abilities["knowledge"] = 10
        investigator.abilities["inspiration"] = 10
        investigator.personality["curiosity"] = 100
        scene = self.world.scenes["warehouse_3"]

        hide_warehouse_evidence(self.world, keeper, scene)
        obj = self.world.objects["object:warehouse_contraband_ledger_page"]
        obj.custodian_id = keeper.id
        first_event_count = len(self.world.events_by_day[1])
        self.assertTrue(obj.hidden)
        self.assertEqual("container:warehouse_3:discarded_medicine_cabinet", obj.container_id)

        hide_warehouse_evidence(self.world, keeper, scene)
        self.assertEqual(first_event_count, len(self.world.events_by_day[1]))

        self.world.rng.seed(1)
        search_hidden_objects(self.world, investigator, scene)
        self.assertIn(investigator.id, obj.discovered_by)
        search_hidden_objects(self.world, keeper, scene)
        self.assertNotIn(keeper.id, obj.discovered_by)
        event_types = [item.event_type for item in self.world.events_by_day[1]]
        self.assertIn("EVIDENCE_DISCOVERED", event_types)
        self.assertEqual("RELATIONSHIP_CHANGED", event_types[-1])
        self.assertIn("可能藏匿了违禁货物账页", investigator.beliefs[-1])

    def test_occult_incident_forces_next_day_official_and_hostile_response(self):
        official = self.world.npcs["npc_000"]
        hostile = self.world.npcs["npc_001"]
        official.layer = NPCLayer.OFFICIAL_BEYONDER.value
        hostile.layer = NPCLayer.HOSTILE_BEYONDER.value
        incident = event("ritual", "OCCULT_DISTURBANCE", scene="warehouse_3",
                         tags=["occult", "ritual"],
                         conflict_ids=["conflict:tingen_occult_war"])

        generate_incident_response_drives(self.world, [incident])
        self.world.day = 2
        official.daily_plan = rule_plan_for_npc(self.world, official)
        hostile.daily_plan = rule_plan_for_npc(self.world, hostile)

        official_plan = resolve_phase_plan(self.world, official, Phase.AFTERNOON)
        hostile_plan = resolve_phase_plan(self.world, hostile, Phase.AFTERNOON)
        self.assertEqual("RESPOND_OCCULT_INCIDENT", official_plan.behavior)
        self.assertEqual("warehouse_3", official_plan.scene_id)
        self.assertIn(hostile_plan.behavior, {"HIDE_EVIDENCE", "COUNTER_INVESTIGATE"})

    def test_tingen_beyonders_are_limited_to_sequences_seven_through_nine(self):
        for npc in self.world.npcs.values():
            if npc.sequence_rank is not None:
                self.assertIn(npc.sequence_rank, {7, 8, 9})

    def test_higher_sequence_gets_larger_relevant_skill_modifier(self):
        actor = self.world.npcs["npc_000"]
        actor.sequence_pathway = "不眠者"
        actor.sequence_rank = 9
        sequence_nine = sequence_modifier(actor, "observation")
        actor.sequence_rank = 7
        sequence_seven = sequence_modifier(actor, "observation")
        self.assertGreater(sequence_seven, sequence_nine)

    def test_opposed_check_records_auditable_rolls_and_modifiers(self):
        actor = self.world.npcs["npc_000"]
        opponent = self.world.npcs["npc_001"]
        result = resolve_opposed_check(
            self.world, "追踪", actor, opponent, "tracking", "counter_tracking",
            actor_context=10, opponent_context=5, scene_id="market")
        self.assertEqual(result.actor_roll + sum(result.actor_modifiers.values()),
                         result.actor_total)
        self.assertEqual(result.opponent_roll + sum(result.opponent_modifiers.values()),
                         result.opponent_total)
        self.assertEqual(result.actor_total-result.opponent_total, result.margin)
        self.assertIn(result.outcome, {"complete_success", "success", "partial",
                                       "failure", "critical_failure"})

    def test_evernight_church_is_protected_from_generic_occult_events(self):
        church = self.world.scenes["evernight_church"]
        self.assertIn("official_controlled", church.tags)
        self.assertIn("occult_protected", church.tags)
        self.assertNotIn("occult", church.event_tags)

    def test_witness_report_creates_police_case_without_world_truth_access(self):
        witness = self.world.npcs["npc_000"]
        officer = self.world.npcs["npc_001"]
        officer.current_scene = "police_station"
        observation = Observation(
            "obs_test", witness.id, "evt_source", "warehouse_3",
            "看见有人把账页塞进废弃药柜", 0.75, 7,
            ["conflict:warehouse_anomaly"],
            ["object:warehouse_contraband_ledger_page"],
        )
        self.world.observations[observation.id] = observation
        case = file_police_report(self.world, witness, observation)
        self.assertIsNotNone(case)
        self.assertTrue(observation.reported)
        self.assertEqual([officer.id], case.assigned_officer_ids)
        self.assertEqual(["report_001"], case.report_ids)
        self.assertNotIn("npc_002", case.suspect_ids)

    def test_low_energy_and_satiety_change_rule_plan_weights(self):
        npc = self.world.npcs["npc_000"]
        npc.states["energy"] = 10
        npc.states["satiety"] = 10
        plans = rule_plan_for_npc(self.world, npc)
        self.assertEqual("REST", plans["morning"].behavior)
        self.assertEqual("SHOP", plans["afternoon"].behavior)

    def test_state_delta_changes_value_and_records_source(self):
        npc = self.world.npcs["npc_000"]
        npc.states["fear"] = 10
        change_state(self.world, npc, "fear", 25, "目击危险")
        self.assertEqual(35, npc.states["fear"])
        self.assertEqual(25, self.world.state_deltas[-1].delta)


if __name__ == "__main__":
    unittest.main()
