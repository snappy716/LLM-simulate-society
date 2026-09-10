"""Final step-12 unattended audit; no score, schedule or relationship injection.

Uses the shipped campus and authoritative phase commands. A real mid-run disk
checkpoint is loaded and resumed, comparing every world field and RNG stream.
Counts are observations, not a mandated attendance or romantic-success quota.
"""
import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from simulation.actions.commands import SimulationCommand
from simulation.api.server import CampusKernelBridge
from simulation.persistence.kernel_checkpoint import load_kernel_checkpoint, save_kernel_checkpoint
from simulation.systems.campus_life import ledger, life_invariant
from simulation.systems.campus_bonds import bonds_invariant
from simulation.systems.campus_medical import medical_invariant


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def audit(seed, days):
    with patch("urllib.request.urlopen", side_effect=AssertionError("Paid API forbidden in offline closure audit")):
        bridge = CampusKernelBridge(seed)
        assert not bridge.cognition_runtime.provider.configured
        event_counts = Counter()
        restored = False
        for step in range(days * 4):
            state = bridge.kernel._state
            result = bridge.kernel.execute(SimulationCommand(
                f"closure:{seed}:{step}", "player", "ADVANCE_PHASE", state.revision,
                issued_day=state.clock.day, issued_phase=state.clock.phase))
            assert result.success, result.code
            event_counts.update(e.event_type for e in result.events)
            state = bridge.kernel._state
            assert not list(life_invariant(state))
            assert not list(bonds_invariant(state))
            assert not list(medical_invariant(state))
            assert state.cognition["usage"]["calls"] == 0
            if step + 1 == 7 * 4:
                captured, rng = bridge.kernel.capture_checkpoint()
                with TemporaryDirectory(prefix="campus-life-closure-") as directory:
                    path = Path(directory) / "checkpoint.json"
                    save_kernel_checkpoint(path, captured, rng, content_manifest=bridge.registry.manifest)
                    loaded = load_kernel_checkpoint(path, expected_content_version=captured.content_version)
                    assert canonical(asdict(captured)) == canonical(asdict(loaded.state))
                    assert canonical(rng.snapshot()) == canonical(loaded.rng.snapshot())
                    print(json.dumps({"seed": seed, "checkpoint_day": state.clock.day,
                        "all_world_fields_and_rng_equal": True,
                        "world_sha256": hashlib.sha256(canonical(asdict(captured)).encode()).hexdigest()}), flush=True)
                    bridge.kernel.restore_checkpoint(loaded.state, loaded.rng, expected_revision=state.revision)
                    restored = True
            if (step + 1) % 4 == 0:
                print(json.dumps({"seed": seed, "days_completed": (step + 1) // 4,
                    "clock": asdict(bridge.kernel._state.clock)}), flush=True)
        state = bridge.kernel._state
        book = ledger(state)
        completed = Counter()
        wages = 0
        for sid, actors in book["records"].items():
            for actor, row in actors.items():
                assert actor != "player", "Audit player must not attend life opportunities"
                if row["status"] == "completed":
                    completed[sid.split(":")[-1]] += 1
                    if book["definitions"][sid.split(":")[-1]].get("job"):
                        # Generic lectures have attendance but no wage receipt;
                        # named paid shifts must have an actual transfer receipt.
                        wages += row["result"]["job"]["wage"]
        outings = Counter(f"{r['kind']}:{r['status']}" for r in state.situations.get("campus_outings", {}).get("records", {}).values())
        bonds = Counter(f"{r['kind']}:{r['status']}" for r in state.situations.get("campus_bonds", {}).get("records", {}).values())
        promotions = sum(len(r.get("promotion_history", [])) for club in state.organizations.values()
            for r in club.get("memberships", {}).values())
        report = {"seed": seed, "days": days, "content_version": state.content_version,
            "completed_opportunities": dict(completed), "actual_wages": wages,
            "outings": dict(outings), "bonds": dict(bonds), "club_promotions": promotions,
            "clinic_receipts": len(state.situations.get("campus_medical", {}).get("receipts", {})),
            "events": dict(sorted(event_counts.items())), "mid_run_disk_restore": restored,
            "paid_api_calls": 0, "injected_plans_or_outcomes": False}
        assert restored and (state.clock.day, state.clock.phase) == (days + 1, "morning")
        assert completed["observation_challenge"] and completed["club_exchange_festival"]
        assert wages > 0 and any(completed[k] for k in completed if book["definitions"][k].get("course"))
        assert any(k.endswith(":completed") for k in outings)
        print(json.dumps(report, ensure_ascii=False, sort_keys=True), flush=True)
        print(f"CAMPUS_LIFE_CLOSURE_OK seed={seed} days={days}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--days", type=int, default=14)
    args = parser.parse_args()
    assert 14 <= args.days <= 28
    audit(args.seed, args.days)
