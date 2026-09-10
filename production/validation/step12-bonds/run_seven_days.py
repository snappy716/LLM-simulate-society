"""Unattended natural worlds; report zero romance honestly. No paid network."""
from collections import Counter
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from simulation.actions.commands import SimulationCommand
from simulation.api.server import CampusKernelBridge
from simulation.persistence.kernel_checkpoint import save_kernel_checkpoint, load_kernel_checkpoint
from simulation.systems.campus_bonds import records, bond_view, bonds_invariant
from simulation.systems.campus_outings import records as outings, outings_invariant


def run(seed):
    with patch("urllib.request.urlopen", side_effect=AssertionError("offline audit forbids API")):
        bridge = CampusKernelBridge(seed)
        assert not bridge.cognition_runtime.provider.configured
        for step in range(28):
            state = bridge.kernel._state
            result = bridge.kernel.execute(SimulationCommand(f"bonds-natural:{seed}:{step}", "player", "ADVANCE_PHASE",
                state.revision, issued_day=state.clock.day, issued_phase=state.clock.phase))
            assert result.success, result.code
            state = bridge.kernel._state
            assert not bonds_invariant(state) and not outings_invariant(state)
            assert not bridge.cognition_runtime.provider.configured
            assert all("player" in (r["proposer_id"], r["recipient_id"]) for r in bond_view(state)["records"])
            assert not any(r["status"] == "active" and r["recipient_id"] == "player" for r in records(state).values())
            if step == 13:
                checkpoint, rng = bridge.kernel.capture_checkpoint()
                with TemporaryDirectory(prefix="bonds-audit-save-") as directory:
                    path = Path(directory) / "checkpoint.json"
                    save_kernel_checkpoint(path, checkpoint, rng, content_manifest=bridge.registry.manifest)
                    loaded = load_kernel_checkpoint(path, expected_content_version=checkpoint.content_version)
                    assert records(loaded.state) == records(checkpoint)
                    assert loaded.rng.snapshot() == rng.snapshot()
                    bridge.kernel.restore_checkpoint(loaded.state, loaded.rng, expected_revision=checkpoint.revision)
            if step % 4 == 3:
                print(json.dumps({"seed": seed, "elapsed_days": (step + 1) // 4,
                    "bond_requests": len(records(state)), "outings": len(outings(state))}), flush=True)
        state = bridge.kernel._state
        result = {"result": "BONDS_SEVEN_DAYS_OK", "seed": seed, "elapsed_days": 7,
            "bonds": dict(Counter(f"{r['kind']}:{r['status']}" for r in records(state).values())),
            "outings": dict(Counter(f"{r['kind']}:{r['status']}" for r in outings(state).values())),
            "player_participation": False, "injected_relationships_or_dates": False, "paid_api_calls": 0}
        print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    for seed in (42, 314): run(seed)
