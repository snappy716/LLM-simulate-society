"""Actual prior Godot checkpoint: additive event catalogue, no historical scores."""
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from simulation.api.server import CampusKernelBridge
from simulation.persistence.kernel_checkpoint import load_kernel_checkpoint
from simulation.systems.campus_life import ledger, life_invariant

path = Path(sys.argv[1])
source = path.read_bytes()
with patch("urllib.request.urlopen", side_effect=AssertionError("offline save check")):
    old = load_kernel_checkpoint(path)
    bridge = CampusKernelBridge(42)
    loaded = load_kernel_checkpoint(path, expected_content_version=bridge.registry.content_version)
    assert loaded.migrations[-1] == "campus-events-v1"
    assert ledger(loaded.state)["records"] == ledger(old.state)["records"]
    compared = loaded.state.clone()
    ledger(compared)["definitions"] = ledger(old.state)["definitions"]
    assert ledger(compared).pop("events_available_from") == {"day": old.state.clock.day, "phase": old.state.clock.phase}
    compared.content_version = old.state.content_version
    assert compared.to_dict() == old.state.to_dict()
    assert loaded.rng.snapshot() == old.rng.snapshot()
    assert not list(life_invariant(loaded.state))
    bridge.kernel.restore_checkpoint(loaded.state, loaded.rng, expected_revision=bridge.kernel._state.revision)
    assert bridge.snapshot()["agenda"]["life"]["event_board"] == []
    assert path.read_bytes() == source
    print(json.dumps({"result": "PRE_EVENTS_GODOT_SAVE_OK", "sha256": hashlib.sha256(source).hexdigest(),
        "only_additive_definitions_availability_and_content_identity": True, "existing_records_and_rng_unchanged": True,
        "no_retroactive_event_results": True, "source_file_unchanged": True, "paid_api_calls": 0}))
