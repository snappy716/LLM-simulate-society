from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from simulation.api.server import CampusKernelBridge
from simulation.actions.commands import SimulationCommand
from simulation.systems.transactions import TransactionContext
from simulation.systems import DeterministicRngPool
from simulation.systems.campus_anomalies import anomalies_invariant, anomaly_view, advance_anomaly_support
from simulation.systems.campus_relationship_anchors import sources, use_problem
from simulation.systems.campus_growth import _actor_growth, _topic_progress
from simulation.systems.campus_social import DEFAULT_RELATIONSHIP
from simulation.systems.campus_messaging import _add_contact
from simulation.persistence.kernel_checkpoint import save_kernel_checkpoint, load_kernel_checkpoint
from tests.test_campus_anomalies import prepare_anomaly_fixture
from tests.test_campus_contact_inquiries import as_npc
from tests.test_campus_combat_deployment import travel_to_location


def prepare_anchor_fixture(bridge, npc_helper=False):
    target, other, cid = prepare_anomaly_fixture(bridge)
    helper = other if npc_helper else "player"
    state = bridge.kernel._state
    # Explicit need, supply, trust and knowledge thresholds. Requests, assent,
    # physical delivery and the resulting evidence must be real shared actions.
    for a, b in ((helper, target), (target, helper)):
        state.relationships[a][b] = {**DEFAULT_RELATIONSHIP, "trust": 80}
    state.population[helper]["personality"].update(altruism=100, agreeableness=100)
    state.population[helper]["needs"].update(rest=0, food=0, safety=0, money=0)
    state.inventories["actors"][helper]["quantities"]["blank_notebook"] = 2
    state.inventories["actors"][target]["quantities"].pop("blank_notebook", None)
    case = state.situations["campus_anomalies"]["cases"][cid]
    _topic_progress(_actor_growth(state, helper), case["topic_id"])["theory"] = 40
    _add_contact(state, target, helper)
    for row in list(state.cognition.get("material_assistance", {}).get("requests", {}).values()):
        if row["requester_id"] == target and row["status"] in {"pending", "accepted"}:
            assert as_npc(bridge, target, "CANCEL_MATERIAL_HELP", {"request_id": row["request_id"]}).success
    requested = as_npc(bridge, target, "REQUEST_MATERIAL_HELP", {"helper_id": helper, "item_id": "blank_notebook"})
    assert requested.success, requested.code
    rid = requested.payload["request"]["request_id"]
    if helper == "player":
        assert as_npc(bridge, helper, "RESPOND_MATERIAL_HELP", {"request_id": rid, "accepted": True}).success
    delivered = as_npc(bridge, helper, "DELIVER_MATERIAL_HELP", {"request_id": rid})
    assert delivered.success, delivered.code
    assert as_npc(bridge, helper, "ASK_ANOMALY_EXPERIENCE", {"npc_id": target}).success
    return target, helper, cid, rid


class RelationshipAnchorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = CampusKernelBridge(42)
        cls.target, cls.helper, cls.cid, cls.rid = prepare_anchor_fixture(cls.bridge)
        cls.initial, cls.rng = cls.bridge.kernel.capture_checkpoint()

    def setUp(self):
        self.bridge.kernel.restore_checkpoint(self.initial, self.rng, expected_revision=self.bridge.kernel.state.revision)
        self.bridge.cognition_runtime.configure_rule()

    @property
    def state(self): return self.bridge.kernel._state

    @property
    def case(self): return self.state.situations["campus_anomalies"]["cases"][self.cid]

    def act(self, action, **params):
        return as_npc(self.bridge, self.helper, action, {"npc_id": self.target, "case_id": self.cid,
            "expected_case_revision": self.case["revision"], **params})

    def confirm(self):
        result = self.act("CONFIRM_RELATIONSHIP_ANCHOR", source_id="material:" + self.rid)
        self.assertTrue(result.success, result.code)
        return result.payload["anchor"]["anchor_id"]

    def test_source_requires_completed_real_need_not_assent_or_ordinary_gift(self):
        self.assertIn("material:" + self.rid, [row["source_id"] for row in sources(self.state, self.case, self.helper)])
        row = self.state.cognition["material_assistance"]["requests"][self.rid]
        self.assertEqual(1, row["receipt"]["helper_before"] - row["receipt"]["helper_after"])
        row["status"] = "accepted"
        self.assertEqual([], sources(self.state, self.case, self.helper))
        self.assertEqual("shared_source_required", self.act("CONFIRM_RELATIONSHIP_ANCHOR", source_id="gift:anything").code)

    def test_confirmation_is_free_private_idempotent_and_not_support(self):
        before = deepcopy((self.state.clock, self.state.action_economy, self.state.population, self.state.inventories, self.case["history"]))
        anchor_id = self.confirm()
        self.assertEqual(before, (self.state.clock, self.state.action_economy, self.state.population, self.state.inventories, self.case["history"]))
        self.assertEqual(anchor_id, self.confirm())
        self.assertEqual(1, len(self.case["anchors"]))
        claim_id = self.case["anchors"][self.helper]["claim_id"]
        stranger = next(w for w in self.state.population if w not in {self.helper, self.target})
        self.assertNotIn(claim_id, self.state.knowledge["beliefs_by_actor"][stranger])
        self.assertNotIn("anchors", self.bridge.snapshot()["population"][self.target])
        self.assertEqual([], anomalies_invariant(self.state))

    def test_forged_or_foreign_source_and_stale_case_rejected(self):
        self.assertEqual("shared_source_required", self.act("CONFIRM_RELATIONSHIP_ANCHOR", source_id=[]).code)
        self.assertEqual("case_revision_conflict", self.act("CONFIRM_RELATIONSHIP_ANCHOR", source_id="material:" + self.rid, expected_case_revision=True).code)
        self.assertEqual("owned_anchor_required", self.act("SUPPORT_ANOMALY", anchor_id="foreign").code)
        self.assertNotIn("anchors", self.case)

    def test_knowledge_and_current_consent_checked_before_cost(self):
        aid = self.confirm()
        before = deepcopy(self.state.action_economy)
        _topic_progress(_actor_growth(self.state, self.helper), self.case["topic_id"])["theory"] = 20
        self.assertEqual("anchor_knowledge_required", self.act("SUPPORT_ANOMALY", anchor_id=aid).code)
        _topic_progress(_actor_growth(self.state, self.helper), self.case["topic_id"])["theory"] = 40
        self.state.relationships[self.target][self.helper]["trust"] = 55
        self.assertEqual("anchor_withheld", self.act("SUPPORT_ANOMALY", anchor_id=aid).code)
        self.assertEqual(before, self.state.action_economy)
        self.assertEqual([], self.case["history"])

    def test_genuine_anchor_support_changes_case_not_health_and_cannot_stack(self):
        aid = self.confirm()
        before = deepcopy((self.state.clock, self.state.population, self.state.inventories))
        self.assertTrue(self.act("SUPPORT_ANOMALY", anchor_id=aid).success)
        self.assertEqual((20, 20, 30), tuple(self.case[k] for k in ("shell", "core", "coherence")))
        self.assertEqual(before, (self.state.clock, self.state.population, self.state.inventories))
        self.assertEqual([0, 0], [self.state.action_economy["actors"][w]["major_remaining"] for w in (self.target, self.helper)])
        self.assertEqual("anchor_already_applied", use_problem(self.state, self.case, self.helper, aid)[0])
        self.assertEqual(aid, self.case["history"][-1]["anchor_id"])
        self.assertEqual([], anomalies_invariant(self.state))

    def test_remote_confirmation_allowed_but_support_requires_actual_meeting(self):
        travel_to_location(self.bridge, "library_reading_hall", self.helper)
        aid = self.confirm()
        self.assertEqual("same_location_required", self.act("SUPPORT_ANOMALY", anchor_id=aid).code)
        self.assertEqual([], self.case["history"])

    def test_old_report_or_unreliable_anchor_does_not_unlock_effect(self):
        aid = self.confirm()
        claim_id = self.case["anchors"][self.helper]["claim_id"]
        self.state.knowledge["beliefs_by_actor"][self.helper][claim_id]["distortion"] = .8
        self.assertEqual("reliable_anchor_required", self.act("SUPPORT_ANOMALY", anchor_id=aid).code)
        self.state.knowledge["beliefs_by_actor"][self.helper][claim_id]["distortion"] = 0
        self.assertTrue(self.act("SUPPORT_ANOMALY").success)
        self.assertEqual("fresh_report_required", self.act("CONFIRM_RELATIONSHIP_ANCHOR", source_id="material:" + self.rid).code)

    def test_confirmed_anchor_survives_disk_and_corrupt_source_rejected(self):
        self.confirm()
        with TemporaryDirectory() as directory:
            path = Path(directory) / "anchor.json"
            save_kernel_checkpoint(path, self.state, DeterministicRngPool(42))
            restored = load_kernel_checkpoint(path).state
            self.assertEqual([], anomalies_invariant(restored))
            restored.situations["campus_anomalies"]["cases"][self.cid]["anchors"][self.helper]["source_id"] = "material:invented"
            self.assertIn("invalid relationship anchor source", anomalies_invariant(restored))

    def test_private_own_context_contains_anchor_not_worldwide_anchors(self):
        aid = self.confirm()
        row = next(r for r in anomaly_view(self.state, self.helper) if r["case_id"] == self.cid)
        self.assertEqual(aid, row["confirmed_anchor"]["anchor_id"])
        self.assertTrue(row["can_use_anchor"])
        self.assertFalse({"shell", "core", "coherence"} & row.keys())
        stranger = next(w for w in self.state.population if w not in {self.helper, self.target})
        self.assertFalse(any(r.get("confirmed_anchor") for r in anomaly_view(self.state, stranger)))

    def test_same_day_support_does_not_manufacture_independent_past(self):
        self.assertTrue(self.act("SUPPORT_ANOMALY").success)
        self.assertNotIn("support:1", [row["source_id"] for row in sources(self.state, self.case, self.helper)])

    def test_overnight_model_context_contains_only_own_dated_anchor(self):
        from dataclasses import replace
        from simulation.domain.cognition import BoundedDecisionRequest
        from simulation.systems.campus_cognition import bind_cognition_identity
        self.confirm()
        request = BoundedDecisionRequest(self.helper, self.state.revision, self.state.clock.day, self.state.clock.phase, {}, {}, "", (), ())
        own = bind_cognition_identity(self.state, request).state["own_confirmed_relationship_anchors"]
        self.assertEqual(1, len(own))
        self.assertEqual(self.target, own[0]["npc_id"])
        self.assertIn("当面交付", own[0]["summary"])
        self.assertNotIn("case_id", own[0])
        stranger = next(w for w in self.state.population if w not in {self.helper, self.target})
        self.assertEqual([], bind_cognition_identity(self.state, replace(request, npc_id=stranger)).state["own_confirmed_relationship_anchors"])

    def test_npc_uses_same_confirmation_and_effect_without_player(self):
        bridge = CampusKernelBridge(42)
        target, helper, cid, _ = prepare_anchor_fixture(bridge, npc_helper=True)
        state = bridge.kernel._state
        weekly = str((state.clock.day - 1) % 7)
        for who in (helper, target):
            state.population[who]["weekly_schedule"][weekly][state.clock.phase]["priority"] = 20
        before = deepcopy(state.population["player"])
        context = TransactionContext(state, DeterministicRngPool(42), SimulationCommand("anchor-npc-boundary", "player", "ADVANCE_PHASE", state.revision))
        self.assertEqual(1, advance_anomaly_support(context)["anomaly_supports"])
        case = state.situations["campus_anomalies"]["cases"][cid]
        self.assertIn(helper, case["anchors"])
        self.assertIn("anchor_id", case["history"][-1])
        self.assertEqual(before, state.population["player"])
        self.assertEqual([], anomalies_invariant(state))


if __name__ == "__main__": unittest.main()
