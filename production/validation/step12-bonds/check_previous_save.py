"""Read-only check of a pre-bond checkpoint produced by actual Godot save flow."""
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from simulation.api.server import CampusKernelBridge
from simulation.persistence.kernel_checkpoint import load_kernel_checkpoint
from simulation.systems.campus_bonds import records, bond_view, bonds_invariant

path = Path(sys.argv[1])
before = hashlib.sha256(path.read_bytes()).hexdigest()
with patch("urllib.request.urlopen", side_effect=AssertionError("offline check forbids API")):
    bridge = CampusKernelBridge(42)
    loaded = load_kernel_checkpoint(path, expected_content_version=bridge.kernel.state.content_version)
    assert "campus_bonds" not in loaded.state.situations
    expected = loaded.state.to_dict()
    expected["revision"] = max(bridge.kernel.state.revision, loaded.state.revision) + 1
    bridge.kernel.restore_checkpoint(loaded.state, loaded.rng, expected_revision=bridge.kernel.state.revision)
    restored, rng = bridge.kernel.capture_checkpoint()
    assert restored.to_dict() == expected
    assert rng.snapshot() == loaded.rng.snapshot()
    assert not records(restored) and not bonds_invariant(restored)
    assert bond_view(restored)["records"] == []
    assert bridge.snapshot()["agenda"]["bonds"]["records"] == []
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    print(json.dumps({"result": "PRE_BONDS_GODOT_SAVE_OK", "sha256": before,
        "world_unchanged_except_load_revision": True, "rng_unchanged": True,
        "no_retroactive_bonds": True, "source_file_unchanged": True, "paid_api_calls": 0}))
