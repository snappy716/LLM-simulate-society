from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from simulation.api.server import CampusKernelBridge
from simulation.actions.commands import SimulationCommand
from simulation.systems import DeterministicRngPool, ContentRegistry
from simulation.systems.transactions import TransactionContext
from simulation.systems.campus_night_sites import create_night_site, upkeep_night_sites
from simulation.systems.campus_welfare import sync_welfare_cases, advance_welfare, welfare_view, welfare_invariant
from simulation.systems.campus_messaging import _add_contact, load_campus_messaging_policy
from simulation.systems.campus_social import DEFAULT_RELATIONSHIP
from simulation.persistence.kernel_checkpoint import save_kernel_checkpoint, load_kernel_checkpoint
from tests.test_campus_disputes import command


def prepare_welfare_fixture(bridge):
    """Explicit incident placement; source uses the actual stranded-site creator."""
    from tests.test_campus_combat_deployment import travel_to_location
    from simulation.systems.campus_parties import party_for_actor
    from simulation.systems.campus_night_sites import captive_site
    for _ in range(2):
        assert command(bridge, "ADVANCE_PHASE", {})["ok"]
    state = bridge.kernel._state
    victim = next(n for n, actor in state.population.items() if n != "player" and actor.get("role_kind") == "student"
        and not actor.get("active_forum_task_id") and not party_for_actor(state, n) and not captive_site(state, n))
    helper = next(n for n in state.population if n not in ("player", victim))
    travel_to_location(bridge, "south_gate", victim)
    state = bridge.kernel._state
    task = next(t for t in state.tasks.values() if t.get("night_site_id") and t["state"] in {"open", "viewed", "considering"})
    # This fixture relocates an existing post below; discard awareness of its
    # original publication rather than forging an observation of the new place.
    for regions in state.cognition.get("regional_awareness", {}).values():
        for region, notice in list(regions.items()):
            if notice["source_task_id"] == task["task_id"]:
                del regions[region]
    context = TransactionContext(state, DeterministicRngPool(42), SimulationCommand("welfare-fixture", "player", "ADVANCE_PHASE", state.revision))
    create_night_site(context, task, {"kind": "rescue", "label": "受控滞留点", "initial_state": "待脱离",
        "resolved_state": "已安全脱离", "operation": "护送", "safe_location_id": "hospital_clinic"}, victim)
    registry = ContentRegistry.load_default(Path(__file__).resolve().parents[1] / "content")
    sync_welfare_cases(state)
    for who in ("player", helper):
        _add_contact(state, victim, who)
        state.relationships[victim][who] = {**DEFAULT_RELATIONSHIP, "trust": 75}
    return state, victim, helper, context, load_campus_messaging_policy(registry)


