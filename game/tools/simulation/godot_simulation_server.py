#!/usr/bin/env python3
"""Godot-facing launcher for the repository simulation API."""
from __future__ import annotations

import sys
from pathlib import Path


REPOSITORY_DIR = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPOSITORY_DIR))

from simulation.api.server import main  # noqa: E402


if __name__ == "__main__":
    main()
