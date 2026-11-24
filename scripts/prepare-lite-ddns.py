#!/usr/bin/env python3
"""Compatibility entry for the TR3000 host helper."""
from pathlib import Path
import runpy
runpy.run_path(str(Path(__file__).resolve().parents[1] / "devices/tr3000/build/prepare-lite-ddns.py"), run_name="__main__")
