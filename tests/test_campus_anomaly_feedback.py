"""Own real routes and dated disclosure, never inferred remote NPC success."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from simulation.api.server import CampusKernelBridge
from simulation.systems.campus_anomaly_feedback import route_feedback
from simulation.systems.campus_anomalies import anomalies_invariant
from simulation.persistence.kernel_checkpoint import save_kernel_checkpoint, load_kernel_checkpoint
from simulation.systems import DeterministicRngPool
from tests.test_campus_relationship_anchors import prepare_anchor_fixture
from tests.test_campus_anomaly_combat import claim_afterimage, win_afterimage
from tests.test_campus_contact_inquiries import as_npc


def actual_support(bridge, target, cid):
    assert as_npc(bridge, "player", "ASK_ANOMALY_EXPERIENCE", {"npc_id": target}).success
    case = bridge.kernel._state.situations["campus_anomalies"]["cases"][cid]
    result = as_npc(bridge, "player", "SUPPORT_ANOMALY", {"npc_id": target, "case_id": cid, "expected_case_revision": case["revision"]})
    assert result.success, result.code


def actual_night(bridge, target, cid):
    for _ in range(2):
        assert as_npc(bridge, "player", "ADVANCE_PHASE", {}).success
    task = next(t for t in bridge.kernel._state.tasks.values() if t.get("anomaly_case_id") == cid)
    claim_afterimage(bridge, task["task_id"])
    bid = win_afterimage(bridge, task["task_id"])
    assert as_npc(bridge, "player", "EXIT_NIGHT_WORLD", {}).success
    return bid


def prepare_route_fixture(bridge):
    target, _, cid, _ = prepare_anchor_fixture(bridge)
    actual_support(bridge, target, cid)
    bid = actual_night(bridge, target, cid)
    assert as_npc(bridge, "player", "ASK_ANOMALY_EXPERIENCE", {"npc_id": target}).success
    return target, cid, bid


class AnomalyFeedbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = CampusKernelBridge(42)
        cls.target, _, cls.cid, _ = prepare_anchor_fixture(cls.bridge)
        cls.initial, cls.initial_rng = cls.bridge.kernel.capture_checkpoint()
        actual_support(cls.bridge, cls.target, cls.cid)
        cls.bid = actual_night(cls.bridge, cls.target, cls.cid)
        # Keep the older report: later results must not silently refresh it.
        cls.mixed, cls.mixed_rng = cls.bridge.kernel.capture_checkpoint()

    def setUp(self):
        self.bridge.kernel.restore_checkpoint(self.mixed, self.mixed_rng, expected_revision=self.bridge.kernel.state.revision)

    @property
    def state(self): return self.bridge.kernel._state
    @property
    def case(self): return self.state.situations["campus_anomalies"]["cases"][self.cid]

    def view(self, actor="player"): return route_feedback(self.state, self.case, actor)
    def ask(self): return as_npc(self.bridge, "player", "ASK_ANOMALY_EXPERIENCE", {"npc_id": self.target})
    def initial_state(self):
        self.bridge.kernel.restore_checkpoint(self.initial, self.initial_rng, expected_revision=self.bridge.kernel.state.revision)

    def test_mixed_route_only_counts_actual_support_and_resolved_site(self):
        feedback = self.view()
        self.assertEqual("白天支持＋夜间处置", feedback["own_path"])
        self.assertEqual(["day_support", "night_battle"], [r["kind"] for r in feedback["own_records"]])
        self.assertIn("双方各消耗一次主要行动", feedback["own_records"][0]["text"])
        self.assertIn("不是本人心结已经解决", feedback["own_records"][1]["text"])
        self.assertGreater(self.case["core"], 0)
        self.assertEqual(0, self.case["shell"])

    def test_stale_report_stays_dated_after_actual_support_and_night(self):
        report = self.case["reports"]["player"]
        self.assertEqual({"support_sessions": 0, "images": "recurring", "stability": "unsettled"}, report["experience"])
        self.assertIn("共同支持过 0 次", self.view()["statement"])
        self.assertIn("不是实时状态", self.view()["statement"])
        self.assertEqual([], anomalies_invariant(self.state))

    def test_fresh_disclosure_updates_experience_not_health_or_resources(self):
        before = deepcopy((self.state.clock, self.state.action_economy, self.state.population, self.state.inventories))
        self.assertTrue(self.ask().success)
        experience = self.case["reports"]["player"]["experience"]
        self.assertEqual("quiet", experience["images"])
        self.assertEqual("easing", experience["stability"])
        self.assertGreaterEqual(experience["support_sessions"], 1)
        self.assertEqual(before, (self.state.clock, self.state.action_economy, self.state.population, self.state.inventories))
        self.assertNotIn("旧现场", self.case["reports"]["player"]["summary"])

    def test_stranger_cannot_borrow_players_routes_or_private_reports(self):
        stranger = next(n for n in self.state.population if n != self.target and n not in self.case["reports"])
        self.assertEqual({}, self.view(stranger))
        for listener in self.case["reports"]:
            if listener != "player":
                self.assertFalse(any(r["kind"] == "night_battle" for r in self.view(listener)["own_records"]))
        text = json.dumps(self.view(), ensure_ascii=False)
        for secret in (self.cid, self.bid, self.target, "core", "coherence"):
            self.assertNotIn(secret, text)

    def test_old_report_does_not_backfill_information_on_view(self):
        self.case["reports"]["player"].pop("experience")
        before = deepcopy(self.case)
        self.assertIn("不补造历史信息", self.view()["statement"])
        self.assertEqual(before, self.case)
        self.assertEqual([], anomalies_invariant(self.state))

    def test_dated_snapshot_forgery_rejected_and_disk_roundtrip(self):
        with TemporaryDirectory() as directory:
            file = Path(directory) / "routes.json"
            save_kernel_checkpoint(file, self.state, DeterministicRngPool(42))
            restored = load_kernel_checkpoint(file).state
            case = restored.situations["campus_anomalies"]["cases"][self.cid]
            self.assertEqual(self.view(), route_feedback(restored, case, "player"))
        self.case["reports"]["player"]["experience"]["support_sessions"] = 99
        self.assertIn("invalid dated anomaly experience", anomalies_invariant(self.state))

    def test_no_participation_does_not_take_credit_for_other_npcs(self):
        self.initial_state()
        before = deepcopy(self.state)
        self.assertIn("尚无", self.view()["own_path"])
        self.assertEqual([], self.view()["own_records"])
        self.assertEqual(before, self.state)

    def test_day_only_real_cost_does_not_become_night_success(self):
        self.initial_state()
        actual_support(self.bridge, self.target, self.cid)
        self.assertEqual("白天支持", self.view()["own_path"])
        self.assertEqual(0, self.state.action_economy["actors"]["player"]["major_remaining"])
        self.assertGreater(self.case["shell"], 0)

    def test_night_only_does_not_claim_player_did_day_support(self):
        self.initial_state()
        actual_night(self.bridge, self.target, self.cid)
        self.assertEqual("夜间处置", self.view()["own_path"])
        self.assertFalse(any(r["kind"] == "day_support" for r in self.view()["own_records"]))
        self.assertGreater(self.case["core"], 0)

    def test_guide_distinguishes_costs_and_does_not_promise_healing(self):
        guide = {r["route"]: r["note"] for r in self.view()["route_guide"]}
        self.assertIn("双方各一次主要行动", guide["day"])
        self.assertIn("后续战斗延续资源消耗", guide["night"])
        self.assertIn("重新询问本人", guide["mixed"])

    def test_actual_retreat_keeps_costs_without_crediting_containment(self):
        from tests.test_campus_evidence_insight import prepare_evidence_fixture
        bridge = CampusKernelBridge(42)
        target, cid, bid = prepare_evidence_fixture(bridge)
        state = bridge.kernel._state
        before_case = deepcopy(state.situations["campus_anomalies"]["cases"][cid])
        health = state.population["player"]["vitals"]["health"]
        result = as_npc(bridge, "player", "RETREAT_CARD_COMBAT", {"battle_id": bid, "expected_battle_revision": state.battles[bid]["revision"]})
        self.assertTrue(result.success, result.code)
        state = bridge.kernel._state
        case = state.situations["campus_anomalies"]["cases"][cid]
        feedback = route_feedback(state, case, "player")
        self.assertIn("尚无", feedback["own_path"])
        self.assertIn("已撤退，未完成封控", feedback["own_records"][0]["text"])
        self.assertLess(state.population["player"]["vitals"]["health"], health)
        self.assertEqual(before_case, case)

    def test_night_finishes_only_after_real_day_support_already_resolved_core(self):
        bridge = CampusKernelBridge(42)
        target, _, cid, rid = prepare_anchor_fixture(bridge)
        state = bridge.kernel._state
        case = state.situations["campus_anomalies"]["cases"][cid]
        self.assertTrue(as_npc(bridge, "player", "CONFIRM_RELATIONSHIP_ANCHOR", {"npc_id": target, "case_id": cid,
            "expected_case_revision": case["revision"], "source_id": "material:" + rid}).success)
        case = bridge.kernel._state.situations["campus_anomalies"]["cases"][cid]
        self.assertTrue(as_npc(bridge, "player", "SUPPORT_ANOMALY", {"npc_id": target, "case_id": cid,
            "expected_case_revision": case["revision"], "anchor_id": case["anchors"]["player"]["anchor_id"]}).success)
        for _ in range(2):
            self.assertTrue(as_npc(bridge, "player", "ADVANCE_PHASE", {}).success)
        state = bridge.kernel._state
        held = next(t for t in state.tasks.values() if t.get("anomaly_case_id") == cid and t["created_day"] == state.clock.day)
        # Legitimately hold the first night's task without completing it, so
        # another NPC cannot clear this fixture's shell before the next support.
        claim_afterimage(bridge, held["task_id"])
        for _ in range(2):
            self.assertTrue(as_npc(bridge, "player", "ADVANCE_PHASE", {}).success)
        state = bridge.kernel._state
        case = state.situations["campus_anomalies"]["cases"][cid]
        if case["core"]:
            # Explicit free-slot boundary only; never inject support/results or
            # change clocks. All four phase transitions above are actual.
            for who in ("player", target):
                state.action_economy["actors"][who]["major_remaining"] = 1
            from tests.test_campus_combat_deployment import travel_to_location
            travel_to_location(bridge, state.population[target]["current_location_id"])
            actual_support(bridge, target, cid)
        self.assertEqual(0, bridge.kernel._state.situations["campus_anomalies"]["cases"][cid]["core"])
        for _ in range(2):
            self.assertTrue(as_npc(bridge, "player", "ADVANCE_PHASE", {}).success)
        state = bridge.kernel._state
        task = next(t for t in state.tasks.values() if t.get("anomaly_case_id") == cid and t["created_day"] == state.clock.day)
        claim_afterimage(bridge, task["task_id"])
        person = deepcopy(bridge.kernel._state.population[target])
        win_afterimage(bridge, task["task_id"])
        state = bridge.kernel._state
        case = state.situations["campus_anomalies"]["cases"][cid]
        self.assertEqual((0, 0, 0, "resolved"), tuple(case[k] for k in ("shell", "core", "coherence", "status")))
        self.assertEqual(person, state.population[target])
        self.assertEqual([], anomalies_invariant(state))
        self.assertTrue(as_npc(bridge, "player", "EXIT_NIGHT_WORLD", {}).success)
        self.assertTrue(as_npc(bridge, "player", "ASK_ANOMALY_EXPERIENCE", {"npc_id": target}).success)
        state = bridge.kernel._state
        case = state.situations["campus_anomalies"]["cases"][cid]
        self.assertEqual("stable", case["reports"]["player"]["experience"]["stability"])
        self.assertIn("已能区分", route_feedback(state, case, "player")["statement"])


if __name__ == "__main__": unittest.main()
