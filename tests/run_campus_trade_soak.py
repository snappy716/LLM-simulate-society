"""Offline multi-day audit: actual receipts, movements and conserved trade assets."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import tempfile

from simulation.actions.commands import SimulationCommand
from simulation.api.server import CampusKernelBridge
from simulation.persistence.kernel_checkpoint import save_kernel_checkpoint, load_kernel_checkpoint
from simulation.systems.campus_inventory import campus_inventory_invariant
from simulation.systems.campus_trade import professional
from simulation.systems.randomness import DeterministicRngPool


def run(days=14, seed=42, pause_days=()):
    bridge = CampusKernelBridge(seed)
    counts, gaps, settled_at = Counter(), [], defaultdict(list)
    started = bridge.kernel.state
    previous_quantities = Counter()
    for group in ("actors", "shops", "ground"):
        for record in started.inventories[group].values():
            previous_quantities.update(record["quantities"])
    for index in range(days * 4):
        upcoming_day = bridge.kernel._state.clock.day + (bridge.kernel._state.clock.phase == "late_night")
        # Test-only outage injection, not a production player/LLM command.
        bridge.kernel._state.inventories["supply"]["available"] = upcoming_day not in pause_days
        state = bridge.kernel.state
        result = bridge.kernel.execute(SimulationCommand(f"soak:{index}", "player", "ADVANCE_PHASE", state.revision,
            issued_day=state.clock.day, issued_phase=state.clock.phase))
        assert result.success, result
        consumed = Counter()
        imported = Counter()
        shop_sales, supply_paid = 0, 0
        for event in result.events:
            if event.event_type == "CAMPUS_ITEM_ACTION_COMPLETED":
                counts[event.payload["action_id"]] += 1
                if event.payload["action_id"] == "USE_ITEM":
                    consumed[event.payload["item_id"]] += event.payload["quantity"]
                if event.payload["action_id"] == "BUY_ITEM":
                    shop_sales += event.payload["total_price"]
                    # Receipt location must be the shop, not an intended target.
                    assert event.scene_id == state.inventories["shops"][event.payload["shop_id"]]["location_id"]
                elif event.payload["action_id"] == "SELL_ITEM":
                    shop_sales -= event.payload["total_price"]
            elif event.event_type == "CAMPUS_SUPPLY_ORDERED":
                counts["supply_orders"] += 1
                supply_paid += event.payload["total_price"]
            elif event.event_type == "CAMPUS_SUPPLY_DELIVERED":
                counts["supply_deliveries"] += 1
                imported[event.payload["item_id"]] += event.payload["quantity"]
                assert event.day >= event.payload["ordered_day"] + 1
                assert event.day not in pause_days
            elif event.event_type == "CAMPUS_SUPPLY_DELAYED":
                counts["supply_delays"] += 1
            elif event.event_type == "CAMPUS_TRADE_SETTLED":
                counts["private_settled"] += 1
                offer = event.payload
                assert "player" not in (offer["buyer_id"], offer["seller_id"])
                for actor_id in (offer["buyer_id"], offer["seller_id"]):
                    settled_at[actor_id].append(offer["closed_tick"])
            elif event.event_type == "NPC_DECISION_MADE" and event.payload.get("activity_id") == "BUY_ITEM":
                counts["procurement_plans"] += 1
        after = bridge.kernel.state
        assert not list(campus_inventory_invariant(after))
        current = Counter()
        for group in ("actors", "shops", "ground"):
            for record in after.inventories[group].values():
                current.update(record["quantities"])
        assert previous_quantities + imported - consumed == current, (index, previous_quantities + imported - consumed - current)
        assert sum(s["cash"] for s in after.inventories["shops"].values()) == sum(s["cash"] for s in state.inventories["shops"].values()) + shop_sales - supply_paid
        assert after.inventories["supply"]["supplier_receipts"] - state.inventories["supply"]["supplier_receipts"] == supply_paid
        previous_quantities = current
        if index == days * 2:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "soak.json"
                save_kernel_checkpoint(path, after, DeterministicRngPool.from_snapshot(bridge.kernel.rng_snapshot))
                loaded = load_kernel_checkpoint(path)
                assert loaded.state.to_dict() == json.loads(json.dumps(after.to_dict()))
                bridge.kernel._state = loaded.state
                # This phase path did not draw trade RNG; restore the whole pool
                # as well, so cognition/schedules continue on the saved streams.
                bridge.kernel._rng = loaded.rng
        if (index + 1) % 4 == 0:
            print(json.dumps({"day": (index + 1) // 4, "counts": dict(counts)}, ensure_ascii=False), flush=True)
    state = bridge.kernel.state
    for actor_id, times in settled_at.items():
        if not professional(state, actor_id):
            for a, b in zip(times, times[1:]):
                assert b - a >= 8, (actor_id, times)
                gaps.append((b - a) / 4)
    assert counts["BUY_ITEM"] > 0 and counts["private_settled"] > 0, counts
    summary = {"days": days, "seed": seed, "counts": dict(counts), "participants": len(settled_at),
               "supply_pause_days": list(pause_days),
               "ordinary_repeat_intervals_days": gaps, "stock_conserved_with_recorded_imports_and_consumption": True,
               "shop_cash_and_external_payments_reconciled": True,
               "supplier_receipts": state.inventories["supply"]["supplier_receipts"],
               "midpoint_checkpoint_restored": True, "paid_llm_calls": 0}
    print("CAMPUS_TRADE_SOAK_OK " + json.dumps(summary, ensure_ascii=False), flush=True)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--pause-days", type=int, nargs="*", default=[])
    args = parser.parse_args()
    run(args.days, args.seed, args.pause_days)
