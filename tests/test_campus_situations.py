from collections import Counter
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from simulation.api.server import CampusKernelBridge
from simulation.actions.commands import SimulationCommand
from simulation.systems.transactions import TransactionContext
from simulation.systems import DeterministicRngPool
from simulation.systems.campus_situations import advance_campus_situations, campus_situations_invariant, regional_pressure, situation_forum_view, weighted_night_templates
from simulation.systems.campus_supply import review_campus_supply, receive_campus_supply
from simulation.systems.campus_night_sites import site_exposure
from simulation.persistence.kernel_checkpoint import save_kernel_checkpoint, load_kernel_checkpoint
from tests.test_campus_cognition import command


def context_for(state):
    return TransactionContext(state, DeterministicRngPool(42), SimulationCommand("situation-fixture", "player", "ADVANCE_PHASE", state.revision))


class SituationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        bridge = CampusKernelBridge(42)
        for _ in range(4):
            assert command(bridge, "ADVANCE_PHASE")["ok"]
        cls.baseline, cls.rng = bridge.kernel.capture_checkpoint()

    def setUp(self):
        self.state = self.baseline.clone()
        self.context = context_for(self.state)

    def test_actual_expired_sites_create_persistent_pressure_once(self):
        ledger = self.state.situations["campus_dynamics"]
        self.assertTrue(any(r["pressure"] > 0 for r in ledger["regions"].values()))
        for site_id, status in ledger["processed_sites"].items():
            self.assertEqual(status, self.state.situations["night_sites"]["sites"][site_id]["status"])
        before = deepcopy(ledger)
        advance_campus_situations(self.context)
        advance_campus_situations(self.context)
        self.assertEqual(before, ledger)
        self.assertEqual([], list(campus_situations_invariant(self.state)))

    def test_exposure_template_weights_and_night_privacy(self):
        ledger = self.state.situations["campus_dynamics"]
        region = next(r for r, v in ledger["regions"].items() if v["pressure"])
        # Explicit high-pressure boundary; no task, item or victory is fabricated.
        ledger["regions"][region]["pressure"] = 8
        self.state.population["player"]["current_location_id"] = region
        self.assertGreaterEqual(site_exposure(self.state, "player"), 2)
        other = next(r for r in self.state.places if r not in ledger["regions"] and self.state.places[r].get("node_type") == "region")
        weights = Counter(weighted_night_templates(self.state, {"high": {"scene_id": region}, "calm": {"scene_id": other}}))
        self.assertEqual({"high": 3, "calm": 1}, weights)
        self.assertEqual([], situation_forum_view(self.state, False)["night"])
        self.assertTrue(situation_forum_view(self.state, True)["night"])
        self.assertNotIn("source_site_ids", str(situation_forum_view(self.state, False)))

    def test_same_region_night_expiries_share_cap_but_retain_all_receipts(self):
        from collections import defaultdict
        sites = self.state.situations["night_sites"]["sites"]
        groups = defaultdict(list)
        for site_id, site in sites.items():
            if site["status"] == "expired":
                groups[(site["region_id"], site["expires_day"])].append(site_id)
        self.assertTrue(any(len(ids) > 1 for ids in groups.values()))
        # Re-evaluate the actual previous night's expired sites from empty pressure.
        ledger = self.state.situations["campus_dynamics"]
        ledger["regions"] = {}
        ledger["processed_sites"] = {k: s["status"] for k, s in sites.items() if s["status"] == "resolved"}
        advance_campus_situations(self.context)
        for (region, _), ids in groups.items():
            self.assertEqual(2, ledger["regions"][region]["pressure"])
            self.assertTrue(all(ledger["processed_sites"][k] == "expired" for k in ids))
        before = deepcopy(ledger)
        advance_campus_situations(self.context)
        self.assertEqual(before, ledger)

    def test_prior_expiry_receipt_prevents_recharge_after_checkpoint(self):
        sites = self.state.situations["night_sites"]["sites"]
        ledger = self.state.situations["campus_dynamics"]
        for site_id, site in sites.items():
            if site["status"] == "expired" and any(k != site_id and s["status"] == "expired"
                    and s["region_id"] == site["region_id"] and s["expires_day"] == site["expires_day"] for k, s in sites.items()):
                ledger["processed_sites"].pop(site_id)
                before = ledger["regions"][site["region_id"]]["pressure"]
                advance_campus_situations(self.context)
                self.assertEqual(before, ledger["regions"][site["region_id"]]["pressure"])
                break
        else:
            self.fail("expected naturally multiple expired sites in one region")

    def test_pressure_settles_once_per_day_and_checkpoint_roundtrip(self):
        ledger = self.state.situations["campus_dynamics"]
        before = {r: d["pressure"] for r, d in ledger["regions"].items()}
        self.state.clock.day += 1
        advance_campus_situations(self.context)
        advance_campus_situations(self.context)
        self.assertEqual({r: max(0, p - 1) for r, p in before.items()}, {r: d["pressure"] for r, d in ledger["regions"].items()})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "situations.json"
            save_kernel_checkpoint(path, self.state, self.rng)
            restored = load_kernel_checkpoint(path).state
            self.assertEqual(ledger, restored.situations["campus_dynamics"])
        region = next(iter(ledger["regions"]))
        ledger["regions"][region]["pressure"] = 999
        self.assertIn("invalid campus regional pressure", list(campus_situations_invariant(self.state)))

    def test_shortage_duration_prioritizes_real_paid_supply_then_recovers(self):
        state = CampusKernelBridge(42).kernel.state
        context = context_for(state)
        shop_id = next(iter(state.inventories["shops"]))
        shop = state.inventories["shops"][shop_id]
        item = next(iter(shop["quantities"]))
        shop["quantities"].pop(item)
        advance_campus_situations(context)
        key = shop_id + ":" + item
        self.assertEqual("watch", state.situations["campus_dynamics"]["shortages"][key]["status"])
        state.clock.day += 1
        advance_campus_situations(context)
        self.assertEqual("shortage", state.situations["campus_dynamics"]["shortages"][key]["status"])
        cash = shop["cash"]
        review_campus_supply(context)
        self.assertLess(shop["cash"], cash)
        orders = state.inventories["supply"]["orders"]
        self.assertTrue(any(o["item_id"] == item and o["shop_id"] == shop_id for o in orders.values()))
        state.clock.day += 1
        receive_campus_supply(context)
        advance_campus_situations(context)
        self.assertGreater(shop["quantities"][item], 0)
        self.assertEqual("resolved", state.situations["campus_dynamics"]["shortages"][key]["status"])

    def test_player_real_site_resolution_reduces_pressure(self):
        from tests import test_campus_night_sites as physical
        physical.NightSitesTests.setUpClass()
        run = physical.NightSitesTests()
        run.setUp()
        run.prepare()
        region = run.site()["region_id"]
        state = run.bridge.kernel._state
        state.situations["campus_dynamics"]["regions"][region] = {"pressure": 6, "source_site_ids": []}
        run.battle()
        if run.site()["status"] != "resolved":
            self.assertTrue(run.resolve()["ok"])
        self.assertEqual("resolved", run.site()["status"])
        self.assertEqual(3, regional_pressure(run.bridge.kernel.state, region))
        self.assertIn(run.site()["site_id"], run.bridge.kernel.state.situations["campus_dynamics"]["processed_sites"])

    def test_older_shortage_gets_limited_cash_before_fresh_shortage(self):
        state = CampusKernelBridge(42).kernel.state
        context = context_for(state)
        shop_id = next(k for k, s in state.inventories["shops"].items() if len(s["quantities"]) >= 2)
        shop = state.inventories["shops"][shop_id]
        fresh, old = sorted(shop["quantities"])[0], sorted(shop["quantities"])[-1]
        shop["quantities"].pop(old)
        advance_campus_situations(context)
        state.clock.day += 1
        shop["quantities"].pop(fresh)
        policy = state.inventories["supply"]["policy"]
        price = max(1, (state.inventories["catalog"][old]["base_price"] * policy["wholesale_percent"] + 99) // 100)
        shop["cash"] = policy["cash_reserve"] + price
        review_campus_supply(context)
        orders = [o for o in state.inventories["supply"]["orders"].values() if o["shop_id"] == shop_id]
        self.assertEqual([old], [o["item_id"] for o in orders])
        self.assertEqual(policy["cash_reserve"], shop["cash"])


if __name__ == "__main__":
    unittest.main()
