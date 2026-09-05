from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from simulation.api.legacy_bridge import SimulationBridge  # Explicit retired-runtime fixture only.


class UnifiedActionApiTests(unittest.TestCase):
    def make_bridge(self):
        output=tempfile.TemporaryDirectory(); self.addCleanup(output.cleanup)
        return SimulationBridge(Path(output.name))

    def test_drop_and_pick_up_round_trip_through_one_endpoint(self):
        bridge=self.make_bridge(); scene=bridge.world.player_scene
        before=bridge.revision
        dropped=bridge.action({
            "actor_id":"player","action_id":"DROP_ITEM",
            "item_id":"hemp_rope","quantity":1,
        })
        self.assertTrue(dropped["ok"])
        self.assertEqual(before+1,dropped["snapshot"]["revision"])
        self.assertEqual(1,bridge.world.inventories[f"scene:{scene}"].quantity("hemp_rope"))
        picked=bridge.action({
            "actor_id":"player","action_id":"PICK_UP_ITEM",
            "item_id":"hemp_rope","quantity":1,
        })
        self.assertTrue(picked["ok"])
        self.assertEqual(1,bridge.world.inventories["player"].quantity("hemp_rope"))

    def test_equip_and_unequip_use_unified_action_payload(self):
        bridge=self.make_bridge()
        bridge.world.item_instances.add_new(bridge.world,"player","walking_cane",1)
        equipped=bridge.action({
            "actor_id":"player","action_id":"EQUIP_ITEM","item_id":"walking_cane",
        })
        self.assertTrue(equipped["ok"])
        self.assertEqual("walking_cane",equipped["action"]["item_id"])
        removed=bridge.action({
            "actor_id":"player","action_id":"UNEQUIP_ITEM","item_id":"walking_cane",
        })
        self.assertTrue(removed["ok"])
        self.assertEqual({},bridge.world.player_equipment_slots)

    def test_checked_failure_is_performed_and_snapshot_is_saved(self):
        bridge=self.make_bridge(); world=bridge.world
        inspector=world.npcs["npc_003"]
        inspector.current_scene=world.player_scene
        world.item_instances.add_new(world,"player","rusted_knife",1)
        bridge.action({"actor_id":"player","action_id":"EQUIP_ITEM","item_id":"rusted_knife"})
        before=bridge.revision
        result=bridge.action({
            "actor_id":"player","action_id":"THREATEN_WITH_WEAPON",
            "target_id":inspector.id,"difficulty_override":200,
        })
        self.assertFalse(result["ok"])
        self.assertTrue(result["performed"])
        self.assertEqual(before+1,result["snapshot"]["revision"])
        self.assertEqual("critical_failure",result["action"]["check"]["outcome"])

    def test_precondition_failure_is_not_performed_but_block_event_is_visible(self):
        bridge=self.make_bridge(); before=bridge.revision
        result=bridge.action({
            "actor_id":"player","action_id":"PERFORM_SECRET_RITUAL",
        })
        self.assertFalse(result["ok"])
        self.assertFalse(result["performed"])
        self.assertEqual(before+1,result["snapshot"]["revision"])
        self.assertEqual("RITUAL_BLOCKED_MISSING_MATERIAL",
                         result["snapshot"]["new_events"][-1]["event_type"])

    def test_invalid_action_does_not_mutate_revision(self):
        bridge=self.make_bridge(); before=bridge.revision
        result=bridge.action({"actor_id":"player","action_id":"NOT_REAL"})
        self.assertFalse(result["ok"])
        self.assertFalse(result["performed"])
        self.assertEqual(before,bridge.revision)


if __name__=="__main__":
    unittest.main()
