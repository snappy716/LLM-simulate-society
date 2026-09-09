from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from simulation.api.server import CampusKernelBridge
from simulation.domain.cognition import BoundedDecisionRequest
from simulation.systems.campus_cognition import bind_cognition_identity
from simulation.systems.campus_contact_leads import CHECK_POINTS, known_contact_leads, contact_check_options, contact_leads_invariant
from simulation.systems.campus_messaging import _add_contact, phone_available
from simulation.systems.campus_vitals import actor_layer
from simulation.persistence.kernel_checkpoint import save_kernel_checkpoint, load_kernel_checkpoint
from tests.test_campus_disputes import command
from tests.test_campus_contact_inquiries import as_npc
from tests.test_campus_combat_deployment import travel_to_location


def prepare_contact_lead_fixture(bridge):
    """Real NPC work receipt and actual permitted sharing; explicit incapacity."""
    for _ in range(2):
        assert command(bridge, "ADVANCE_PHASE", {})["ok"]
    state = bridge.kernel._state
    claim = next(c for c in state.knowledge["claims"].values()
        if c.get("predicate") == "task_completed" and c.get("source_context", {}).get("location_id") in {"library_reading_hall", "canteen_dining_hall"}
        and state.tasks[c["object_id"]]["forum"] == "surface"
        and actor_layer(state, state.tasks[c["object_id"]]["issuer_id"]) == "surface"
        and phone_available(state, state.tasks[c["object_id"]]["issuer_id"]))
    target, issuer, location, claim_id = claim["subject_id"], state.tasks[claim["object_id"]]["issuer_id"], claim["source_context"]["location_id"], claim["claim_id"]
    travel_to_location(bridge, "south_gate", issuer)
    travel_to_location(bridge, "south_gate", "player")
    shared = as_npc(bridge, issuer, "SHARE_EVIDENCE", {"claim_id": claim_id, "target_id": "player"})
    assert shared.success and shared.payload["shared"], shared.code
    state = bridge.kernel._state
    # Unresponsiveness is deliberately imposed to test the inquiry gate, not
    # claimed as a naturally occurring missing-person storyline.
    state.population[target]["vitals"]["health"] = 0
    for actor in ("player", issuer):
        _add_contact(state, actor, target)
    return target, issuer, location, claim_id


class ContactLeadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = CampusKernelBridge(42)
        cls.target, cls.issuer, cls.location, cls.claim_id = prepare_contact_lead_fixture(cls.bridge)
        cls.initial, cls.rng = cls.bridge.kernel.capture_checkpoint()

    def setUp(self):
        self.bridge.kernel.restore_checkpoint(self.initial, self.rng, expected_revision=self.bridge.kernel.state.revision)

    @property
    def state(self):
        return self.bridge.kernel._state

    def send(self, actor="player"):
        return as_npc(self.bridge, actor, "SEND_PHONE_MESSAGE", {"target_id": self.target, "text": "方便时回个消息。"})

    def test_actual_shared_record_ranks_point_not_live_target_location(self):
        leads = known_contact_leads(self.state, "player", self.target)
        self.assertEqual(self.claim_id, leads[0]["claim_id"])
        self.assertEqual(self.location, contact_check_options(self.state, "player", self.target)[0]["location_id"])
        original = deepcopy(leads)
        self.state.population[self.target]["current_location_id"] = "campus_security_office"
        self.assertEqual(original, known_contact_leads(self.state, "player", self.target))
        outsider = next(n for n in self.state.population if n not in {"player", self.target, self.issuer}
            and self.claim_id not in self.state.knowledge["beliefs_by_actor"][n])
        self.assertNotIn(self.claim_id, [r["claim_id"] for r in known_contact_leads(self.state, outsider, self.target)])

    def test_stale_distorted_low_confidence_and_hidden_layer_records_not_recommended(self):
        belief = self.state.knowledge["beliefs_by_actor"]["player"][self.claim_id]
        original = deepcopy(belief)
        for field, value in (("confidence", .1), ("distortion", .9)):
            belief.update(original)
            belief[field] = value
            self.assertNotIn(self.claim_id, [r["claim_id"] for r in known_contact_leads(self.state, "player", self.target)])
        belief.update(original)
        source = self.state.knowledge["claims"][self.claim_id]["source_context"]
        source["layer"] = "night"
        self.assertNotIn(self.claim_id, [r["claim_id"] for r in known_contact_leads(self.state, "player", self.target)])
        source["layer"] = "surface"
        self.state.clock.day += 3
        self.assertNotIn(self.claim_id, [r["claim_id"] for r in known_contact_leads(self.state, "player", self.target)])

    def test_real_request_retains_private_source_and_opening_hours(self):
        self.assertEqual("reply_pending", self.send().code)
        result = command(self.bridge, "REQUEST_CONTACT_CHECK", {"target_id": self.target, "location_id": self.location})
        self.assertTrue(result["ok"], result["result"]["code"])
        task_id = result["result"]["payload"]["task_id"]
        task = self.state.tasks[task_id]
        case = self.state.situations["contact_inquiries"]["cases"][task["inquiry_id"]]
        self.assertEqual(self.claim_id, case["decision_basis"]["source_claim_id"])
        self.assertEqual(list(self.state.places[self.location]["open_phases"]), task["allowed_phases"])
        self.assertNotIn("late_night", task["allowed_phases"])
        from simulation.systems.campus_contact_inquiries import contact_inquiry_view
        self.assertNotIn("decision_basis", contact_inquiry_view(self.state, self.issuer, task))
        self.assertNotIn(self.claim_id, str({k: v for k, v in self.bridge.snapshot()["tasks"][task_id].items() if k != "contact_inquiry"}))
        self.assertTrue(all(not option["available"] for option in contact_check_options(self.state, "player", self.target)))
        with TemporaryDirectory() as directory:
            file = Path(directory) / "leads.json"
            state, rng = self.bridge.kernel.capture_checkpoint()
            save_kernel_checkpoint(file, state, rng)
            restored = load_kernel_checkpoint(file).state
            self.assertEqual([], contact_leads_invariant(restored))
            restored.situations["contact_inquiries"]["cases"][case["case_id"]]["decision_basis"]["source_claim_id"] = "invented"
            self.assertTrue(contact_leads_invariant(restored))

    def test_npc_two_real_attempts_choose_known_point_and_preserve_next_day_context(self):
        from simulation.systems.campus_night_sites import create_night_site
        from tests.test_campus_situations import context_for
        task = next(t for t in self.state.tasks.values() if t.get("night_site_id") and t["state"] in {"open", "viewed", "considering"})
        for regions in self.state.cognition.get("regional_awareness", {}).values():
            for region, notice in list(regions.items()):
                if notice["source_task_id"] == task["task_id"]:
                    del regions[region]
        # Explicit real-site confinement lasts across evening -> late night;
        # ordinary rest must remain able to heal the non-confined fixture.
        create_night_site(context_for(self.state), task, {"kind": "rescue", "label": "受控持续联系中断",
            "initial_state": "待脱离", "resolved_state": "已脱离", "operation": "护送", "safe_location_id": "hospital_clinic"}, self.target)
        self.assertEqual("reply_pending", self.send(self.issuer).code)
        self.assertTrue(command(self.bridge, "ADVANCE_PHASE", {})["ok"])
        self.assertEqual("reply_pending", self.send(self.issuer).code)
        self.assertTrue(command(self.bridge, "ADVANCE_SOCIAL_PULSE", {})["ok"])
        cases = [c for c in self.state.situations["contact_inquiries"]["cases"].values() if c["issuer_id"] == self.issuer and c["target_id"] == self.target]
        self.assertEqual(1, len(cases))
        self.assertEqual(self.location, cases[0]["location_id"])
        request = BoundedDecisionRequest(self.issuer, 1, self.state.clock.day, self.state.clock.phase, {}, {}, "", (), ())
        own = bind_cognition_identity(self.state, request).state["own_contact_leads"]
        self.assertTrue(any(r["target_id"] == self.target and r["leads"] for r in own))
        request = BoundedDecisionRequest("player", 1, self.state.clock.day, self.state.clock.phase, {}, {}, "", (), ())
        self.assertEqual([], bind_cognition_identity(self.state, request).state["own_contact_leads"])

    def test_library_or_canteen_check_requires_real_arrival_and_one_action(self):
        self.assertEqual("reply_pending", self.send(self.issuer).code)
        result = as_npc(self.bridge, self.issuer, "REQUEST_CONTACT_CHECK", {"target_id": self.target, "location_id": self.location})
        self.assertTrue(result.success, result.code)
        task_id = result.payload["task_id"]
        self.assertTrue(command(self.bridge, "CLAIM_FORUM_TASK", {"task_id": task_id, "expected_task_revision": 0})["ok"])
        params = {"task_id": task_id, "expected_task_revision": self.state.tasks[task_id]["lock_revision"]}
        self.assertEqual("task_location_required", command(self.bridge, "CHECK_CONTACT_LOCATION", params)["result"]["code"])
        travel_to_location(self.bridge, self.location, "player")
        before = self.state.action_economy["actors"]["player"]["major_remaining"]
        from simulation.systems.campus_contact_inquiries import make_contact_inquiry_handler
        from simulation.systems.campus_messaging import load_campus_messaging_policy
        from simulation.systems.time import load_action_economy_policy
        from simulation.actions.commands import SimulationCommand
        from simulation.systems.transactions import TransactionContext
        from simulation.systems import DeterministicRngPool
        closed = self.state.clone()
        closed.clock.phase = "late_night"
        closed_command = SimulationCommand("closed-point", "player", "CHECK_CONTACT_LOCATION", closed.revision,
            parameters=params, issued_day=closed.clock.day, issued_phase=closed.clock.phase)
        refused = make_contact_inquiry_handler(load_action_economy_policy(self.bridge.registry), load_campus_messaging_policy(self.bridge.registry))(
            TransactionContext(closed, DeterministicRngPool(42), closed_command), closed_command)
        self.assertEqual("task_time_unavailable", refused.code)
        self.assertEqual(before, closed.action_economy["actors"]["player"]["major_remaining"])
        checked = command(self.bridge, "CHECK_CONTACT_LOCATION", params)
        self.assertTrue(checked["ok"], checked["result"]["code"])
        self.assertEqual(before - 1, self.state.action_economy["actors"]["player"]["major_remaining"])
        self.assertEqual(self.location, checked["result"]["payload"]["contact_report"]["location_id"])

    def test_fallback_is_not_a_location_fact_and_private_rooms_never_candidates(self):
        self.state.knowledge["beliefs_by_actor"]["player"].clear()
        options = contact_check_options(self.state, "player", self.target)
        self.assertEqual(set(CHECK_POINTS), {r["location_id"] for r in options})
        self.assertTrue(all(r["lead"] is None and "不代表对方位置" in r["basis"] for r in options))
        self.assertFalse(any("dorm" in r["location_id"] or "hospital" in r["location_id"] for r in options))


if __name__ == "__main__":
    unittest.main()
