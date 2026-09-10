"""Offline seven-day natural clinic audit; no injected injury or patient plan.

The wrapper observes original handlers and asserts their real deltas. It never
changes the chosen action, its inputs, RNG, result, or world. Absence of natural
visits is reported as zero, not replaced with a fabricated demonstration.
"""
import json
from copy import deepcopy
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from simulation.actions.commands import SimulationCommand
from simulation.api.server import CampusKernelBridge
from simulation.persistence.kernel_checkpoint import save_kernel_checkpoint, load_kernel_checkpoint
from simulation.systems import campus_medical as medical
from simulation.systems import campus_free_errands


def observe(state, actor_id):
    actor = state.population.get(actor_id, {})
    shop = state.inventories.get("shops", {}).get(medical.SHOP, {})
    return deepcopy({"wealth": actor.get("wealth"), "vitals": actor.get("vitals"),
        "shop": shop, "budget": state.action_economy, "clock": vars(state.clock),
        "night": state.situations.get("night_world", {}).get("actor_states", {}).get(actor_id)})


def storage_arrays(value):
    """JSON represents Python tuples and lists as arrays; preserve every value/key."""
    if isinstance(value, dict):
        return {key: storage_arrays(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [storage_arrays(item) for item in value]
    return value


def first_difference(first, second, path="world"):
    if first == second:
        return None
    if type(first) is not type(second):
        return {"path": path, "before_type": type(first).__name__, "after_type": type(second).__name__}
    if isinstance(first, dict):
        if first.keys() != second.keys():
            return {"path": path, "difference": "keys"}
        for key in first:
            difference = first_difference(first[key], second[key], path + "." + str(key))
            if difference:
                return difference
    if isinstance(first, (list, tuple)):
        if len(first) != len(second):
            return {"path": path, "difference": "length"}
        for index, (a, b) in enumerate(zip(first, second)):
            difference = first_difference(a, b, path + f"[{index}]")
            if difference:
                return difference
    return {"path": path, "difference": "value"}


def run(seed):
    original_factory = medical.make_medical_handler
    successful, failures, checks = [], [], []

    def observed_factory():
        original = original_factory()

        def handle(context, request):
            before = observe(context.state, request.actor_id)
            result = original(context, request)
            after = observe(context.state, request.actor_id)
            if result.success:
                receipt = result.payload
                fee = receipt["fee"]
                assert after["wealth"] == before["wealth"] - fee
                assert after["shop"]["cash"] == before["shop"]["cash"] + fee
                for item, count in medical.SUPPLIES.items():
                    assert after["shop"]["quantities"][item] == before["shop"]["quantities"][item] - count
                assert after["vitals"]["health"] == before["vitals"]["health"] + receipt["health"]["delta"]
                assert after["vitals"]["focus"] == before["vitals"]["focus"]
                assert after["budget"] == before["budget"] and after["clock"] == before["clock"]
                assert after["night"] == before["night"]
                successful.append(deepcopy(receipt))
            else:
                assert after == before, result.code
                failures.append(result.code)
            return result
        return handle

    with patch.object(medical, "make_medical_handler", observed_factory), \
            patch.object(campus_free_errands, "make_medical_handler", observed_factory), \
            patch("urllib.request.urlopen", side_effect=AssertionError("offline audit forbids API")):
        bridge = CampusKernelBridge(seed)
        assert not bridge.cognition_runtime.provider.configured
        for step in range(28):
            state = bridge.kernel.state
            before_count = len(successful)
            result = bridge.kernel.execute(SimulationCommand(f"clinic-natural:{seed}:{step}", "player", "ADVANCE_PHASE", state.revision,
                issued_day=state.clock.day, issued_phase=state.clock.phase))
            assert result.success, result.code
            state = bridge.kernel.state
            assert not medical.medical_invariant(state)
            assert not bridge.cognition_runtime.provider.configured
            for receipt in successful[before_count:]:
                activity = state.population[receipt["patient_id"]].get("current_activity", {})
                checks.append({"status": activity.get("status"), "activity_id": activity.get("activity_id")})
            if step == 13:
                checkpoint, rng = bridge.kernel.capture_checkpoint()
                with TemporaryDirectory(prefix="clinic-natural-save-") as directory:
                    path = Path(directory) / "checkpoint.json"
                    save_kernel_checkpoint(path, checkpoint, rng, content_manifest=bridge.registry.manifest)
                    loaded = load_kernel_checkpoint(path, expected_content_version=checkpoint.content_version)
                    expected = checkpoint.to_dict()
                    expected["revision"] += 1
                    bridge.kernel.restore_checkpoint(loaded.state, loaded.rng, expected_revision=checkpoint.revision)
                    restored, restored_rng = bridge.kernel.capture_checkpoint()
                    actual = restored.to_dict()
                    if actual != expected:
                        print(json.dumps({"checkpoint_native_difference": first_difference(expected, actual),
                            "array_normalized_equal": storage_arrays(actual) == storage_arrays(expected),
                            "rng_equal": restored_rng.snapshot() == rng.snapshot()}, ensure_ascii=False), flush=True)
                    # No field is dropped and no value is ignored. Only the
                    # tuple-to-JSON-array representation is normalized.
                    assert storage_arrays(actual) == storage_arrays(expected), first_difference(storage_arrays(expected), storage_arrays(actual))
                    assert restored_rng.snapshot() == rng.snapshot()
            if (step + 1) % 4 == 0:
                print(json.dumps({"seed": seed, "days_advanced": (step + 1) // 4,
                    "natural_visits": len(successful), "failed_attempts": len(failures)}, ensure_ascii=False), flush=True)
        state = bridge.kernel.state
        assert len(medical.ledger(state).get("receipts", {})) == len(successful)
        assert all(receipt["patient_id"] != "player" for receipt in successful)
        result = {"result": "MEDICAL_SEVEN_DAY_AUDIT_OK", "seed": seed, "phases_advanced": 28,
            "natural_visits": len(successful), "distinct_patients": len({r["patient_id"] for r in successful}),
            "staff_shifts": len(medical.ledger(state).get("shifts", {})),
            "fees_transferred": sum(r["fee"] for r in successful),
            "materials_consumed": {item: count * len(successful) for item, count in medical.SUPPLIES.items()},
            "health_restored": sum(r["health"]["delta"] for r in successful),
            "failed_attempts": failures,
            "post_visit_primary_completed": sum(r["status"] == "completed" for r in checks),
            "post_visit_other_statuses": [r for r in checks if r["status"] != "completed"],
            "checkpoint_roundtrip": True, "injected_injury_or_plan": False, "paid_api_calls": 0}
        print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    for seed in sys.argv[1:] or [42]:
        run(int(seed))
