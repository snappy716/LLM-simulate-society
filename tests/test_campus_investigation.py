"""Source-bound observations, private beliefs and transactional investigation."""
from copy import deepcopy
import tempfile
import unittest
from pathlib import Path
from simulation.api.server import CampusKernelBridge
from simulation.persistence.kernel_checkpoint import save_kernel_checkpoint, load_kernel_checkpoint
from simulation.systems.campus_intelligence import create_campus_claim, disclosable_known_claims, load_campus_intelligence_policy, share_known_claim
from simulation.systems.campus_investigation import investigation_invariant, project_investigation_events
from simulation.systems import DeterministicRngPool
from tests.test_campus_combat_deployment import execute


class CampusInvestigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = CampusKernelBridge(46)
        cls.baseline, cls.rng = cls.bridge.kernel.capture_checkpoint()

    def setUp(self):
        self.bridge.kernel.restore_checkpoint(self.baseline, self.rng, expected_revision=self.bridge.kernel.state.revision)
        self.counter = 0
        self.npc = next(key for key in self.bridge.kernel._state.population if key != "player")
        self.bridge.kernel._state.population[self.npc]["current_location_id"] = "south_gate_region"

    def run_action(self, action, **params):
        self.counter += 1
        return execute(self.bridge, action, params, marker=f"investigation-{self.counter}")

    def observe(self):
        result = self.run_action("OBSERVE_SCENE")
        self.assertTrue(result["ok"], result)
        return result["result"]["payload"]["claim_ids"]

    def assert_failure(self, code, action, **params):
        before, rng = self.bridge.kernel.capture_checkpoint()
        result = self.run_action(action, **params)
        self.assertEqual(code, result["result"]["code"], result)
        self.assertFalse(result["ok"])
        after, after_rng = self.bridge.kernel.capture_checkpoint()
        for field in ("knowledge", "action_economy", "population", "inventories", "clock", "revision"):
            self.assertEqual(getattr(before, field), getattr(after, field), field)
        self.assertEqual(rng.snapshot(), after_rng.snapshot())

    def test_observation_uses_real_notice_without_time_or_action_cost(self):
        before = self.bridge.kernel.state
        ids = self.observe()
        after = self.bridge.kernel.state
        self.assertEqual(before.clock, after.clock)
        self.assertEqual(before.action_economy, after.action_economy)
        for key in ids:
            claim = after.knowledge["claims"][key]
            self.assertIn(claim["object_id"], after.tasks)
            self.assertEqual("notice", claim["source_context"]["source_kind"])
            self.assertEqual(1, after.knowledge["beliefs_by_actor"]["player"][key]["confidence"])
        self.assert_failure("no_new_evidence", "OBSERVE_SCENE")

    def test_search_inspects_real_dropped_stock_and_spends_only_one_major_action(self):
        drop = self.run_action("DROP_ITEM", item_id="bread_loaf", quantity=1)
        self.assertTrue(drop["ok"], drop)
        before = self.bridge.kernel.state
        result = self.run_action("SEARCH_SCENE")
        self.assertTrue(result["ok"], result)
        after = self.bridge.kernel.state
        self.assertEqual(before.clock, after.clock)
        self.assertEqual(before.inventories, after.inventories)
        self.assertEqual(before.action_economy["actors"]["player"]["major_remaining"] - 1, after.action_economy["actors"]["player"]["major_remaining"])
        claim = after.knowledge["claims"][result["result"]["payload"]["claim_ids"][0]]
        self.assertEqual("observed_ground_item", claim["predicate"])
        self.assertIn("无法仅据此确定物主", claim["summary"])
        self.assert_failure("no_new_evidence", "SEARCH_SCENE")

    def test_search_no_evidence_or_no_budget_never_spends_or_reveals(self):
        self.assert_failure("no_new_evidence", "SEARCH_SCENE")
        self.run_action("DROP_ITEM", item_id="bread_loaf", quantity=1)
        self.bridge.kernel._state.action_economy["actors"]["player"]["major_remaining"] = 0
        self.assertFalse(self.bridge.snapshot()["investigation"]["can_search"])
        self.assert_failure("major_action_exhausted", "SEARCH_SCENE")

    def test_notes_require_real_notebook_and_preserve_original_belief(self):
        key = self.observe()[0]
        self.assertTrue(self.run_action("RECORD_EVIDENCE", claim_id=key)["ok"])
        note = deepcopy(self.bridge.kernel.state.knowledge["investigation"]["notes_by_actor"]["player"][key])
        self.bridge.kernel._state.knowledge["beliefs_by_actor"]["player"][key]["confidence"] = .5
        self.assertEqual(note, self.bridge.snapshot()["investigation"]["notes"][key])
        self.bridge.kernel._state.inventories["actors"]["player"]["quantities"].pop("blank_notebook")
        self.assert_failure("notebook_required", "RECORD_EVIDENCE", claim_id=key)

    def test_unknown_evidence_invalid_boolean_and_forged_links_are_atomic(self):
        self.assert_failure("unknown_evidence", "RECORD_EVIDENCE", claim_id="unknown")
        key = self.observe()[0]
        self.assert_failure("invalid_disclosure", "SET_EVIDENCE_DISCLOSURE", claim_id=key, withheld="false")
        self.assert_failure("unknown_evidence", "LINK_EVIDENCE", claim_ids=[key, key], summary="猜测")
        self.assert_failure("unknown_evidence", "LINK_EVIDENCE", claim_ids=[key, []], summary="猜测")

    def test_hypothesis_never_becomes_truth_or_leaks_to_npc(self):
        self.observe()
        ids = list(self.bridge.kernel.state.knowledge["beliefs_by_actor"]["player"])[:2]
        before = self.bridge.kernel.state.knowledge
        result = self.run_action("LINK_EVIDENCE", claim_ids=ids, summary="导师可能知道这里发生的事，但尚无证据。")
        self.assertTrue(result["ok"], result)
        after = self.bridge.kernel.state.knowledge
        self.assertEqual(before["claims"], after["claims"])
        self.assertEqual(before["beliefs_by_actor"], after["beliefs_by_actor"])
        self.assertEqual("unverified", result["result"]["payload"]["hypothesis"]["status"])
        self.assert_failure("invalid_hypothesis", "LINK_EVIDENCE", claim_ids=ids, summary="x" * 201)

    def test_privacy_blocks_specific_and_autonomous_disclosure(self):
        key = self.observe()[0]
        self.assertTrue(self.run_action("SET_EVIDENCE_DISCLOSURE", claim_id=key, withheld=True)["ok"])
        state = self.bridge.kernel._state
        policy = load_campus_intelligence_policy(self.bridge.registry)
        self.assertNotIn(key, [item["claim"]["claim_id"] for item in disclosable_known_claims(state, "player", self.npc, policy)])
        # Isolate the one hidden source to test autonomous candidate selection.
        state.knowledge["beliefs_by_actor"]["player"] = {key: state.knowledge["beliefs_by_actor"]["player"][key]}
        self.assertIsNone(share_known_claim(state, sender_id="player", receiver_id=self.npc, interaction_id="privacy", intent_id="exchange_ideas", policy=policy, rng=DeterministicRngPool(1).stream("test")))
        self.assertTrue(self.run_action("SET_EVIDENCE_DISCLOSURE", claim_id=key, withheld=False)["ok"])
        self.assertIn(key, [item["claim"]["claim_id"] for item in disclosable_known_claims(self.bridge.kernel.state, "player", self.npc, policy)])

    def test_share_preserves_source_and_pair_cooldown(self):
        key = self.observe()[0]
        result = self.run_action("SHARE_EVIDENCE", claim_id=key, target_id=self.npc)
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["result"]["payload"]["shared"])
        belief = self.bridge.kernel.state.knowledge["beliefs_by_actor"][self.npc][key]
        self.assertEqual("player", belief["source_actor_id"])
        self.assertLess(belief["confidence"], 1)
        self.assert_failure("evidence_pair_cooldown", "ASK_ABOUT_EVIDENCE", claim_id=key, target_id=self.npc)

    def test_asking_only_reveals_known_related_disclosable_information(self):
        key = self.observe()[0]
        state = self.bridge.kernel._state
        fact = state.knowledge["claims"][key]
        extra = create_campus_claim(state, subject_id=fact["subject_id"], predicate="testimony", object_id=fact["object_id"], summary="我知道这份公告的发布经过。", secrecy=0, known_by=[self.npc])
        secret = create_campus_claim(state, subject_id=self.npc, predicate="secret", object_id="unrelated", summary="私人内容", secrecy=100, known_by=[self.npc])
        result = self.run_action("ASK_ABOUT_EVIDENCE", claim_id=key, target_id=self.npc)
        self.assertTrue(result["result"]["payload"]["shared"], result)
        own = self.bridge.kernel.state.knowledge["beliefs_by_actor"]["player"]
        self.assertIn(extra["claim_id"], own)
        self.assertNotIn(secret["claim_id"], own)

    def test_offsite_target_refused_and_unknown_personal_notes_hidden(self):
        key = self.observe()[0]
        self.bridge.kernel._state.population[self.npc]["current_location_id"] = "hospital_pharmacy"
        self.assert_failure("target_not_present", "SHARE_EVIDENCE", claim_id=key, target_id=self.npc)
        own = self.bridge.snapshot()["investigation"]
        npc_keys = set(self.bridge.kernel.state.knowledge["beliefs_by_actor"][self.npc])
        self.assertTrue(npc_keys.isdisjoint({entry["claim"]["claim_id"] for entry in own["entries"]}))

    def test_npc_uses_same_source_and_independent_action_budget(self):
        before = self.bridge.snapshot()
        result = self.bridge.execute({"command_id": "npc-observe", "actor_id": self.npc, "action_id": "OBSERVE_SCENE", "target_ids": [], "parameters": {}, "expected_world_revision": before["revision"], "issued_day": before["clock"]["day"], "issued_phase": before["clock"]["phase"], "issued_minute": 0, "source": "rule"})
        self.assertTrue(result["ok"], result)
        for key in result["result"]["payload"]["claim_ids"]:
            self.assertIn(key, self.bridge.kernel.state.knowledge["beliefs_by_actor"][self.npc])
            self.assertNotIn(key, self.bridge.kernel.state.knowledge["beliefs_by_actor"]["player"])

    def test_item_event_source_is_owned_and_reprojection_is_idempotent(self):
        result = self.run_action("DROP_ITEM", item_id="bread_loaf", quantity=1)
        self.assertTrue(result["ok"], result)
        from simulation.domain.events import SimulationEvent
        events = [SimulationEvent.from_dict(event) for event in result["result"]["events"]]
        state = self.bridge.kernel._state
        before = deepcopy(state.knowledge)
        project_investigation_events(state, events)
        self.assertEqual(before, state.knowledge)
        key = state.knowledge["investigation"]["observations"][events[0].event_id]
        self.assertNotIn(key, state.knowledge["beliefs_by_actor"][self.npc])
        self.assertEqual("surface", state.knowledge["claims"][key]["source_context"]["layer"])

    def test_save_load_keeps_sources_notes_hypotheses_and_privacy(self):
        key = self.observe()[0]
        self.run_action("RECORD_EVIDENCE", claim_id=key)
        self.run_action("SET_EVIDENCE_DISCLOSURE", claim_id=key, withheld=True)
        state, rng = self.bridge.kernel.capture_checkpoint()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "investigation.json"
            save_kernel_checkpoint(path, state, rng)
            loaded = load_kernel_checkpoint(path, expected_content_version=state.content_version)
            self.bridge.kernel.restore_checkpoint(loaded.state, loaded.rng, expected_revision=state.revision)
        self.assertEqual(state.knowledge, self.bridge.kernel.state.knowledge)
        self.assertEqual([], investigation_invariant(self.bridge.kernel.state))

    def test_read_projection_does_not_mutate_state_and_accepts_empty_additive_ledger(self):
        before = self.bridge.kernel.state.to_dict()
        self.bridge.snapshot()
        self.assertEqual(before, self.bridge.kernel.state.to_dict())
        self.assertEqual([], investigation_invariant(self.bridge.kernel.state))

    def test_corrupt_nested_investigation_records_fail_validation_without_crashing(self):
        key = self.observe()[0]
        state = self.bridge.kernel.state
        ledger = state.knowledge["investigation"]
        corruptions = [
            ("traces", {"bad": {"claim_id": []}}),
            ("notes_by_actor", {"player": {key: {"claim": []}}}),
            ("hypotheses_by_actor", {"player": [{"status": "unverified", "claim_ids": []}]}),
            ("withheld_by_actor", {"player": [[]]}),
            ("last_query_by_pair", {"player|" + self.npc: [1, []]}),
        ]
        for field, bad in corruptions:
            original = ledger[field]
            ledger[field] = bad
            self.assertTrue(investigation_invariant(state), field)
            ledger[field] = original

    def test_surface_search_does_not_reveal_night_ground(self):
        state = self.bridge.kernel._state
        state.inventories["ground"]["night:south_gate_region"] = {"quantities": {"bread_loaf": 1}}
        self.assertFalse(self.bridge.snapshot()["investigation"]["can_search"])
        self.assert_failure("no_new_evidence", "SEARCH_SCENE")

    def test_private_interactions_do_not_create_public_traces(self):
        from simulation.domain.events import SimulationEvent
        state = self.bridge.kernel._state
        before = deepcopy(state.knowledge)
        event = SimulationEvent(event_id="private-test", event_type="NPC_INTERACTION_RESOLVED", day=1,
            phase="morning", minute=0, world_revision=1, command_id="private",
            public_summary="绝不能成为公开证据的私聊文本", actor_ids=(self.npc,), visibility="private")
        project_investigation_events(state, [event])
        self.assertEqual(before, state.knowledge)


if __name__ == "__main__":
    unittest.main()
