"""Physical objectives, real common combat/traversal, blocked/expired/replayed work."""
from copy import deepcopy
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from simulation.api.server import CampusKernelBridge
from simulation.actions.commands import SimulationCommand
from simulation.systems.transactions import TransactionContext
from simulation.systems.campus_night_sites import (
    captive_site, create_night_site, night_sites_invariant, rescue_candidates,
    site_exposure, make_site_resolution_handler,
)
from simulation.systems.campus_locations import load_campus_location_graph
from simulation.systems.campus_combat import combat_round_policy_from_state
from simulation.systems.campus_autonomous_combat import choose_combat_action
from simulation.systems.campus_tasks import complete_assigned_task
from simulation.persistence.kernel_checkpoint import save_kernel_checkpoint, load_kernel_checkpoint
from tests.test_campus_combat_deployment import execute, travel_to_location


class NightSitesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = CampusKernelBridge(42)
        for i in range(2):
            result = execute(cls.bridge, "ADVANCE_PHASE", marker=f"site-init-{i}")
            assert result["ok"], result["result"]["code"]
        cls.baseline, cls.rng = cls.bridge.kernel.capture_checkpoint()

    def setUp(self):
        self.bridge.kernel.restore_checkpoint(self.baseline, self.rng, expected_revision=self.bridge.kernel.state.revision)
        self.counter = 0
        self.task_id = next(t["task_id"] for t in self.bridge.kernel.state.tasks.values()
                            if t.get("night_site_id") and t["state"] in {"open", "viewed", "considering"})

    def act(self, action, params=None, actor="player"):
        self.counter += 1
        state = self.bridge.kernel.state
        return self.bridge.execute({"command_id": f"site-test:{self.counter}:{state.revision}:{action}",
            "actor_id": actor, "source": "player" if actor == "player" else "rule", "action_id": action,
            "parameters": params or {}, "target_ids": [], "expected_world_revision": state.revision,
            "issued_day": state.clock.day, "issued_phase": state.clock.phase, "issued_minute": state.clock.minute})

    def prepare(self, rescue=False):
        if rescue:
            # Controlled incident boundary: move a real uncommitted student using
            # actual passage commands, then bind that actor. No fake NPC/receipt.
            from simulation.systems.campus_parties import party_for_actor
            state = self.bridge.kernel.state
            victim = next(key for key, actor in state.population.items() if key != "player"
                          and actor.get("role_kind") == "student" and not actor.get("active_forum_task_id")
                          and not party_for_actor(state, key) and not captive_site(state, key))
            travel_to_location(self.bridge, "south_gate", victim)
            state, rng = self.bridge.kernel.capture_checkpoint()
            # Controlled relocation invalidates readings of the old post; do
            # not forge knowledge of the fixture's new incident location.
            for regions in state.cognition.get("regional_awareness", {}).values():
                for region, notice in list(regions.items()):
                    if notice["source_task_id"] == self.task_id:
                        del regions[region]
            command = SimulationCommand("controlled-incident", "player", "ADVANCE_PHASE", state.revision,
                                        issued_day=state.clock.day, issued_phase=state.clock.phase)
            context = TransactionContext(state, rng, command)
            create_night_site(context, state.tasks[self.task_id], {"kind": "rescue", "label": "南门滞留点",
                "initial_state": "学生被困", "resolved_state": "已安全脱离", "operation": "护送到医院",
                "safe_location_id": "hospital_clinic"}, victim)
            self.bridge.kernel.restore_checkpoint(state, rng, expected_revision=self.bridge.kernel.state.revision)
        self.assertTrue(self.act("ENTER_NIGHT_WORLD")["ok"])
        task = self.bridge.kernel.state.tasks[self.task_id]
        self.assertTrue(self.act("CLAIM_FORUM_TASK", {"task_id": self.task_id, "expected_task_revision": task["lock_revision"]})["ok"])
        travel_to_location(self.bridge, task["scene_id"])

    def site(self):
        state = self.bridge.kernel.state
        return state.situations["night_sites"]["sites"][state.tasks[self.task_id]["night_site_id"]]

    def resolve(self, **extra):
        task = self.bridge.kernel.state.tasks[self.task_id]
        return self.act("RESOLVE_NIGHT_SITE", {"task_id": self.task_id, "expected_task_revision": task["lock_revision"], **extra})

    def battle(self):
        result = self.act("START_BATTLE_PREPARATION", {"task_id": self.task_id})
        self.assertTrue(result["ok"], result["result"]["code"])
        view = self.bridge.snapshot()["combat"]["active_battle"]
        own = next(card for card in view["character_cards"].values() if card["actor_id"] == "player")
        bid = view["battle_id"]
        def issue(action, params=None):
            current = self.bridge.kernel.state.battles[bid]
            result = self.act(action, {"battle_id": bid, "expected_battle_revision": current["revision"], **(params or {})})
            self.assertTrue(result["ok"], result["result"]["code"])
            return result
        issue("DEPLOY_COMBAT_CHARACTER", {"character_card_instance_id": own["character_card_instance_id"], "destination_row": own["preferred_row"]})
        issue("CONFIRM_BATTLE_DEPLOYMENT")
        issue("START_CARD_COMBAT")
        for _ in range(150):
            view = self.bridge.snapshot()["combat"]["active_battle"]
            if view is None or view["phase"] == "resolved":
                break
            action, params = choose_combat_action(self.bridge.kernel.state, view, "player", combat_round_policy_from_state(self.bridge.kernel.state))
            issue(action, params)
        self.assertEqual("victory", self.bridge.kernel.state.battles[bid]["result"])
        return bid

    def test_publication_has_actual_sites_and_no_unavailable_rescue_target(self):
        state = self.bridge.kernel.state
        self.assertEqual([], night_sites_invariant(state))
        for task in state.tasks.values():
            if task.get("forum") == "night" and task.get("resolution_kind") != "field_recon":
                self.assertIn(task["night_site_id"], state.situations["night_sites"]["sites"])
        self.assertNotIn("night_sites", self.bridge.snapshot())
        graph = load_campus_location_graph(self.bridge.registry)
        candidates = rescue_candidates(state, "sports_health_region", "hospital_clinic", graph)
        self.assertTrue(all(state.population[key]["current_location_id"] != "hospital_clinic" for key in candidates))

    def test_no_combat_no_site_success_no_reward(self):
        self.prepare()
        before = self.bridge.kernel.state
        self.assertEqual("site_threat_active", self.resolve()["result"]["code"])
        state, rng = self.bridge.kernel.capture_checkpoint()
        command = SimulationCommand("fake-site", "player", "RESOLVE_NIGHT_SITE", state.revision)
        self.assertFalse(complete_assigned_task(TransactionContext(state, rng, command), "player", {"task_id": self.task_id, "battle_id": "fake"}))
        self.assertEqual(before.population, self.bridge.kernel.state.population)
        self.assertEqual(before.tasks, self.bridge.kernel.state.tasks)

    def test_real_fight_changes_facility_and_reduces_local_exposure(self):
        self.prepare()
        before = self.bridge.kernel.state
        bid = self.battle()
        state = self.bridge.kernel.state
        self.assertEqual("resolved", self.site()["status"])
        corrupted = self.bridge.kernel.state
        sid = corrupted.tasks[self.task_id]["night_site_id"]
        corrupted.situations["night_sites"]["sites"][sid]["receipt"]["major_action_cost"] = True
        self.assertTrue(night_sites_invariant(corrupted))
        self.assertEqual("site_resolution", state.tasks[self.task_id]["completion_evidence"]["kind"])
        self.assertEqual(bid, self.site()["receipt"]["battle_id"])
        self.assertEqual(0, self.site()["receipt"]["major_action_cost"])
        self.assertLessEqual(site_exposure(state, "player"), site_exposure(before, "player"))
        self.assertEqual(before.population["player"]["wealth"] + before.tasks[self.task_id]["reward"]["wealth"], state.population["player"]["wealth"])
        self.assertEqual("task_not_owned", self.resolve()["result"]["code"])
        self.assertEqual(state.population, self.bridge.kernel.state.population)

    def test_real_rescue_uses_passages_and_releases_actual_victim(self):
        self.prepare(rescue=True)
        site = self.site()
        victim = site["victim_id"]
        before = self.bridge.kernel.state
        self.battle()
        state = self.bridge.kernel.state
        self.assertEqual("resolved", self.site()["status"])
        self.assertGreater(len(self.site()["receipt"]["passage_ids"]), 0)
        self.assertEqual("hospital_clinic", state.population[victim]["current_location_id"])
        self.assertEqual("hospital_clinic", state.population["player"]["current_location_id"])
        self.assertEqual("surface", state.situations["night_world"]["actor_states"][victim]["layer"])
        self.assertIsNone(captive_site(state, victim))
        self.assertEqual(before.population[victim]["vitals"], state.population[victim]["vitals"])
        self.assertEqual([], night_sites_invariant(state))
        corrupted = state.clone()
        corrupted.situations["night_sites"]["sites"][site["site_id"]]["receipt"]["passage_ids"] = []
        self.assertTrue(night_sites_invariant(corrupted))

    def test_captive_cannot_move_shop_join_or_take_other_job(self):
        self.prepare(rescue=True)
        victim = self.site()["victim_id"]
        for action, params in (("FAST_TRAVEL_CAMPUS", {"destination_id": "central_region"}), ("REST", {}),
                               ("BUY_ITEM", {}), ("EXIT_NIGHT_WORLD", {}), ("CLAIM_FORUM_TASK", {"task_id": self.task_id})):
            result = self.act(action, params, actor=victim)
            self.assertEqual("actor_stranded", result["result"]["code"])
        from simulation.systems.campus_parties import invitation_assessment, party_policy_from_state
        state = self.bridge.kernel.state
        self.assertEqual("actor_stranded", invitation_assessment(state, "player", victim, party_policy_from_state(state))["reason"])

    def block_escort_and_win(self):
        from simulation.domain.locations import CampusLocationGraph
        original = CampusLocationGraph.shortest_route
        def closed(graph, start, destination, **kwargs):
            if destination == "hospital_clinic" and start == "south_gate":
                return None
            return original(graph, start, destination, **kwargs)
        with patch.object(CampusLocationGraph, "shortest_route", closed):
            bid = self.battle()
        self.assertEqual("suppressed", self.site()["status"])
        self.assertEqual("locked", self.bridge.kernel.state.tasks[self.task_id]["state"])
        return bid

    def test_blocked_escort_preserves_victory_without_reward_and_can_retry_once(self):
        self.prepare(rescue=True)
        before = self.bridge.kernel.state
        bid = self.block_escort_and_win()
        state = self.bridge.kernel.state
        self.assertEqual(before.population["player"]["wealth"], state.population["player"]["wealth"])
        self.assertEqual("south_gate", state.population[self.site()["victim_id"]]["current_location_id"])
        self.assertEqual("site_threat_cleared", self.act("START_BATTLE_PREPARATION", {"task_id": self.task_id})["result"]["code"])
        self.assertTrue(self.resolve()["ok"])
        self.assertEqual(bid, self.site()["receipt"]["battle_id"])
        self.assertEqual(len(state.battles), len(self.bridge.kernel.state.battles))
        self.assertEqual("resolved", self.site()["status"])

    def test_replacement_must_pay_own_action_and_cannot_respawn_guard(self):
        self.prepare(rescue=True)
        self.block_escort_and_win()
        self.assertTrue(self.act("ABANDON_FORUM_TASK", {"task_id": self.task_id})["ok"])
        from simulation.systems.campus_parties import party_for_actor
        state = self.bridge.kernel.state
        npc = next(key for key, actor in state.population.items() if key != "player" and not captive_site(state, key)
                   and not party_for_actor(state, key) and actor.get("night_access") in {"capable", "willing"}
                   and state.situations["night_world"]["actor_states"][key]["layer"] == "night")
        if state.population[npc].get("active_forum_task_id"):
            self.assertTrue(self.act("ABANDON_FORUM_TASK", {"task_id": state.population[npc]["active_forum_task_id"]}, actor=npc)["ok"])
        task = self.bridge.kernel.state.tasks[self.task_id]
        self.assertTrue(self.act("CLAIM_FORUM_TASK", {"task_id": self.task_id, "expected_task_revision": task["lock_revision"]}, actor=npc)["ok"])
        travel_to_location(self.bridge, "south_gate", npc)
        task = self.bridge.kernel.state.tasks[self.task_id]
        params = {"task_id": self.task_id, "expected_task_revision": task["lock_revision"]}
        self.bridge.kernel._state.action_economy["actors"][npc]["major_remaining"] = 0
        self.assertEqual("major_action_exhausted", self.act("RESOLVE_NIGHT_SITE", params, actor=npc)["result"]["code"])
        self.bridge.kernel._state.action_economy["actors"][npc]["major_remaining"] = 1
        self.assertTrue(self.act("RESOLVE_NIGHT_SITE", params, actor=npc)["ok"])
        self.assertEqual(1, self.site()["receipt"]["major_action_cost"])
        self.assertEqual(0, self.bridge.kernel.state.action_economy["actors"][npc]["major_remaining"])

    def test_retry_command_replay_does_not_duplicate_reward_or_escort(self):
        self.prepare(rescue=True)
        self.block_escort_and_win()
        state = self.bridge.kernel.state
        command = SimulationCommand("once-resolve-site", "player", "RESOLVE_NIGHT_SITE", state.revision,
            issued_day=state.clock.day, issued_phase=state.clock.phase,
            parameters={"task_id": self.task_id, "expected_task_revision": state.tasks[self.task_id]["lock_revision"]})
        self.assertTrue(self.bridge.kernel.execute(command).success)
        after = self.bridge.kernel.state
        self.assertTrue(self.bridge.kernel.execute(command).replayed)
        self.assertEqual(after, self.bridge.kernel.state)

    def test_wrong_location_and_layer_cannot_resolve_remote_site(self):
        self.prepare()
        travel_to_location(self.bridge, "south_gate" if self.site()["location_id"] != "south_gate" else "central_region")
        self.assertEqual("task_location_required", self.resolve()["result"]["code"])
        self.assertTrue(self.act("EXIT_NIGHT_WORLD")["ok"])
        self.assertEqual("task_not_owned", self.resolve()["result"]["code"])

    def test_invalid_revision_and_client_fabrication_leave_world_unchanged(self):
        self.prepare()
        before = self.bridge.kernel.state
        for rev in (True, "1", -1, 900):
            self.assertEqual("task_revision_conflict", self.resolve(expected_task_revision=rev)["result"]["code"])
        self.assertEqual("invalid_site_resolution", self.resolve(victim_id="fake", rescued=True)["result"]["code"])
        self.assertEqual(before.situations, self.bridge.kernel.state.situations)

    def test_capture_checkpoint_preserves_target_and_dawn_releases_without_reward(self):
        self.prepare(rescue=True)
        victim = self.site()["victim_id"]
        state, rng = self.bridge.kernel.capture_checkpoint()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "site.json"
            save_kernel_checkpoint(path, state, rng, content_manifest=self.bridge.registry.manifest)
            loaded = load_kernel_checkpoint(path, expected_content_version=self.bridge.registry.content_version)
            self.assertEqual(state.situations, loaded.state.situations)
            self.assertEqual(rng.snapshot(), loaded.rng.snapshot())
        self.assertTrue(self.act("ADVANCE_PHASE")["ok"])
        self.assertTrue(self.act("ADVANCE_PHASE")["ok"])
        after = self.bridge.kernel.state
        self.assertEqual("expired", self.site()["status"])
        self.assertEqual("expired", after.tasks[self.task_id]["state"])
        self.assertIsNone(captive_site(after, victim))
        self.assertLess(after.population[victim]["vitals"]["health"], state.population[victim]["vitals"]["health"])
        self.assertEqual(state.population["player"]["wealth"], after.population["player"]["wealth"])

    def test_npc_completes_actual_objectives_without_player(self):
        result = self.act("ADVANCE_PHASE")
        self.assertTrue(result["ok"], result["result"]["code"])
        resolved = [s for s in self.bridge.kernel.state.situations["night_sites"]["sites"].values() if s["status"] == "resolved"]
        self.assertTrue(resolved)
        self.assertTrue(all(s["receipt"]["actor_id"] != "player" for s in resolved))
        self.assertTrue(any(e["event_type"] == "NIGHT_SITE_RESOLVED" for e in result["result"]["events"]))

    def test_invariant_rejects_fabricated_completion_or_moved_captive(self):
        self.prepare(rescue=True)
        state = self.bridge.kernel.state
        victim = self.site()["victim_id"]
        state.population[victim]["current_location_id"] = "central_region"
        self.assertTrue(night_sites_invariant(state))
        state = self.bridge.kernel.state
        state.tasks[self.task_id]["state"] = "completed"
        self.assertTrue(night_sites_invariant(state))

    def test_frozen_previous_content_migrates_without_inventing_sites(self):
        from simulation.persistence.content_migrations import migrate_campus_content
        from simulation.persistence.kernel_checkpoint import LoadedCheckpoint, CheckpointError
        spec = json.loads((Path(__file__).resolve().parents[1] / "simulation/persistence/campus_night_sites_content.json").read_text())
        state, rng = self.bridge.kernel.capture_checkpoint()
        state.content_version = spec["source_version"]
        state.situations.pop("campus_life", None)  # Frozen old content predates public activities.
        loaded = LoadedCheckpoint(state, rng, spec["source_manifest"])
        result = migrate_campus_content(loaded, self.bridge.registry.content_version)
        comparison = result.state.clone()
        comparison.content_version = state.content_version
        life = comparison.situations.pop("campus_life")
        self.assertEqual({}, life["records"])
        self.assertEqual(self.bridge.registry.all("life_opportunity"), life["definitions"])
        self.assertEqual(state, comparison)
        self.assertEqual(rng.snapshot(), result.rng.snapshot())
        self.assertEqual(self.bridge.registry.manifest, result.content_manifest)
        self.assertIn(spec["migration_id"], result.migrations)
        self.assertIn("campus-additional-friend-cognition-v2", result.migrations)
        with self.assertRaises(CheckpointError):
            migrate_campus_content(LoadedCheckpoint(state, rng, {}), self.bridge.registry.content_version)
