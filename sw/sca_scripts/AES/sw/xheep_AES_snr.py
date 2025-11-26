#!/usr/bin/env python3
"""
Offline SNR analysis for X-HEEP AES traces.

This script:
  - Locates the Side-Channel-Dojo project root.
  - Loads a ChipWhisperer project (.cwp) for a given AES S-box.
  - Computes the SNR of the first-round S-box leakage model OR
    loads a cached SNR curve from disk.
  - Optionally saves the SNR curve and the SNR plot to disk.
"""

import sys
import os
import json
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
import chipwhisperer as cw
import chipwhisperer.analyzer as cwa

# ---------------------------------------------------------------------------
# Project root detection and path setup
# ---------------------------------------------------------------------------

def find_project_root(start: Path, markers=("fusesoc.conf", ".dojo_root")) -> Path:
    """
    Walk upwards from `start` until one of the marker files is found.

    This allows the script to be launched from any subdirectory of the
    repository and still find the global project root.
    """
    current = start
    while current != current.parent:
        if any((current / m).exists() for m in markers):
            return current
        current = current.parent

    raise RuntimeError(
        f"Could not find project root (looked for markers: {markers}). "
        "Please ensure you are inside the Side-Channel-Dojo repository."
    )


# In a script, __file__ exists; in a notebook it might not.
try:
    SCRIPT_DIR = Path(__file__).resolve().parent
except NameError:
    SCRIPT_DIR = Path.cwd()

DOJO_ROOT = find_project_root(SCRIPT_DIR)

# High-level directories
AES_PY_DIR = DOJO_ROOT / "sw" / "ciphers" / "AES_python"
SCA_DIR    = DOJO_ROOT / "sw" / "sca_scripts"
HW_DIR     = DOJO_ROOT / "hw"

# Script-specific directories
XHEEP_DIR      = DOJO_ROOT / "sw" / "x-heep"
TRACESET_DIR   = DOJO_ROOT / "sw" / "traceset" / "AES" / "sw"
BASE_PLOT_DIR  = DOJO_ROOT / "sw" / "sca_scripts" / "AES" / "sw" / "plot"
BASE_CACHE_DIR = DOJO_ROOT / "sw" / "sca_scripts" / "AES" / "sw" / "cache"

# Ensure traceset directory exists
TRACESET_DIR.mkdir(parents=True, exist_ok=True)

# Make local modules importable without fragile ../ relative paths
sys.path.insert(0, str(AES_PY_DIR))
sys.path.insert(0, str(SCA_DIR))
sys.path.insert(0, str(XHEEP_DIR))

from analyzer.attack.aes.SBox_leakage_models import AES128SboxResistantLeakageModels

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# List of available S-box implementations (for reference)
AVAILABLE_SBOXES = [
    "sbox_rijandael  (default AES S-Box, aes_sbox)",
    "sbox_freyre_1",
    "sbox_freyre_2",
    "sbox_freyre_3",
    "sbox_hussain_6",
    "sbox_ozkaynak_1",
    "sbox_azam_1",
    "sbox_azam_2",
    "sbox_azam_3",
]

# Default S-box to analyze
tested_sbox = "sbox_freyre_1"
sbox_id = tested_sbox.replace("sbox_", "")

# Whether we are analyzing traces from a masked firmware or not
masked_flag = False

# Output / flow flags
save_plots          = True   # Save SNR plot as PNG
save_results        = True   # Save SNR curve to JSON cache
load_snr_from_cache = False  # If True, reuse cached SNR instead of recomputing

# ChipWhisperer project (.cwp) path:
#   - Projects are stored under DOJO_ROOT/sw/traceset/AES/sw
if masked_flag:
    project_file_path = TRACESET_DIR / f"CW305_xheep_AES_{sbox_id}_masked.cwp"
else:
    project_file_path = TRACESET_DIR / f"CW305_xheep_AES_{sbox_id}.cwp"

project_file = str(project_file_path)

# Cache and plot directories are organized per S-box
CACHE_DIR = BASE_CACHE_DIR / tested_sbox
PLOT_DIR  = BASE_PLOT_DIR / tested_sbox

# Ensure cache/plot directories exist
TRACESET_DIR.mkdir(parents=True, exist_ok=True)
PLOT_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# SNR cache file path
SNR_CACHE_FILE = CACHE_DIR / f"SNR_{tested_sbox}.json"


def _yn(flag: bool) -> str:
    """Return 'yes' or 'no' for a boolean flag."""
    return "yes" if flag else "no"


