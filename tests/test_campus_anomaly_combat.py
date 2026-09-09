from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from simulation.api.server import CampusKernelBridge
from simulation.actions.commands import SimulationCommand
from simulation.systems import DeterministicRngPool
from simulation.systems.transactions import TransactionContext
from simulation.systems.campus_anomalies import anomalies_invariant
from simulation.systems.campus_anomaly_combat import afterimage_invariant, pending_afterimages
from simulation.systems.campus_night_sites import site_exposure, upkeep_night_sites
from simulation.systems.campus_night_tasks import _expire_previous_night
from simulation.systems.campus_tasks import complete_assigned_task
from simulation.persistence.kernel_checkpoint import save_kernel_checkpoint, load_kernel_checkpoint
from tests.test_campus_anomalies import prepare_anomaly_fixture
from tests.test_campus_disputes import command
from tests.test_campus_contact_inquiries import as_npc
from tests.test_campus_combat_deployment import travel_to_location


def prepare_afterimage_fixture(bridge, *, support=False):
    target, helper, case_id = prepare_anomaly_fixture(bridge)
    if support:
        assert command(bridge, "ASK_ANOMALY_EXPERIENCE", {"npc_id": target})["ok"]
        assert command(bridge, "SUPPORT_ANOMALY", {"npc_id": target, "case_id": case_id, "expected_case_revision": 0})["ok"]
    for _ in range(2):
        result = command(bridge, "ADVANCE_PHASE", {})
        assert result["ok"], result["result"]
    task = next(t for t in bridge.kernel._state.tasks.values() if t.get("anomaly_case_id") == case_id)
    return target, case_id, task["task_id"]


def claim_afterimage(bridge, task_id):
    assert command(bridge, "ENTER_NIGHT_WORLD", {})["ok"]
    task = bridge.kernel._state.tasks[task_id]
    result = command(bridge, "CLAIM_FORUM_TASK", {"task_id": task_id, "expected_task_revision": task["lock_revision"]})
    assert result["ok"], result["result"]
    travel_to_location(bridge, task["scene_id"])


def win_afterimage(bridge, task_id):
    from tests.test_campus_night_sites import NightSitesTests
    fixture = NightSitesTests()
    fixture.bridge, fixture.task_id, fixture.counter = bridge, task_id, 0
    return fixture.battle()  # Real deployments, cards and enemy turns. No injected win.


class AnomalyCombatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = CampusKernelBridge(42)
        cls.target, cls.case_id, cls.task_id = prepare_afterimage_fixture(cls.bridge)
        cls.initial, cls.rng = cls.bridge.kernel.capture_checkpoint()

    def setUp(self):
        self.bridge.kernel.restore_checkpoint(self.initial, self.rng, expected_revision=self.bridge.kernel.state.revision)

    @property
    def state(self):
        return self.bridge.kernel._state

    @property
    def case(self):
        return self.state.situations["campus_anomalies"]["cases"][self.case_id]

    def test_real_source_anonymous_publication_within_twenty_not_live_npc_tracking(self):
        task = self.state.tasks[self.task_id]
        source = self.state.situations["night_sites"]["sites"][self.case_id]
        self.assertEqual(source["location_id"], task["scene_id"])
        self.assertEqual(20, sum(t.get("forum") == "night" and t["created_day"] == 2 for t in self.state.tasks.values()))
        self.assertNotIn(self.task_id, self.bridge.snapshot()["tasks"])
        self.assertTrue(command(self.bridge, "ENTER_NIGHT_WORLD", {})["ok"])
        view = self.bridge.snapshot()["tasks"][self.task_id]
        self.assertNotIn("anomaly_case_id", view)
        self.assertEqual("", view["night_site"]["victim_name"])
        self.assertNotIn(self.state.population[self.target]["display_name"], view["description"])
        self.state.population[self.target]["current_location_id"] = "hospital_clinic"
        self.assertEqual(source["location_id"], self.state.tasks[self.task_id]["scene_id"])
        self.assertEqual([], afterimage_invariant(self.state))

    def test_actual_card_victory_clears_shell_not_person_or_core_and_no_duplicate(self):
        claim_afterimage(self.bridge, self.task_id)
        person = deepcopy(self.state.population[self.target])
        exposure = site_exposure(self.state, "player")
        bid = win_afterimage(self.bridge, self.task_id)
        self.assertEqual("victory", self.state.battles[bid]["result"])
        self.assertEqual((0, 60, 40, "easing"), tuple(self.case[k] for k in ("shell", "core", "coherence", "status")))
        self.assertEqual(person, self.state.population[self.target])
        self.assertEqual("completed", self.state.tasks[self.task_id]["state"])
        self.assertLess(site_exposure(self.state, "player"), exposure)
        self.assertEqual([], anomalies_invariant(self.state))
        self.assertEqual([], afterimage_invariant(self.state))
        old = deepcopy(self.case)
        result = command(self.bridge, "RESOLVE_NIGHT_SITE", {"task_id": self.task_id,
            "expected_task_revision": self.state.tasks[self.task_id]["lock_revision"]})
        self.assertFalse(result["ok"])
        self.assertEqual(old, self.case)
        self.assertNotIn(self.case_id, [c["case_id"] for c in pending_afterimages(self.state)])

    def test_day_support_weakens_actual_enemy_without_exposing_case(self):
        bridge = CampusKernelBridge(42)
        _, case_id, task_id = prepare_afterimage_fixture(bridge, support=True)
        claim_afterimage(bridge, task_id)
        result = command(bridge, "START_BATTLE_PREPARATION", {"task_id": task_id})
        self.assertTrue(result["ok"], result["result"])
        state = bridge.kernel._state
        case = state.situations["campus_anomalies"]["cases"][case_id]
        battle = next(b for b in state.battles.values() if b.get("situation_id") == task_id)
        base_hp = state.metadata["campus_combat"]["enemy_archetypes"][case["topic_id"]]["max_health"]
        self.assertEqual(20, case["shell"])
        self.assertEqual((base_hp * 20 + 29) // 30, next(iter(battle["enemy_units"].values()))["max_health"])
        self.assertNotIn("anomaly_origin", bridge.snapshot()["combat"]["active_battle"])
        self.assertEqual([], afterimage_invariant(state))

    def test_no_victory_cannot_fake_site_completion(self):
        claim_afterimage(self.bridge, self.task_id)
        before = deepcopy((self.case, self.state.action_economy, self.state.inventories))
        state = self.state
        context = TransactionContext(state, DeterministicRngPool(42), SimulationCommand("fake", "player", "COMPLETE_FORUM_TASK", state.revision))
        self.assertFalse(complete_assigned_task(context, "player", {"task_id": self.task_id, "site_resolution": True, "battle_id": "made-up"}))
        self.assertFalse(command(self.bridge, "RESOLVE_NIGHT_SITE", {"task_id": self.task_id,
            "expected_task_revision": state.tasks[self.task_id]["lock_revision"]})["ok"])
        self.assertEqual(before, (self.case, self.state.action_economy, self.state.inventories))

    def test_npc_uses_common_owned_task_and_real_combat(self):
        from simulation.systems.campus_parties import party_for_actor
        eligible = [n for n in self.state.population if n not in {"player", self.target} and not party_for_actor(self.state, n)
            and not self.state.population[n].get("active_forum_task_id")
            and self.state.situations["night_world"]["actor_states"][n]["layer"] == "night"]
        npc = max(eligible, key=lambda n: sum(self.state.population[n]["attributes"].values()))
        result = as_npc(self.bridge, npc, "CLAIM_FORUM_TASK", {"task_id": self.task_id,
            "expected_task_revision": self.state.tasks[self.task_id]["lock_revision"]})
        self.assertTrue(result.success, result.code)
        travel_to_location(self.bridge, self.state.tasks[self.task_id]["scene_id"], npc)
        # Explicit available-action boundary; no fake combat outcome/stat boosts.
        self.state.action_economy["actors"][npc].update(major_remaining=1, night_combat_paid=False)
        person = deepcopy(self.state.population[self.target])
        result = as_npc(self.bridge, npc, "EXECUTE_NPC_NIGHT_TASK", {"task_id": self.task_id})
        self.assertTrue(result.success, result.code)
        battles = [b for b in self.state.battles.values() if b["situation_id"] == self.task_id]
        self.assertEqual(1, len(battles))
        self.assertNotIn("player", battles[0]["participant_ids"])
        if battles[0]["result"] == "victory":
            self.assertEqual(0, self.case["shell"])
            self.assertEqual(npc, self.case["history"][-1]["helper_id"])
        else:
            self.assertEqual(30, self.case["shell"])
        self.assertEqual(person, self.state.population[self.target])
        self.assertEqual([], afterimage_invariant(self.state))

    def test_unhandled_expiry_keeps_person_case_and_allows_new_night(self):
        before = deepcopy(self.case)
        self.state.clock.day += 1
        self.state.clock.phase = "morning"
        context = TransactionContext(self.state, DeterministicRngPool(42), SimulationCommand("expiry-boundary", "player", "ADVANCE_PHASE", self.state.revision))
        upkeep_night_sites(context)
        _expire_previous_night(context)
        self.assertEqual("expired", self.state.tasks[self.task_id]["state"])
        self.assertEqual(before, self.case)
        self.assertIn(self.case_id, [c["case_id"] for c in pending_afterimages(self.state)])

    def test_checkpoint_preserves_linkage_and_rejects_wrong_projection(self):
        claim_afterimage(self.bridge, self.task_id)
        self.assertTrue(command(self.bridge, "START_BATTLE_PREPARATION", {"task_id": self.task_id})["ok"])
        with TemporaryDirectory() as directory:
            path = Path(directory) / "afterimage.json"
            save_kernel_checkpoint(path, self.state, DeterministicRngPool(42))
            restored = load_kernel_checkpoint(path).state
            self.assertEqual([], afterimage_invariant(restored))
            battle = next(b for b in restored.battles.values() if b["situation_id"] == self.task_id)
            schema = json.loads((Path(__file__).resolve().parents[1] / "contracts/battle_state.schema.json").read_text())
            self.assertEqual(set(schema["properties"]["anomaly_origin"]["required"]), set(battle["anomaly_origin"]))
            battle["anomaly_origin"]["shell"] = 0
            self.assertTrue(afterimage_invariant(restored))
            battle.pop("anomaly_origin")
            self.assertTrue(afterimage_invariant(restored))

    def test_wrong_case_cannot_borrow_another_victory(self):
        claim_afterimage(self.bridge, self.task_id)
        win_afterimage(self.bridge, self.task_id)
        self.case["history"][-1]["battle_id"] = "unrelated"
        self.assertTrue(anomalies_invariant(self.state))
        self.assertTrue(afterimage_invariant(self.state))


if __name__ == "__main__":
    unittest.main()
