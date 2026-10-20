"""Puts host/ on the import path, so the tests run with no install."""

import sys
from pathlib import Path

HOST_DIR = Path(__file__).resolve().parents[2] / "host"

if str(HOST_DIR) not in sys.path:
    sys.path.insert(0, str(HOST_DIR))
