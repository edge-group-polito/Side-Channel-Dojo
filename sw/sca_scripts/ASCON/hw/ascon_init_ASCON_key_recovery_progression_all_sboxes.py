#!/usr/bin/env python3
"""Hardware entry point for ASCON key-recovery progression."""

import runpy
import sys
from pathlib import Path


def find_project_root(start: Path, markers=("fusesoc.conf", ".dojo_root")) -> Path:
    current = start
    while current != current.parent:
        if any((current / marker).exists() for marker in markers):
            return current
        current = current.parent
    raise RuntimeError(f"Could not find project root from {start}")


SCRIPT_DIR = Path(__file__).resolve().parent
DOJO_ROOT = find_project_root(SCRIPT_DIR)
SW_SCRIPT = (
    DOJO_ROOT
    / "sw"
    / "sca_scripts"
    / "ASCON"
    / "sw"
    / "xheep_ASCON_key_recovery_progression_all_sboxes.py"
)

sys.argv = [str(SW_SCRIPT), "--implementation", "hw", *sys.argv[1:]]
runpy.run_path(str(SW_SCRIPT), run_name="__main__")
