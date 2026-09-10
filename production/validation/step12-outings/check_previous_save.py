"""Read-only audit of an actual pre-outing Godot save; no API or save rewrite."""
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from simulation.api.server import CampusKernelBridge
from simulation.persistence.kernel_checkpoint import load_kernel_checkpoint
from simulation.systems.campus_outings import records, outings_invariant


path = Path(sys.argv[1])
before = hashlib.sha256(path.read_bytes()).hexdigest()
bridge = CampusKernelBridge(42)
loaded = load_kernel_checkpoint(path, expected_content_version=bridge.kernel.state.content_version)
assert "campus_outings" not in loaded.state.situations, "audit requires an actual pre-feature save"
original_world = loaded.state.to_dict()
original_rng = loaded.rng.snapshot()
expected_revision = max(bridge.kernel.state.revision, loaded.state.revision) + 1
bridge.kernel.restore_checkpoint(loaded.state, loaded.rng, expected_revision=bridge.kernel.state.revision)
restored, restored_rng = bridge.kernel.capture_checkpoint()
assert restored.revision == expected_revision  # Existing stale-command protection on load.
original_world["revision"] = expected_revision
assert restored.to_dict() == original_world
assert restored_rng.snapshot() == original_rng
assert records(restored) == {}
assert outings_invariant(restored) == []
view = bridge.snapshot()["agenda"]["outings"]
assert view["records"] == [] and view["slots"]
assert hashlib.sha256(path.read_bytes()).hexdigest() == before
print(json.dumps({"result": "PREVIOUS_GODOT_SAVE_OK", "sha256": before,
    "content_version": restored.content_version, "world_unchanged_except_load_revision": True,
    "load_revision_matches_existing_policy": True, "rng_unchanged": True,
    "save_file_unchanged": True, "retroactive_outings": 0, "available_slots": len(view["slots"]),
    "paid_api_calls": 0}, ensure_ascii=False))
