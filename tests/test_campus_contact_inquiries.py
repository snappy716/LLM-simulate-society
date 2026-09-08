from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
import unittest

from simulation.actions.commands import SimulationCommand
from simulation.api.server import CampusKernelBridge
from simulation.systems.campus_contact_inquiries import contact_inquiries_invariant, advance_contact_inquiries, make_contact_inquiry_handler
from simulation.systems.campus_tasks import complete_assigned_task
from simulation.systems import ContentRegistry, DeterministicRngPool
from simulation.systems.time import load_action_economy_policy
from simulation.systems.transactions import TransactionContext
from simulation.persistence.kernel_checkpoint import save_kernel_checkpoint, load_kernel_checkpoint
from tests.test_campus_welfare import prepare_welfare_fixture
from tests.test_campus_disputes import command
from tests.test_campus_combat_deployment import travel_to_location


def as_npc(bridge, actor, action, parameters):
    state = bridge.kernel._state
    return bridge.kernel.execute(SimulationCommand(str(uuid4()), actor, action, state.revision, parameters=parameters,
        issued_day=state.clock.day, issued_phase=state.clock.phase, source="rule"))


def prepare_inquiry_fixture(bridge):
    _, target, issuer, _, policy = prepare_welfare_fixture(bridge)
    assert as_npc(bridge, issuer, "SEND_PHONE_MESSAGE", {"target_id": target, "text": "方便时告诉我近况。"}).success
    published = as_npc(bridge, issuer, "REQUEST_CONTACT_CHECK", {"target_id": target, "location_id": "south_gate"})
    assert published.success, published.code
    return target, issuer, published.payload["task_id"], policy


