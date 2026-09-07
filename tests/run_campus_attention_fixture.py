"""A fresh real campus; only the Godot background timer advances attention."""
import argparse
from pathlib import Path
import tempfile
from http.server import ThreadingHTTPServer
from simulation.api.server import CampusKernelBridge, Handler, SimulationBridge


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="campus-attention-fixture-") as directory:
        bridge = SimulationBridge(save_dir=Path(directory))
        bridge.campus = CampusKernelBridge(42)
        Handler.bridge = bridge
        with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
            print("ATTENTION_FIXTURE_READY real_initial_campus no_injected_claims no_paid_api", flush=True)
            server.serve_forever()


if __name__ == "__main__":
    main()
