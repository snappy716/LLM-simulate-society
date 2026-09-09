"""Explicit preparation thresholds; real consent, delivery, travel and combat."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from simulation.api.server import CampusKernelBridge
from simulation.systems.campus_evidence_insight import options, receipts_valid
from simulation.systems.campus_autonomous_combat import choose_combat_action
from simulation.systems.campus_combat import combat_round_policy_from_state
from simulation.persistence.kernel_checkpoint import save_kernel_checkpoint, load_kernel_checkpoint
from simulation.systems import DeterministicRngPool, campus_combat_invariant
from tests.test_campus_relationship_anchors import prepare_anchor_fixture
from tests.test_campus_anomaly_combat import claim_afterimage
from tests.test_campus_contact_inquiries import as_npc


def prepare_evidence_fixture(bridge):
    target, helper, cid, rid = prepare_anchor_fixture(bridge)
    result = as_npc(bridge, helper, "CONFIRM_RELATIONSHIP_ANCHOR", {"npc_id": target, "case_id": cid,
        "expected_case_revision": bridge.kernel._state.situations["campus_anomalies"]["cases"][cid]["revision"], "source_id": "material:" + rid})
    assert result.success, result.code
    for _ in range(2):
        result = as_npc(bridge, "player", "ADVANCE_PHASE", {})
        assert result.success, result.code
    task = next(t for t in bridge.kernel._state.tasks.values() if t.get("anomaly_case_id") == cid)
    claim_afterimage(bridge, task["task_id"])
    result = as_npc(bridge, "player", "START_BATTLE_PREPARATION", {"task_id": task["task_id"]})
    assert result.success, result.code
    battle = next(b for b in bridge.kernel._state.battles.values() if b.get("situation_id") == task["task_id"])
    bid = battle["battle_id"]
    own = next(c for c in battle["character_cards"].values() if c["actor_id"] == "player")
    for action, params in (("DEPLOY_COMBAT_CHARACTER", {"character_card_instance_id": own["character_card_instance_id"], "destination_row": "front"}),
                           ("CONFIRM_BATTLE_DEPLOYMENT", {}), ("START_CARD_COMBAT", {})):
        result = as_npc(bridge, "player", action, {"battle_id": bid, "expected_battle_revision": bridge.kernel._state.battles[bid]["revision"], **params})
        assert result.success, result.code
    return target, cid, bid


class EvidenceInsightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = CampusKernelBridge(42)
        cls.target, cls.cid, cls.bid = prepare_evidence_fixture(cls.bridge)
        cls.initial, cls.rng = cls.bridge.kernel.capture_checkpoint()

    def setUp(self):
        self.bridge.kernel.restore_checkpoint(self.initial, self.rng, expected_revision=self.bridge.kernel.state.revision)

    @property
    def state(self): return self.bridge.kernel._state
    @property
    def battle(self): return self.state.battles[self.bid]
    @property
    def case(self): return self.state.situations["campus_anomalies"]["cases"][self.cid]
    @property
    def enemy(self): return next(iter(self.battle["enemy_units"]))

    def act(self, action="USE_KNOWLEDGE_INSIGHT", **params):
        return as_npc(self.bridge, "player", action, {"battle_id": self.bid, "expected_battle_revision": self.battle["revision"],
            "target_id": self.enemy, "tactic": "ground", **params})

    def test_actual_sources_unlock_without_revealing_private_case(self):
        view = self.bridge.snapshot()["combat"]["active_battle"]
        ground = next(o for o in view["action_options"]["insights"] if o["tactic"] == "ground")
        self.assertTrue(ground["playable"])
        self.assertEqual(40, ground["mastery"])
        self.assertNotIn("anomaly_origin", view)
        self.assertNotIn("evidence_insight_receipts", view)
        self.assertNotIn(self.cid, json.dumps(ground))
        self.assertNotIn(self.target, json.dumps(ground))

    def test_real_cost_one_skipped_attack_not_remote_support_or_healing(self):
        before = deepcopy((self.case, self.state.population[self.target], self.state.clock, self.state.action_economy))
        health, pollution = deepcopy(self.battle["health"]), deepcopy(self.battle["pollution"])
        self.assertTrue(self.act().success)
        self.assertEqual(2, self.battle["command_points"]["party:player"])
        self.assertEqual(before, (self.case, self.state.population[self.target], self.state.clock, self.state.action_economy))
        self.assertTrue(receipts_valid(self.state, self.battle))
        self.assertTrue(self.act("END_COMBAT_ROUND").success)
        self.assertEqual(health, self.battle["health"])
        self.assertEqual(pollution, self.battle["pollution"])
        self.assertNotIn("knowledge_interrupted", self.battle["enemy_units"][self.enemy]["statuses"])
        self.assertEqual([], list(campus_combat_invariant(self.state)))

    def test_duplicate_does_not_cost_or_rearm_even_next_round(self):
        self.assertTrue(self.act().success)
        self.assertTrue(self.act("END_COMBAT_ROUND").success)
        before = deepcopy(self.battle)
        self.assertFalse(self.act().success)
        self.assertEqual(before, self.battle)
        self.assertTrue(options(self.state, self.battle, "player")[0]["used"])

    def test_same_archetype_without_this_case_source_does_not_qualify(self):
        clone = deepcopy(self.battle)
        clone.pop("anomaly_origin")
        self.assertEqual([], options(self.state, clone, "player"))
        clone["anomaly_origin"] = {"case_id": "another-person-same-monster"}
        self.assertEqual([], options(self.state, clone, "player"))

    def test_lost_reliability_or_current_willingness_blocks_without_cost(self):
        anchor = self.case["anchors"]["player"]
        for key in ("claim_id", "report_claim_id"):
            belief = self.state.knowledge["beliefs_by_actor"]["player"][anchor[key]]
            old = deepcopy(belief)
            belief["distortion"] = .8
            before = deepcopy(self.battle)
            self.assertFalse(self.act().success)
            self.assertEqual(before, self.battle)
            belief.update(old)
        self.state.relationships[self.target]["player"]["trust"] = 0
        self.assertEqual([], options(self.state, self.battle, "player"))

    def test_knowledge_alone_or_foreign_memory_cannot_replace_own_anchor(self):
        anchor = self.case["anchors"].pop("player")
        self.assertEqual([], options(self.state, self.battle, "player"))
        self.case["anchors"]["player"] = anchor
        self.state.knowledge["growth"]["actors"]["player"]["topics"][self.case["topic_id"]]["theory"] = 39
        self.assertEqual([], options(self.state, self.battle, "player"))

    def test_downed_reserve_foreign_actor_and_insufficient_points_rejected(self):
        clone = deepcopy(self.battle)
        clone["health"]["player"] = 0
        from simulation.systems.campus_knowledge_insight import knowledge_insight_options
        self.assertTrue(all(not o["playable"] for o in knowledge_insight_options(self.state, clone, "player")))
        own = next(c for c in clone["character_cards"].values() if c["actor_id"] == "player")
        own["deployment_state"] = "reserve"
        self.assertEqual([], options(self.state, clone, "player"))
        self.assertFalse(self.act(source_actor_id=self.target).success)
        self.battle["command_points"]["party:player"] = 0
        self.assertFalse(self.act().success)

    def test_pending_interrupt_prevents_waste(self):
        self.battle["enemy_units"][self.enemy]["statuses"].append("knowledge_interrupted")
        before = deepcopy(self.battle)
        self.assertFalse(self.act().success)
        self.assertEqual(before, self.battle)

    def test_npc_controller_selects_same_available_tactic_and_real_handler(self):
        view = self.bridge.snapshot()["combat"]["active_battle"]
        action, params = choose_combat_action(self.state, view, "player", combat_round_policy_from_state(self.state))
        self.assertEqual("USE_KNOWLEDGE_INSIGHT", action)
        self.assertEqual("ground", params["tactic"])
        self.assertTrue(self.act(action, **params).success)

    def test_checkpoint_retains_private_provenance_and_rejects_forgery(self):
        self.assertTrue(self.act().success)
        schema = json.loads((Path(__file__).resolve().parents[1] / "contracts/battle_state.schema.json").read_text())
        self.assertEqual(set(schema["properties"]["evidence_insight_receipts"]["items"]["required"]), set(self.battle["evidence_insight_receipts"][0]))
        self.assertNotIn("evidence_insight_receipts", self.bridge.snapshot()["combat"]["active_battle"])
        with TemporaryDirectory() as directory:
            file = Path(directory) / "evidence.json"
            save_kernel_checkpoint(file, self.state, DeterministicRngPool(42))
            loaded = load_kernel_checkpoint(file).state
            self.assertTrue(receipts_valid(loaded, loaded.battles[self.bid]))
        row = self.battle["evidence_insight_receipts"][0]
        row["anchor_id"] = "foreign"
        self.assertFalse(receipts_valid(self.state, self.battle))
        self.battle.pop("evidence_insight_receipts")
        self.assertFalse(receipts_valid(self.state, self.battle))

    def test_old_battle_without_optional_receipt_remains_valid(self):
        self.assertNotIn("evidence_insight_receipts", self.battle)
        self.assertTrue(receipts_valid(self.state, self.battle))
        self.battle["evidence_insight_receipts"] = [{"target_id": self.enemy}]
        self.assertFalse(receipts_valid(self.state, self.battle))


if __name__ == "__main__": unittest.main()
