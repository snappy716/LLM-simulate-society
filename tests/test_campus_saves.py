import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from simulation.actions.commands import SimulationCommand
from simulation.api.server import CampusKernelBridge, Handler
from simulation.persistence.campus_saves import CampusSaveStore, SaveError
from simulation.persistence.kernel_checkpoint import save_kernel_checkpoint, load_kernel_checkpoint, CheckpointError
from simulation.systems.randomness import DeterministicRngPool
from simulation.systems.transactions import RevisionConflictError


class CampusSaveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = CampusKernelBridge(42)
        cls.baseline, cls.initial_rng = cls.bridge.kernel.capture_checkpoint()

    def setUp(self):
        self.bridge.kernel._state = self.baseline.clone()
        self.bridge.kernel._rng = self.initial_rng.clone()
        self.bridge.cognition_runtime.configure_rule()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = CampusSaveStore(Path(self.directory.name) / "saves")

    def request(self, operation, slot="slot_1", backup=False, **overrides):
        listing = self.bridge.persistence(self.store, {"operation": "list"})["slots"]
        entry = next(s for s in listing if s["slot_id"] == slot)
        return self.bridge.persistence(self.store, {"operation": operation, "slot_id": slot,
            "expected_token": entry["backup" if backup else "current"]["token"],
            "expected_world_revision": self.bridge.kernel._state.revision, "backup": backup, "confirmed": True, **overrides})

    def buy(self, command_id="buy-after-save"):
        state = self.bridge.kernel._state
        return self.bridge.kernel.execute(SimulationCommand(command_id, "player", "BUY_ITEM", state.revision,
            parameters={"item_id": "bread_loaf", "shop_id": "campus_market"},
            issued_day=state.clock.day, issued_phase=state.clock.phase))

    def test_three_empty_slots_and_no_world_mutation(self):
        before = self.bridge.kernel.state.to_dict()
        slots = self.bridge.persistence(self.store, {"operation": "list"})["slots"]
        self.assertEqual(3, len(slots))
        self.assertTrue(all(not s["current"]["exists"] for s in slots))
        self.assertEqual(before, self.bridge.kernel.state.to_dict())

    def test_save_load_restores_wallet_inventory_and_free_action_budget(self):
        self.bridge.kernel._state.population["player"]["current_location_id"] = "supermarket_sales_floor"
        before = self.bridge.kernel.state.to_dict()
        self.request("save")
        self.assertEqual(before, self.bridge.kernel.state.to_dict())
        self.assertTrue(self.buy().success)
        advanced_revision = self.bridge.kernel._state.revision
        result = self.request("load")
        after = self.bridge.kernel.state.to_dict()
        self.assertGreater(after["revision"], advanced_revision)
        after["revision"] = before["revision"]
        self.assertEqual(json.loads(json.dumps(before)), json.loads(json.dumps(after)))
        self.assertEqual(500, result["snapshot"]["player"]["wealth"])

    def test_backup_retains_previous_slot_and_can_restore_it(self):
        self.request("save")
        self.bridge.kernel._state.population["player"]["wealth"] = 123
        self.request("save")
        self.assertEqual(500, load_kernel_checkpoint(self.store.path("slot_1", True)).state.population["player"]["wealth"])
        self.request("load", backup=True)
        self.assertEqual(500, self.bridge.kernel._state.population["player"]["wealth"])

    def test_confirmation_and_slot_token_are_required(self):
        self.request("save")
        for operation, overrides in [("save", {"confirmed": False}), ("load", {"confirmed": False}),
                                     ("save", {"expected_token": "stale"}), ("load", {"expected_token": "stale"})]:
            with self.subTest(operation=operation, overrides=overrides):
                before = self.bridge.kernel.state.to_dict()
                with self.assertRaises(SaveError):
                    self.request(operation, **overrides)
                self.assertEqual(before, self.bridge.kernel.state.to_dict())

    def test_stale_world_revision_rejected_without_io_mutation(self):
        self.request("save")
        token = self.store.token(self.store.path("slot_1"))
        with self.assertRaises(SaveError):
            self.request("load", expected_world_revision=0)
        self.assertEqual(token, self.store.token(self.store.path("slot_1")))

    def test_corrupt_current_preserves_world_and_good_backup(self):
        self.request("save")
        self.request("save")
        backup = self.store.token(self.store.path("slot_1", True))
        self.store.path("slot_1").write_text("broken", encoding="utf-8")
        before = self.bridge.kernel.state.to_dict()
        with self.assertRaises(CheckpointError):
            self.request("load")
        self.assertEqual(before, self.bridge.kernel.state.to_dict())
        self.assertEqual(backup, self.store.token(self.store.path("slot_1", True)))
        self.assertTrue(self.request("load", backup=True)["ok"])
        self.assertTrue(self.request("save")["preserved_invalid"])
        self.assertEqual(backup, self.store.token(self.store.path("slot_1", True)))
        archived = list(self.store.directory.glob("slot_1.invalid-*.json"))
        self.assertEqual(1, len(archived))
        self.assertEqual("broken", archived[0].read_text(encoding="utf-8"))

    def test_cross_instance_store_lock_and_slot_conflict(self):
        other = CampusSaveStore(self.store.directory)
        with self.store.locked():
            with self.assertRaises(OSError):
                with other.locked():
                    self.fail("second writer acquired existing lock")
        self.request("save")
        state, rng = self.bridge.kernel.capture_checkpoint()
        with other.locked(), self.assertRaises(SaveError):
            other.save("slot_1", state, rng, {}, expected_token="", confirmed=True)

    def test_pending_supply_and_phase_continuation_remain_exact_after_load(self):
        from simulation.systems.campus_supply import review_campus_supply
        from simulation.systems.transactions import TransactionContext
        state = self.bridge.kernel._state
        state.inventories["shops"]["campus_market"]["quantities"].pop("bread_loaf", None)
        context = TransactionContext(state, self.bridge.kernel._rng, SimulationCommand("order-fixture", "player", "ADVANCE_PHASE", state.revision))
        self.assertGreater(review_campus_supply(context)["supply_orders"], 0)
        saved_supply = json.loads(json.dumps(state.inventories["supply"]))
        self.request("save")
        self.bridge.kernel._state.inventories["supply"]["available"] = False
        self.request("load")
        self.assertEqual(saved_supply, self.bridge.kernel._state.inventories["supply"])
        current = self.bridge.kernel._state
        command = SimulationCommand("post-load-phase", "player", "ADVANCE_PHASE", current.revision,
            issued_day=current.clock.day, issued_phase=current.clock.phase)
        self.assertTrue(self.bridge.kernel.execute(command).success)

    def test_failed_disk_write_preserves_prior_file(self):
        self.request("save")
        token = self.store.token(self.store.path("slot_1"))
        with patch("simulation.persistence.campus_saves.atomic_write_json", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.request("save")
        self.assertEqual(token, self.store.token(self.store.path("slot_1")))

    def test_no_path_traversal_unknown_fields_or_symlinks(self):
        for payload in ({"operation": "list", "path": "/tmp/other"}, [], {"operation": "delete"}):
            with self.assertRaises(SaveError):
                self.bridge.persistence(self.store, payload)
        for slot in ("../other", "/tmp/other", None, []):
            with self.assertRaises(SaveError):
                self.store.path(slot)
        with self.store.locked():
            self.store.path("slot_1").symlink_to(Path(self.directory.name) / "elsewhere")
        with self.assertRaises(SaveError):
            self.bridge.persistence(self.store, {"operation": "list"})

    def test_content_mismatch_not_silently_reinitialized(self):
        state, rng = self.bridge.kernel.capture_checkpoint()
        state.content_version = "unknown-content"
        save_kernel_checkpoint(self.store.path("slot_1"), state, rng)
        before = self.bridge.kernel.state.to_dict()
        with self.assertRaises(CheckpointError):
            self.request("load")
        self.assertEqual(before, self.bridge.kernel.state.to_dict())

    def test_known_missing_policy_migrates_without_changing_assets_or_original_file(self):
        state, rng = self.bridge.kernel.capture_checkpoint()
        for key in ("food_reorder_nutrition", "food_buffer_nutrition"):
            del state.inventories["trade"]["policy"][key]
        save_kernel_checkpoint(self.store.path("slot_1"), state, rng)
        token = self.store.token(self.store.path("slot_1"))
        result = self.request("load")
        self.assertEqual(2, len(result["migrations"]))
        self.assertEqual(state.inventories["actors"], self.bridge.kernel._state.inventories["actors"])
        self.assertEqual(token, self.store.token(self.store.path("slot_1")))

    def test_missing_old_campus_resources_rejected_not_regenerated(self):
        state, rng = self.bridge.kernel.capture_checkpoint()
        del state.inventories["supply"]
        save_kernel_checkpoint(self.store.path("slot_1"), state, rng)
        with self.assertRaises(CheckpointError):
            self.request("load")

    def test_full_runtime_invariants_checked_before_restore(self):
        state, rng = self.bridge.kernel.capture_checkpoint()
        state.action_economy["actors"]["player"]["major_remaining"] = -1
        # Low-level checkpoint has narrower validation than the running bridge.
        save_kernel_checkpoint(self.store.path("slot_1"), state, rng)
        before = self.bridge.kernel.state.to_dict()
        with self.assertRaises(ValueError):
            self.request("load")
        self.assertEqual(before, self.bridge.kernel.state.to_dict())

    def test_rng_restart_and_api_secret_not_in_save(self):
        self.bridge.cognition_runtime.configure_openai_compatible("https://example.invalid/v1", "test", "test-secret-not-a-real-key")
        self.bridge.kernel._rng.stream("save-test").random()
        self.request("save")
        text = self.store.path("slot_1").read_text(encoding="utf-8")
        self.assertNotIn("test-secret-not-a-real-key", text)
        expected = self.bridge.kernel._rng.stream("save-test").random()
        self.bridge.kernel._rng.stream("save-test").random()
        self.request("load")
        self.assertEqual(expected, self.bridge.kernel._rng.stream("save-test").random())
        # Simulate a fresh application process: state/RNG survive; credentials do not.
        fresh = CampusKernelBridge(7)
        slots = fresh.persistence(self.store, {"operation": "list"})["slots"]
        fresh.persistence(self.store, {"operation": "load", "slot_id": "slot_1", "confirmed": True,
            "expected_world_revision": 1, "expected_token": slots[0]["current"]["token"]})
        self.assertFalse(fresh.cognition_runtime.public_status()["configured"])

    def test_stale_future_command_cannot_apply_after_load(self):
        self.bridge.kernel._state.population["player"]["current_location_id"] = "supermarket_sales_floor"
        self.request("save")
        future = SimulationCommand("abandoned-future", "player", "ADVANCE_PHASE", 1)
        self.request("load")
        with self.assertRaises(RevisionConflictError):
            self.bridge.kernel.execute(future)

    def test_saved_map_is_allowlisted_and_does_not_mutate_live_world(self):
        before = self.bridge.kernel.state.to_dict()
        self.request("save", presentation_map_id="library")
        self.assertEqual(before, self.bridge.kernel.state.to_dict())
        self.assertEqual("library", self.request("load")["presentation_map_id"])
        with self.assertRaises(SaveError):
            self.request("save", presentation_map_id="res://arbitrary.tscn")

    def test_rng_clone_failure_cannot_partially_replace_world(self):
        state, rng = self.bridge.kernel.capture_checkpoint()
        state.population["player"]["wealth"] = 1
        before = self.bridge.kernel.state.to_dict()
        with patch.object(rng, "clone", side_effect=ValueError("bad RNG")), self.assertRaises(ValueError):
            self.bridge.kernel.restore_checkpoint(state, rng, expected_revision=before["revision"])
        self.assertEqual(before, self.bridge.kernel.state.to_dict())

    def test_battle_task_locks_cards_and_next_draw_survive_load(self):
        from tests.test_campus_combat_rounds import deploy_and_start
        from tests.test_campus_combat_deployment import execute
        battle = deploy_and_start(self.bridge)
        before = self.bridge.kernel.state.to_dict()
        self.request("save")
        parameters = {"battle_id": battle["battle_id"], "expected_battle_revision": battle["revision"]}
        first = execute(self.bridge, "END_COMBAT_ROUND", parameters, marker="save-next-round")
        self.assertTrue(first["ok"], first)
        self.request("load")
        after = self.bridge.kernel.state.to_dict()
        after["revision"] = before["revision"]
        self.assertEqual(json.loads(json.dumps(before)), json.loads(json.dumps(after)))
        second = execute(self.bridge, "END_COMBAT_ROUND", parameters, marker="save-next-round")
        self.assertTrue(second["ok"], second)
        self.assertEqual(first["snapshot"]["combat"]["active_battle"], second["snapshot"]["combat"]["active_battle"])

    def test_saved_processed_purchase_cannot_charge_twice(self):
        self.bridge.kernel._state.population["player"]["current_location_id"] = "supermarket_sales_floor"
        state = self.bridge.kernel._state
        command = SimulationCommand("saved-purchase", "player", "BUY_ITEM", state.revision,
            parameters={"item_id": "bread_loaf", "shop_id": "campus_market"},
            issued_day=state.clock.day, issued_phase=state.clock.phase)
        self.assertTrue(self.bridge.kernel.execute(command).success)
        self.request("save")
        self.request("load")
        before = self.bridge.kernel.state.to_dict()
        self.assertTrue(self.bridge.kernel.execute(command).success)
        self.assertEqual(before, self.bridge.kernel.state.to_dict())

    def test_http_route_lists_saves_and_returns_rejection_not_server_error(self):
        class TestHandler(Handler):
            bridge = SimpleNamespace(campus=self.bridge, campus_saves=self.store)
        server = ThreadingHTTPServer(("127.0.0.1", 0), TestHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            def post(payload):
                return urlopen(Request(f"http://127.0.0.1:{server.server_port}/kernel/saves",
                    data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}), timeout=10)
            with post({"operation": "list"}) as response:
                self.assertEqual(3, len(json.load(response)["slots"]))
            payload = {"operation": "save", "slot_id": "slot_1", "confirmed": True,
                       "expected_world_revision": self.bridge.kernel._state.revision, "expected_token": ""}
            with post(payload) as response:
                saved = json.load(response)
                self.assertTrue(saved["ok"])
            payload.update(operation="load", expected_token=saved["slots"][0]["current"]["token"])
            with post(payload) as response:
                self.assertTrue(json.load(response)["ok"])
            with self.assertRaises(HTTPError) as caught:
                post({"operation": "load", "slot_id": "../bad"})
            self.assertEqual(400, caught.exception.code)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()
