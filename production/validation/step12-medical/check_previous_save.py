"""Read-only proof that an actual pre-clinic Godot save restores unchanged."""
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from simulation.api.server import CampusKernelBridge
from simulation.persistence.kernel_checkpoint import load_kernel_checkpoint
from simulation.systems.campus_medical import ledger, medical_invariant, medical_view

path = Path(sys.argv[1])
checksum = hashlib.sha256(path.read_bytes()).hexdigest()
bridge = CampusKernelBridge(42)
loaded = load_kernel_checkpoint(path, expected_content_version=bridge.kernel.state.content_version)
assert "campus_medical" not in loaded.state.situations
expected = loaded.state.to_dict()
expected_rng = loaded.rng.snapshot()
expected["revision"] = max(bridge.kernel.state.revision, loaded.state.revision) + 1
bridge.kernel.restore_checkpoint(loaded.state, loaded.rng, expected_revision=bridge.kernel.state.revision)
restored, rng = bridge.kernel.capture_checkpoint()
assert restored.to_dict() == expected and rng.snapshot() == expected_rng
assert not ledger(restored) and not medical_invariant(restored)
assert medical_view(restored)["receipts"] == []
assert medical_view(restored)["available_visits"] == 0
assert hashlib.sha256(path.read_bytes()).hexdigest() == checksum
print(json.dumps({"result": "PRE_MEDICAL_GODOT_SAVE_OK", "sha256": checksum,
    "content_version": restored.content_version, "world_unchanged_except_load_revision": True,
    "rng_unchanged": True, "no_retroactive_shifts": True, "source_file_unchanged": True, "paid_api_calls": 0}))
