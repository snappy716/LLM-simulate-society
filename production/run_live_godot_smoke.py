"""Explicitly paid, headless Godot-to-kernel-to-DeepSeek acceptance; no key files."""
import argparse
import getpass
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

from simulation.api.server import Handler, SimulationBridge
from tests.test_campus_cognition import command


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--godot", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not sys.stdin.isatty():
        parser.error("interactive hidden key input required")
    args.output.mkdir(parents=True, exist_ok=False)
    key = getpass.getpass("DeepSeek API Key (not saved): ")
    with tempfile.TemporaryDirectory(prefix="campus-live-godot-") as directory:
        bridge = SimulationBridge(save_dir=Path(directory) / "saves")
        for _ in range(3):
            assert command(bridge.campus, "ADVANCE_PHASE")["ok"]
        bridge.configure_interface({"provider": "openai_compatible", "base_url": "https://api.deepseek.com",
                                    "model": "deepseek-v4-flash", "api_key": key,
                                    "thinking_mode": "auto", "timeout_seconds": 30})
        del key
        class LiveHandler(Handler):
            pass
        LiveHandler.bridge = bridge
        try:
            with ThreadingHTTPServer(("127.0.0.1", 0), LiveHandler) as server:
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    env = dict(os.environ, GODOT_SIM_EXTERNAL_SERVER="1", GODOT_SIM_PORT=str(server.server_port),
                        GODOT_SIM_DISABLE_SOCIAL_PULSE="1", CAMPUS_LIVE_API_OPT_IN="1",
                        GODOT_SIM_SETTINGS_PATH=str(Path(directory) / "settings.cfg"), GODOT_SIM_SAVE_DIR=str(Path(directory) / "saves"))
                    with (args.output / "godot.log").open("w") as log:
                        process = subprocess.run([args.godot, "--headless", "--path", "game", "--script",
                            "res://tools/test_campus_live_api_flow.gd"], env=env, stdout=log, stderr=subprocess.STDOUT, timeout=260)
                    state = bridge.campus.kernel._state
                    plans = state.cognition["daily_plans"]["actors"]
                    count = sum(all(s["planned_source"] == "llm" for s in plans[n].values()) for n in state.cognition["focused_ids"])
                    summary = {"returncode": process.returncode, "llm_planned_actors": count,
                               "usage": state.cognition["usage"], "provider": bridge.campus.cognition_runtime.public_status()}
                    (args.output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
                    print(json.dumps(summary, ensure_ascii=False), flush=True)
                    assert process.returncode == 0 and count == 20
                    assert "CAMPUS_LIVE_API_FLOW_OK" in (args.output / "godot.log").read_text()
                finally:
                    server.shutdown()
                    thread.join(timeout=5)
        finally:
            bridge.campus.cognition_runtime.configure_rule()


if __name__ == "__main__":
    main()