class ContactInquiryTests(unittest.TestCase):
    def setUp(self):
        self.bridge = CampusKernelBridge(42)
        self.target, self.issuer, self.task_id, self.policy = prepare_inquiry_fixture(self.bridge)

    @property
    def state(self):
        return self.bridge.kernel._state

    def claim(self):
        return command(self.bridge, "CLAIM_FORUM_TASK", {"task_id": self.task_id,
            "expected_task_revision": self.state.tasks[self.task_id]["lock_revision"]})

    def check(self):
        return command(self.bridge, "COMPLETE_FORUM_TASK", {"task_id": self.task_id,
            "expected_task_revision": self.state.tasks[self.task_id]["lock_revision"]})

    def test_real_source_required_and_public_post_hides_target(self):
        view = self.bridge.snapshot()["tasks"][self.task_id]
        self.assertNotIn("target_name", view["contact_inquiry"])
        self.assertNotIn(self.target, str(view))
        before = deepcopy((self.state.tasks, self.state.situations, self.state.action_economy, self.state.population, self.state.knowledge))
        rejected = command(self.bridge, "REQUEST_CONTACT_CHECK", {"target_id": self.target, "location_id": "south_gate"})
        self.assertFalse(rejected["ok"])
        self.assertEqual("contact_attempt_required", rejected["result"]["code"])
        self.assertEqual(before, (self.state.tasks, self.state.situations, self.state.action_economy, self.state.population, self.state.knowledge))
        self.assertTrue(self.claim()["ok"])
        self.assertEqual(self.state.population[self.target]["display_name"], self.bridge.snapshot()["tasks"][self.task_id]["contact_inquiry"]["target_name"])

    def test_physical_absence_is_dated_evidence_not_missing_and_costs_once(self):
        self.assertTrue(self.claim()["ok"])
        before = deepcopy((self.state.action_economy, self.state.knowledge))
        self.assertFalse(self.check()["ok"])
        self.assertEqual(before, (self.state.action_economy, self.state.knowledge))
        travel_to_location(self.bridge, "south_gate", "player")
        budget = self.state.action_economy["actors"]["player"]["major_remaining"]
        money = {n: a["wealth"] for n, a in self.state.population.items()}
        result = self.check()
        self.assertTrue(result["ok"], result["result"]["code"])
        report = result["result"]["payload"]["contact_report"]
        self.assertFalse(report["seen"])
        self.assertIn("不能据此断定失踪", report["summary"])
        self.assertEqual(budget - 1, self.state.action_economy["actors"]["player"]["major_remaining"])
        self.assertEqual(money, {n: a["wealth"] for n, a in self.state.population.items()})
        self.assertEqual("completed", self.state.tasks[self.task_id]["state"])
        belief = self.state.knowledge["beliefs_by_actor"][self.issuer][report["claim_id"]]
        self.assertEqual("player", belief["source_actor_id"])
        self.assertEqual(1, belief["transmission_count"])
        self.assertNotIn(report["claim_id"], self.state.knowledge["beliefs_by_actor"][self.target])
        self.assertFalse(self.check()["ok"])
        self.assertEqual([], contact_inquiries_invariant(self.state))

    def test_self_certification_and_text_only_completion_blocked(self):
        task = self.state.tasks[self.task_id]
        for who in (self.issuer, self.target):
            result = as_npc(self.bridge, who, "CLAIM_FORUM_TASK", {"task_id": self.task_id, "expected_task_revision": task["lock_revision"]})
            self.assertFalse(result.success)
            self.assertIn(result.code, {"independent_checker_required", "actor_stranded"})
        self.assertTrue(self.claim()["ok"])
        context = TransactionContext(self.state, DeterministicRngPool(42), SimulationCommand("fake", "player", "COMPLETE_FORUM_TASK", self.state.revision))
        self.assertFalse(complete_assigned_task(context, "player", {"task_id": self.task_id}))
        self.assertFalse(complete_assigned_task(context, "player", {"task_id": self.task_id, "contact_report": True}))

    def test_attention_excludes_subject_and_releases_stale_self_claim(self):
        from unittest.mock import patch
        from simulation.systems.campus_forum_attention import advance_forum_attention, _ledger
        from simulation.systems.transactions import TransactionOutcome
        from simulation.systems import load_campus_location_graph
        # Isolate the subject's attention to test the eligibility boundary; the
        # actual incident/post remains real, not a fabricated successful search.
        state = self.state
        ledger = _ledger(state)
        ledger["actors"] = {self.target: {"stage": 0, "due": 1, "order": 0, "task_id": "", "task_revision": 0}}
        context = TransactionContext(state, DeterministicRngPool(42), SimulationCommand("attention-subject", "player", "ADVANCE_SOCIAL_PULSE", state.revision))
        attempts = []
        def handler(context, command):
            attempts.append((command.action_id, command.parameters["task_id"]))
            return TransactionOutcome(False, False, "independent_checker_required", "独立承接者") if command.action_id == "CLAIM_FORUM_TASK" else TransactionOutcome(True, True, "success", "已查看")
        graph = load_campus_location_graph(self.bridge.registry)
        with patch("simulation.systems.campus_forum_attention._eligible", side_effect=lambda s, actor: actor == self.target):
            advance_forum_attention(context, graph, handler)
            self.assertNotIn(("VIEW_FORUM_TASK", self.task_id), attempts)
            ledger["actors"][self.target].update(stage=2, due=1, task_id=self.task_id, task_revision=0)
            advance_forum_attention(context, graph, handler)
            self.assertEqual(0, ledger["actors"][self.target]["stage"])
            self.assertIn(("CLAIM_FORUM_TASK", self.task_id), attempts)
        self.assertIsNone(state.tasks[self.task_id]["assignee_id"])

    def test_incapacitated_npc_does_not_browse_or_claim(self):
        from simulation.systems.campus_forum_attention import _eligible
        self.state.population[self.issuer]["vitals"]["health"] = 0
        self.assertFalse(_eligible(self.state, self.issuer))

    def test_repeated_request_dedup_and_follow_up_only_other_public_point(self):
        before = len(self.state.tasks)
        repeated = as_npc(self.bridge, self.issuer, "REQUEST_CONTACT_CHECK", {"target_id": self.target, "location_id": "campus_security_office"})
        self.assertEqual("already_requested", repeated.code)
        self.assertEqual(before, len(self.state.tasks))
        self.claim()
        travel_to_location(self.bridge, "south_gate", "player")
        self.assertTrue(self.check()["ok"])
        self.assertEqual("already_requested", as_npc(self.bridge, self.issuer, "REQUEST_CONTACT_CHECK", {"target_id": self.target, "location_id": "south_gate"}).code)
        follow = as_npc(self.bridge, self.issuer, "REQUEST_CONTACT_CHECK", {"target_id": self.target, "location_id": "campus_security_office"})
        self.assertTrue(follow.success, follow.code)
        self.assertNotEqual(self.task_id, follow.payload["task_id"])
        first_case = self.state.situations["contact_inquiries"]["cases"][self.state.tasks[self.task_id]["inquiry_id"]]
        next_case = self.state.situations["contact_inquiries"]["cases"][self.state.tasks[follow.payload["task_id"]]["inquiry_id"]]
        self.assertEqual(first_case["report"]["claim_id"], next_case["source_claim_id"])

    def test_actual_contact_resumption_withdraws_without_reward_or_penalty(self):
        self.claim()
        # Actual dawn release plus actual acknowledgment triggers withdrawal.
        for _ in range(2):
            result = command(self.bridge, "ADVANCE_PHASE", {})
            self.assertTrue(result["ok"], result["result"]["code"])
        task = self.state.tasks[self.task_id]
        self.assertIsNone(task["assignee_id"])
        self.assertEqual("withdrawn", self.bridge.snapshot()["tasks"][self.task_id]["contact_inquiry"]["status"])
        self.assertIsNone(task.get("social_result"))
        self.assertFalse(any(h["kind"] == "completed" for h in task["history"]))

    def test_checkpoint_preserves_contact_source_and_report(self):
        self.claim()
        travel_to_location(self.bridge, "south_gate", "player")
        self.assertTrue(self.check()["ok"])
        with TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "inquiry.json"
            save_kernel_checkpoint(checkpoint, self.state, DeterministicRngPool(42))
            restored = load_kernel_checkpoint(checkpoint).state
            self.assertEqual(self.state.situations["contact_inquiries"], restored.situations["contact_inquiries"])
            self.assertEqual([], contact_inquiries_invariant(restored))

    def test_npc_executor_follows_real_path_and_uses_same_report_gate(self):
        # Explicit free, independent student is the checker; task and route are real.
        from simulation.systems.campus_parties import party_for_actor
        checker = next(n for n, a in self.state.population.items() if n not in {"player", self.issuer, self.target}
            and a.get("role_kind") == "student" and not a.get("active_forum_task_id") and not party_for_actor(self.state, n))
        result = as_npc(self.bridge, checker, "CLAIM_FORUM_TASK", {"task_id": self.task_id, "expected_task_revision": self.state.tasks[self.task_id]["lock_revision"]})
        self.assertTrue(result.success, result.code)
        before = self.state.population[checker]["current_location_id"]
        self.assertNotEqual("south_gate", before)
        result = command(self.bridge, "ADVANCE_PHASE", {})
        self.assertTrue(result["ok"], result["result"]["code"])
        case = self.state.situations["contact_inquiries"]["cases"][self.state.tasks[self.task_id]["inquiry_id"]]
        self.assertIsNotNone(case["report"])
        self.assertEqual(checker, case["report"]["actor_id"])
        self.assertEqual("south_gate", case["report"]["location_id"])
        self.assertEqual("completed", self.state.tasks[self.task_id]["state"])

    def test_visible_unresponsive_person_is_seen_without_healing_or_phone_reply(self):
        # Explicit incapacity at a public point, separate from the captive fixture.
        from simulation.systems.campus_messaging import _add_contact
        bridge = CampusKernelBridge(42)
        state = bridge.kernel._state
        target = bridge.snapshot()["messaging"]["contacts"][0]["actor_id"]
        issuer = next(n for n in state.population if n not in {"player", target})
        state.population[target]["vitals"]["health"] = 0
        state.population[target]["current_location_id"] = "south_gate"
        _add_contact(state, issuer, target)
        self.assertTrue(as_npc(bridge, issuer, "SEND_PHONE_MESSAGE", {"target_id": target, "text": "还好吗？"}).success)
        task_id = as_npc(bridge, issuer, "REQUEST_CONTACT_CHECK", {"target_id": target}).payload["task_id"]
        self.assertTrue(command(bridge, "CLAIM_FORUM_TASK", {"task_id": task_id, "expected_task_revision": 0})["ok"])
        travel_to_location(bridge, "south_gate", "player")
        result = command(bridge, "COMPLETE_FORUM_TASK", {"task_id": task_id, "expected_task_revision": bridge.kernel._state.tasks[task_id]["lock_revision"]})
        self.assertTrue(result["ok"], result["result"]["code"])
        self.assertTrue(result["result"]["payload"]["contact_report"]["seen"])
        self.assertEqual(0, bridge.kernel._state.population[target]["vitals"]["health"])
        self.assertEqual("awaiting", bridge.kernel._state.cognition["messaging"]["contact_gaps"][issuer + ">" + target]["status"])
        case = bridge.kernel._state.situations["contact_inquiries"]["cases"][bridge.kernel._state.tasks[task_id]["inquiry_id"]]
        case["report"]["seen"] = False
        self.assertTrue(contact_inquiries_invariant(bridge.kernel._state))

    def test_repeated_actual_npc_attempt_can_publish_on_social_pulse(self):
        bridge = CampusKernelBridge(42)
        _, target, issuer, *_ = prepare_welfare_fixture(bridge)
        self.assertTrue(as_npc(bridge, issuer, "SEND_PHONE_MESSAGE", {"target_id": target, "text": "还方便联系吗？"}).success)
        self.assertTrue(command(bridge, "ADVANCE_PHASE", {})["ok"])
        self.assertTrue(as_npc(bridge, issuer, "SEND_PHONE_MESSAGE", {"target_id": target, "text": "我有些担心，方便时回复。"}).success)
        self.assertFalse(bridge.kernel._state.situations.get("contact_inquiries", {}).get("cases"))
        self.assertTrue(command(bridge, "ADVANCE_SOCIAL_PULSE", {})["ok"])
        cases = list(bridge.kernel._state.situations["contact_inquiries"]["cases"].values())
        self.assertEqual(1, len(cases))
        self.assertEqual(issuer, cases[0]["issuer_id"])
        self.assertEqual(target, cases[0]["target_id"])
        self.assertEqual([], contact_inquiries_invariant(bridge.kernel._state))