def print_configuration() -> None:
    """Pretty-print the current SNR analysis configuration."""
    print("\n================= CONFIGURATION =================")
    print(f"DOJO_ROOT           : {DOJO_ROOT}")
    print()
    print("Target")
    print(f"  Tested S-box              : {tested_sbox}")
    print(f"  Masked firmware           : {_yn(masked_flag)}")
    print()
    print("Paths")
    print(f"  CW project (.cwp)         : {project_file}")
    print(f"  Traceset dir              : {TRACESET_DIR}")
    print(f"  Plot dir                  : {PLOT_DIR}")
    print(f"  Cache dir                 : {CACHE_DIR}")
    print(f"  SNR cache file            : {SNR_CACHE_FILE}")
    print()
    print("Offline phase / SNR analysis")
    print(f"  Save plots                : {_yn(save_plots)}")
    print(f"  Save results              : {_yn(save_results)}")
    print(f"  Load SNR from cache       : {_yn(load_snr_from_cache)}")
    print("=================================================\n")


# ---------------------------------------------------------------------------
# SNR cache helpers
# ---------------------------------------------------------------------------

def save_snr_results(snr_array: np.ndarray, filename: Path, meta=None) -> None:
    """
    Save SNR curve and optional metadata to a JSON cache file.

    Args:
        snr_array: numpy array of float64 (e.g., output of calculate_snr).
        filename: path to the JSON file.
        meta: optional dict with extra info (e.g., tested_sbox, N, masked, ...).
    """
    if meta is None:
        meta = {}

    data = {
        "snr": snr_array.tolist(),   # JSON-serializable
        "dtype": "float64",          # for clarity
        "meta": meta,
    }
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    with open(filename, "w") as f:
        json.dump(data, f, indent=2)


def load_snr_results(filename: Path):
    """
    Load SNR curve and metadata from a JSON cache file.

    Returns:
        snr_array: numpy array of dtype float64
        meta: dict with any stored metadata
    """
    with open(filename, "r") as f:
        data = json.load(f)

    snr_array = np.array(data["snr"], dtype=np.float64)
    meta = data.get("meta", {})
    return snr_array, meta


# ---------------------------------------------------------------------------
# Core SNR analysis
# ---------------------------------------------------------------------------

def run_snr_analysis() -> None:
    """Open CW project, compute or load SNR, and generate the SNR plot."""
    print_configuration()

    # -----------------------------------------------------------------------
    # Open ChipWhisperer project
    # -----------------------------------------------------------------------
    try:
        project = cw.open_project(project_file)
        print(f"[OFFLINE] Loaded project file: {project_file}")
    except Exception as e:
        print(f"[ERROR] Failed to open project file '{project_file}': {e}")

        # If the file does not exist, give a clear hint about the capture phase
        if not Path(project_file).exists():
            print(
                "[HINT] The ChipWhisperer project file does not exist.\n"
                "       Make sure you have run the power-trace capture notebook "
                "'xheep_capture_AES.ipynb' (or the equivalent capture script) first."
            )
        # Stop here: analysis cannot continue without the traces
        raise

    try:
        print("Generating SNR plot...")

        snr_fr = None
        snr_meta = {}

        # -------------------------------------------------------------------
        # Try to load SNR from cache if requested
        # -------------------------------------------------------------------
        if load_snr_from_cache:
            try:
                snr_fr, snr_meta = load_snr_results(SNR_CACHE_FILE)
                print(f"[OFFLINE] Loaded cached SNR from: {SNR_CACHE_FILE}")
            except FileNotFoundError:
                print(f"[WARN] SNR cache file not found at {SNR_CACHE_FILE}, recomputing SNR.")
                # Fall back to recomputation
            except Exception as e:
                print(f"[ERROR] Failed to load SNR cache from {SNR_CACHE_FILE}: {e}")
                # Fall back to recomputation

        # -------------------------------------------------------------------
        # If not loaded from cache, compute SNR
        # -------------------------------------------------------------------
        if snr_fr is None:
            leak_model = AES128SboxResistantLeakageModels().FirstRound_ModifiedSbox_Output(
                tested_sbox
            )
            snr_fr = cwa.calculate_snr(project.traces, leak_model=leak_model, db=False)

            if save_results:
                snr_meta = {
                    "tested_sbox": tested_sbox,
                    "masked": masked_flag,
                    "num_traces": len(project.traces),
                }
                save_snr_results(snr_fr, SNR_CACHE_FILE, meta=snr_meta)
                print(f"[OFFLINE] SNR results cached to: {SNR_CACHE_FILE}")

        # -------------------------------------------------------------------
        # Plot SNR curve
        # -------------------------------------------------------------------
        plt.figure(figsize=(12, 6))
        plt.plot(np.arange(len(snr_fr)), snr_fr, alpha=0.5)
        plt.xlabel("Sample")
        plt.ylabel("SNR")
        plt.title("SNR in time")
        plt.grid(True)

        out_file = (
            PLOT_DIR
            / (
                f"AES_masked_SNR_{tested_sbox}.png"
                if masked_flag
                else f"AES_SNR_{tested_sbox}.png"
            )
        )
        if save_plots:
            plt.savefig(out_file)
            print(f"[OFFLINE] SNR plot saved to: {out_file}")

        # Uncomment if you want interactive display when running manually
        # plt.show()
        plt.close()

    finally:
        # Close the project to release file handles
        project.close()
        print("[OFFLINE] Project closed.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_snr_analysis()
