"""Repeatable offline Godot acceptance on macOS/Windows (no paid LLM calls).

Usage: python production/run_godot_checks.py --godot /path/to/Godot
Every flow receives its own existing settings directory, save directory and
loopback port. Logs are retained under a printed temporary directory.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
STANDARD = (
    "components", "navigation_flow", "collab_flow", "combat_round_flow", "departure_flow",
    "inventory_flow", "save_flow", "theme_flow", "inspector_layout", "hud_feedback",
    "operation_feedback", "phone_layout", "social_ui", "startup_flow", "ui_request_lifecycle", "overnight_flow",
)
FIXTURES = ("recovery", "trade", "supply", "enemy", "retreat", "pollution", "combat_item", "investigation", "growth", "knowledge", "goals", "assistance", "autonomous", "expedition", "attention", "fieldwork", "sites", "friend")


def unused_port():
    with socket.socket() as connection:
        connection.bind(("127.0.0.1", 0))
        return connection.getsockname()[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--godot", required=True)
    parser.add_argument("--flows", nargs="+", choices=(*STANDARD, *FIXTURES))
    args = parser.parse_args()
    directory = Path(tempfile.mkdtemp(prefix="campus-godot-checks-"))
    print(f"GODOT_CHECK_LOGS {directory}", flush=True)
    for flow in args.flows or (*STANDARD, *FIXTURES):
        work = directory / flow
        work.mkdir()
        (work / "saves").mkdir()
        port = unused_port()
        environment = dict(os.environ, GODOT_SIM_PORT=str(port),
                           GODOT_SIM_DISABLE_SOCIAL_PULSE="0" if flow == "attention" else "1",
                           GODOT_SIM_SAVE_DIR=str(work / "saves"),
                           GODOT_SIM_SETTINGS_PATH=str(work / "settings.cfg"))
        environment.pop("GODOT_COMBAT_ITEM_INSPECT", None)
        environment.pop("GODOT_SIM_EXTERNAL_SERVER", None)
        fixture = None
        try:
            with (work / "fixture.log").open("w", encoding="utf-8") as fixture_log:
                if flow in FIXTURES:
                    environment["GODOT_SIM_EXTERNAL_SERVER"] = "1"
                    fixture = subprocess.Popen(
                        [sys.executable, "-m", f"tests.run_campus_{flow}_fixture", "--port", str(port)],
                        cwd=ROOT, stdout=fixture_log, stderr=subprocess.STDOUT,
                    )
                    deadline = time.monotonic() + 60
                    while "FIXTURE_READY" not in (work / "fixture.log").read_text(encoding="utf-8"):
                        if fixture.poll() is not None or time.monotonic() >= deadline:
                            raise RuntimeError(f"{flow} fixture did not become ready; see {work}")
                        time.sleep(0.1)
                script = f"{flow}_flow" if flow in FIXTURES else flow
                with (work / "godot.log").open("w", encoding="utf-8") as log:
                    completed = subprocess.run(
                        [args.godot, "--headless", "--path", str(ROOT / "game"),
                         "--script", f"res://tools/test_campus_{script}.gd"],
                        cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT,
                        timeout=120,
                    )
                output = (work / "godot.log").read_text(encoding="utf-8")
                markers = [line for line in output.splitlines() if line.startswith("CAMPUS_") and "_OK" in line]
                if completed.returncode or not markers or "SCRIPT ERROR" in output or "ERROR:" in output:
                    print(output, flush=True)
                    raise RuntimeError(f"{flow} failed; see {work}")
                print(f"PASS {flow}: {markers[-1]}", flush=True)
        finally:
            if fixture is not None:
                fixture.terminate()
                try:
                    fixture.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    fixture.kill()
                    fixture.wait(timeout=5)
    print(f"GODOT_CHECKS_OK {len(args.flows or (*STANDARD, *FIXTURES))} flows", flush=True)


if __name__ == "__main__":
    main()