class WelfareTests(unittest.TestCase):
    def setUp(self):
        self.bridge = CampusKernelBridge(42)
        self.state, self.victim, self.helper, self.context, self.policy = prepare_welfare_fixture(self.bridge)

    def release(self):
        self.state.clock.day = 2
        self.state.clock.phase = "morning"
        upkeep_night_sites(self.context)

    def check(self, listener="player"):
        from simulation.systems.campus_welfare import make_welfare_handler
        return make_welfare_handler(self.policy)(self.context, SimulationCommand("check", listener, "CHECK_NPC_WELFARE", self.state.revision,
            parameters={"npc_id": self.victim}, issued_day=self.state.clock.day, issued_phase=self.state.clock.phase,
            source="player" if listener == "player" else "rule"))

    def test_unanswered_is_not_missing_or_secret_evidence(self):
        self.assertEqual([], welfare_view(self.state))
        result = self.check()
        self.assertTrue(result.success)
        self.assertEqual("unconfirmed", result.code)
        self.assertIsNone(result.payload["report"]["claim_id"])
        view = welfare_view(self.state)[0]
        self.assertNotIn("site_id", view)
        self.assertNotIn("location_id", view)
        self.assertIn("不证明", view["summary"])
        self.assertEqual([], list(welfare_invariant(self.state)))

    def test_release_reports_real_injury_and_does_not_heal_or_move(self):
        self.check()
        self.release()
        before = deepcopy(self.state.population[self.victim])
        result = self.check()
        self.assertEqual("needs_care", result.code)
        self.assertEqual(before, self.state.population[self.victim])
        claim = self.state.knowledge["claims"][result.payload["report"]["claim_id"]]
        self.assertEqual("voluntary_welfare_report", claim["predicate"])
        self.assertNotIn("night-site", str(claim))
        self.assertNotIn(result.payload["report"]["claim_id"], self.state.knowledge["beliefs_by_actor"][self.helper])

    def test_actual_recovery_required_and_duplicate_check_no_effect(self):
        self.release()
        self.check()
        count = len(self.context.event_drafts)
        self.assertEqual("already_checked", self.check().code)
        self.assertEqual(count, len(self.context.event_drafts))
        # Recovery itself is covered by existing rest/item tests; merely asking
        # above did not do it. Explicit recovered boundary must change report.
        vitals = self.state.population[self.victim]["vitals"]
        vitals["health"] = vitals["max_health"]
        vitals["focus"] = vitals["max_focus"]
        self.assertEqual("recovered", self.check().code)
        self.assertEqual("recovered", welfare_view(self.state)[0]["status"])

    def test_refusal_and_no_contacts_preserve_privacy(self):
        self.release()
        self.state.relationships[self.victim]["player"]["trust"] = 0
        self.assertEqual("report_withheld", self.check().code)
        self.assertEqual([], welfare_view(self.state))
        self.state.cognition["messaging"]["contacts_by_actor"]["player"].remove(self.victim)
        self.state.population["player"]["current_location_id"] = "hospital_clinic"
        self.assertEqual("contact_required", self.check().code)

    def test_npc_initiates_own_follow_up_not_omniscient_outsider(self):
        self.assertEqual(0, advance_welfare(self.context, self.policy)["welfare_reports"])
        self.release()
        self.state.relationships[self.victim][self.helper]["trust"] = 90
        before = deepcopy(self.state.population[self.victim]["vitals"])
        summary = advance_welfare(self.context, self.policy)
        self.assertEqual(1, summary["welfare_reports"])
        self.assertEqual([], welfare_view(self.state))
        self.assertEqual("needs_care", welfare_view(self.state, self.helper)[0]["status"])
        self.assertEqual(before, self.state.population[self.victim]["vitals"])
        self.assertEqual(0, advance_welfare(self.context, self.policy)["welfare_reports"])

    def test_checkpoint_preserves_reports_and_old_terminal_not_reinvented(self):
        self.release()
        self.check()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "welfare.json"
            save_kernel_checkpoint(path, self.state, DeterministicRngPool(42))
            self.assertEqual(self.state.situations["campus_welfare"], load_kernel_checkpoint(path).state.situations["campus_welfare"])
        self.state.situations.pop("campus_welfare")
        self.state.clock.day = 5
        self.assertEqual({}, sync_welfare_cases(self.state)["cases"])

    def test_real_kernel_free_check_and_invalid_target_atomic(self):
        before = self.bridge.kernel.state
        result = command(self.bridge, "CHECK_NPC_WELFARE", {"npc_id": self.victim})
        self.assertTrue(result["ok"], result["result"]["code"])
        after = self.bridge.kernel.state
        self.assertEqual(before.clock, after.clock)
        self.assertEqual(before.inventories, after.inventories)
        self.assertEqual(before.action_economy, after.action_economy)
        self.assertEqual(before.population, after.population)
        self.assertEqual("unknown_npc", command(self.bridge, "CHECK_NPC_WELFARE", {"npc_id": []})["result"]["code"])

    def test_injured_poor_npc_requests_real_help_without_giving_or_healing(self):
        self.release()
        self.state.population[self.victim]["wealth"] = 0
        self.state.inventories["actors"][self.victim]["quantities"].pop("bandage_roll", None)
        self.state.relationships[self.victim]["player"]["trust"] = 100
        before = deepcopy(self.state.inventories)
        health = self.state.population[self.victim]["vitals"]["health"]
        self.assertEqual(1, advance_welfare(self.context, self.policy)["welfare_material_requests"])
        case = next(c for c in self.state.situations["campus_welfare"]["cases"].values() if c["actor_id"] == self.victim)
        request = self.state.cognition["material_assistance"]["requests"][case["assistance_id"]]
        self.assertEqual("player", request["helper_id"])
        self.assertEqual("pending", request["status"])
        self.assertEqual(before, self.state.inventories)
        self.assertEqual(health, self.state.population[self.victim]["vitals"]["health"])

    def test_real_rest_closes_case_new_injury_does_not_reopen_old_story(self):
        from simulation.systems.campus_vitals import recover_by_rest
        self.release()
        self.check()
        self.state.population[self.victim]["current_location_id"] = self.state.population[self.victim]["home_location_id"]
        recover_by_rest(self.context, self.victim)
        self.assertEqual("recovered", self.check().code)
        self.state.population[self.victim]["vitals"]["health"] -= 10
        self.assertEqual("follow_up_closed", self.check().code)
        self.assertEqual("recovered", welfare_view(self.state)[0]["status"])


if __name__ == "__main__":
    unittest.main()
