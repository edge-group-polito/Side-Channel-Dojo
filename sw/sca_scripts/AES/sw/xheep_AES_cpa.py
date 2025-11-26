#!/usr/bin/env python3
"""
Offline CPA analysis on X-HEEP AES traces:

- Locates the Side-Channel-Dojo project root.
- Loads a ChipWhisperer project (.cwp) for a given S-box.
- Runs CPA (or loads cached CPA results).
- Optionally plots PGE vs traces and correlation vs traces.
"""

import sys
import os
import json
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import holoviews as hv
hv.extension("bokeh")

import chipwhisperer as cw
import chipwhisperer.analyzer as cwa
from tqdm import tqdm
import logging


# ---------------------------------------------------------------------------
# Project root detection and path setup
# ---------------------------------------------------------------------------

def find_project_root(start: Path, markers=("fusesoc.conf", ".dojo_root")) -> Path:
    """
    Walk upwards from `start` until one of the marker files is found.

    This lets the script be run from anywhere inside the repository while
    still locating the project root (DOJO_ROOT).
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

try:
    SCRIPT_DIR = Path(__file__).resolve().parent
except NameError:
    SCRIPT_DIR = Path.cwd()

DOJO_ROOT = find_project_root(SCRIPT_DIR)

AES_PY_DIR = DOJO_ROOT / "sw" / "ciphers" / "AES_python"
SCA_DIR    = DOJO_ROOT / "sw" / "sca_scripts"
HW_DIR     = DOJO_ROOT / "hw"

# Script-specific dirs
XHEEP_DIR      = DOJO_ROOT / "sw" / "x-heep"
TRACESET_DIR   = DOJO_ROOT / "sw" / "traceset" / "AES" / "sw"
BASE_PLOT_DIR  = DOJO_ROOT / "sw" / "sca_scripts" / "AES" / "sw" / "plot"
BASE_CACHE_DIR = DOJO_ROOT / "sw" / "sca_scripts" / "AES" / "sw" / "cache"

# Make local modules importable
sys.path.insert(0, str(AES_PY_DIR))
sys.path.insert(0, str(SCA_DIR))
sys.path.insert(0, str(XHEEP_DIR))

from analyzer.attack.aes.SBox_leakage_models import AES128SboxResistantLeakageModels
from analyzer.attack.aes.key_schedule import key_schedule_rounds

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

AVAILABLE_SBOXES = [
    "sbox_rijandael",  # default AES S-Box (aes_sbox)
    "sbox_freyre_1",
    "sbox_freyre_2",
    "sbox_freyre_3",
    "sbox_hussain_6",
    "sbox_ozkaynak_1"
]

tested_sbox = "sbox_freyre_1"
sbox_id = tested_sbox.replace("sbox_", "")

masked_flag = False

# Flow flags
load_attack_results   = False  # load PGE/corr from JSON cache if available
save_attack_results   = True   # save PGE/corr to JSON cache after CPA
traces_pge_plot       = True   # Plot PGE vs traces
traces_correlation_plot = True # Plot correlation vs traces
save_plots            = True   # Save plots to disk
save_results          = True   # (reserved for other results if needed)

# Paths
if masked_flag:
    project_file_path = TRACESET_DIR / f"CW305_xheep_AES_{sbox_id}_masked.cwp"
else:
    project_file_path = TRACESET_DIR / f"CW305_xheep_AES_{sbox_id}.cwp"

project_file = str(project_file_path)

CACHE_DIR = BASE_CACHE_DIR / tested_sbox
PLOT_DIR  = BASE_PLOT_DIR / tested_sbox
CPA_CACHE_FILE = CACHE_DIR / f"CPA_results_{tested_sbox}.json"

TRACESET_DIR.mkdir(parents=True, exist_ok=True)
PLOT_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _yn(flag: bool) -> str:
    """Return 'yes' or 'no' for a boolean flag."""
    return "yes" if flag else "no"


def print_configuration():
    """Pretty-print the analysis configuration."""
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
    print()
    print("Analysis configuration")
    print(f"  Save plots                : {_yn(save_plots)}")
    print(f"  Save results              : {_yn(save_results)}")
    print(f"  Load CPA results (cache)  : {_yn(load_attack_results)}")
    print(f"  Save CPA results (cache)  : {_yn(save_attack_results)}")
    print()
    print(f"  PGE plot                  : {_yn(traces_pge_plot)}")
    print(f"  Correlation plot          : {_yn(traces_correlation_plot)}")
    print("=================================================\n")


# ---------------------------------------------------------------------------
# CPA cache helpers
# ---------------------------------------------------------------------------

def save_cpa_results(x_axis,
                     pge_per_byte,
                     corr_correct,
                     corr_wrong_max,
                     filename,
                     meta=None):
    """
    Save PGE and correlation trends for each subkey to a JSON file.

    Stored data:
      - x_axis: trace indices (shared for all bytes)
      - pge[byte]: PGE vs traces
      - corr_correct[byte]: correlation curve of correct key guess
      - corr_wrong_max[byte]: max correlation over all wrong key guesses
    """
    if meta is None:
        meta = {}

    data = {
        "x_axis": list(x_axis),
        "pge": [list(p) for p in pge_per_byte],
        "corr_correct": corr_correct,
        "corr_wrong_max": corr_wrong_max,
        "meta": meta,
    }

    os.makedirs(os.path.dirname(filename), exist_ok=True)
    with open(filename, "w") as f:
        json.dump(data, f, indent=2)


def load_cpa_results(filename):
    """
    Load PGE and correlation curves for each subkey from a JSON file.

    Returns:
        x_axis: numpy array (int)
        pge_per_byte: list of numpy arrays
        corr_correct: list of numpy arrays
        corr_wrong_max: list of numpy arrays
        meta: dict
    """
    with open(filename, "r") as f:
        data = json.load(f)

    x_axis = np.array(data["x_axis"], dtype=np.int64)
    pge_per_byte = [np.array(p, dtype=np.float64) for p in data["pge"]]
    corr_correct = [np.array(c, dtype=np.float64) for c in data["corr_correct"]]
    corr_wrong_max = [np.array(c, dtype=np.float64) for c in data["corr_wrong_max"]]
    meta = data.get("meta", {})

    return x_axis, pge_per_byte, corr_correct, corr_wrong_max, meta


# ---------------------------------------------------------------------------
# ChipWhisperer CPA helper callback
# ---------------------------------------------------------------------------

def _default_python_callback(attack):
    """
    Default Python callback used by ChipWhisperer during CPA analysis.

    It extracts attack results, computes PGE, and can be extended to store
    intermediate statistics if needed.
    """
    global current_trace_iteration
    attack_results = attack.results
    key = attack.known_key()

    attack_results.set_known_key(key)
    stat_data = attack_results.find_maximums()
    df = pd.DataFrame(stat_data).transpose()

    # Add PGE row
    df_pge = (
        pd.DataFrame(attack_results.pge)
        .transpose()
        .rename(index={0: "PGE="}, columns=int)
    )
    df = pd.concat([df_pge, df], ignore_index=False)

    reporting_interval = attack.reporting_interval
    tstart = current_trace_iteration * reporting_interval
    tend = tstart + reporting_interval
    current_trace_iteration += 1
    # (df, tstart, tend) could be stored or logged if needed


def get_python_callback(attack):
    """
    Wrap `_default_python_callback` into a closure that keeps track of
    the current trace iteration.
    """
    global current_trace_iteration
    current_trace_iteration = 0
    return lambda: _default_python_callback(attack)


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def to_hex_str(x):
    """Format a bytes-like / iterable of ints as spaced lowercase hex."""
    return " ".join(f"{b:02x}" for b in x)


def byte_to_color(idx):
    """Map byte index to a color (Category20 palette)."""
    return hv.Palette.colormaps["Category20"](idx / 16.0)


# ---------------------------------------------------------------------------
# Core CPA analysis
# ---------------------------------------------------------------------------

def run_cpa_and_cache(project):
    """
    Run CPA (or load cached results) and return:
    x_axis, pge_per_byte, corr_correct, corr_wrong_max, key
    """
    global load_attack_results

    if load_attack_results:
        try:
            (x_axis,
             pge_per_byte,
             corr_correct,
             corr_wrong_max,
             cpa_meta) = load_cpa_results(CPA_CACHE_FILE)

            print(f"[OFFLINE] Loaded cached CPA results from: {CPA_CACHE_FILE}")
            key = cpa_meta.get("key", [])
            return x_axis, pge_per_byte, corr_correct, corr_wrong_max, key
        except FileNotFoundError:
            print(f"[WARN] CPA cache file not found at {CPA_CACHE_FILE}, running attack instead.")
            load_attack_results = False
        except Exception as e:
            print(f"[ERROR] Failed to load CPA cache from {CPA_CACHE_FILE}: {e}")
            load_attack_results = False

    # Run CPA if we are not loading from cache
    print("Running CPA attack (this might take a while)...")
    leak_model = AES128SboxResistantLeakageModels().FirstRound_ModifiedSbox_Output(
        tested_sbox
    )
    attack = cwa.cpa(project, leak_model)
    results = attack.run(get_python_callback(attack))
    print("CPA attack finished. Results:")
    print(results)

    # Recover key from first-round key and key schedule
    recv_firstroundkey = [kguess[0][0] for kguess in results.find_maximums()]
    recv_key = key_schedule_rounds(recv_firstroundkey, 0, 0, tested_sbox)
    print("Recovered key: ", [hex(subkey) for subkey in recv_key])

    key = list(project.keys[0])
    if key != recv_key:
        logging.warning(
            "Failed to recover encryption key!\nGot {}\nExp {}\n".format(
                [hex(k) for k in recv_key], [hex(k) for k in key]
            )
        )
    else:
        print("Key recovery : Success!")

    # Extract PGE and correlation trends from ChipWhisperer results
    plot_data = cwa.analyzer_plots(results)

    # PGE per byte (x_axis shared)
    x_axis = plot_data.pge_vs_trace(0)[0]
    pge_per_byte = [plot_data.pge_vs_trace(i)[1] for i, _ in enumerate(key)]

    # Correlation curves per byte
    corr_correct = []
    corr_wrong_max = []

    for bnum, _ in enumerate(key):
        x_corr, corr_matrix = plot_data.corr_vs_trace(bnum)
        corr_matrix = np.array(corr_matrix)

        # Index of correct key guess for this byte
        correct_idx = results.known_key[bnum]

        # Correct key correlation curve
        corr_correct.append(corr_matrix[correct_idx])

        # Max over all wrong key guesses at each trace
        wrong_mask = [i != correct_idx for i in range(256)]
        wrong_results = corr_matrix[wrong_mask]
        corr_wrong_max.append(np.amax(wrong_results, axis=0))

        # Sanity check: x_axis should match x_corr
        if list(x_axis) != list(x_corr):
            raise RuntimeError("x_axis mismatch between PGE and correlation data")


    # Save CPA curves to cache if requested
    if save_attack_results:
        meta = {
            "tested_sbox": tested_sbox,
            "masked": masked_flag,
            "num_traces": len(project.traces),
            "key": [hex(k) for k in key],
            "recovered key": [hex(k) for k in recv_key],
        }
        save_cpa_results(x_axis, pge_per_byte, corr_correct, corr_wrong_max,CPA_CACHE_FILE, meta=meta)
        print(f"[ANALYSIS] CPA results cached to: {CPA_CACHE_FILE}")

    return x_axis, pge_per_byte, corr_correct, corr_wrong_max, key


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------

def plot_pge(x_axis, pge_per_byte, key):
    """Plot PGE vs traces for all key bytes."""
    print("Generating PGE vs Traces plot...")

    fig, ax1 = plt.subplots(nrows=1, ncols=1, sharex=True, figsize=[14, 10])
    plt.grid(which="major", axis="both", alpha=0.2)

    step = 500

    # pge_per_byte[i] is a 1D array: PGE over traces for byte i
    for i, _ in enumerate(key):
        plt.plot(x_axis, pge_per_byte[i], linewidth=1, label=f"Byte #{i}")

    # Horizontal guideline at PGE = 10
    plt.plot(
        x_axis,
        [10] * len(x_axis),
        linewidth=1,
        linestyle="dashed",
        color="black",
        label="max(PGE) < 10",
    )

    plt.legend(title="Known Key", fontsize=12, loc="upper right")
    plt.title(f"AES S-Box {sbox_id} - PGE", fontsize=18)
    ax1.set_xticks(range(0, x_axis[-1], step))
    ax1.set_ylabel("Partial Guessing Entropy (PGE)", fontsize=16)
    ax1.set_xlabel("Traces", fontsize=16)
    ax1.set_xlim(0, x_axis[-1])

    out_file = (
        PLOT_DIR
        / (
            f"AES_masked_PGE_{tested_sbox}.png"
            if masked_flag
            else f"AES_PGE_{tested_sbox}.png"
        )
    )
    if save_plots:
        plt.savefig(out_file)
        print(f"[OFFLINE] PGE plot saved to: {out_file}")

    # plt.show()
    plt.close(fig)


def plot_correlation(x_axis, corr_correct, corr_wrong_max):
    """Plot correlation of correct vs. wrong key guesses over traces."""
    print("Generating Correlation plot...")

    bnum_it = range(len(corr_correct))

    fig, ax1 = plt.subplots(nrows=1, ncols=1, sharex=True, figsize=[18, 12])
    plt.grid(which="major", axis="both", alpha=0.2)

    # Plot correlation trends of wrong key guesses (max over all wrong keys)
    for bnum in bnum_it:
        ax1.plot(
            x_axis,
            corr_wrong_max[bnum],
            linewidth=2,
            linestyle="dotted",
            color=byte_to_color(bnum),
        )

    # Plot correct key guesses on top of wrong ones
    for bnum in bnum_it:
        ax1.plot(
            x_axis,
            corr_correct[bnum],
            linewidth=1,
            label=f"Byte #{bnum}",
            color=byte_to_color(bnum),
        )

    ax1.legend(title="Known Key", fontsize=12, loc="upper right")
    plt.title(f"AES S-Box {sbox_id} - Correlations", fontsize=18)

    step = 200
    ax1.set_xticks(range(0, x_axis[-1], step))
    ax1.set_ylabel("Correlation", fontsize=16)
    ax1.set_xlabel("Traces", fontsize=16)

    out_file = (
        PLOT_DIR
        / (
            f"AES_masked_correlations_{tested_sbox}.png"
            if masked_flag
            else f"AES_correlations_{tested_sbox}.png"
        )  
    )
    if save_plots:
        plt.savefig(out_file)
        print(f"[OFFLINE] Correlation plot saved to: {out_file}")

    # plt.show()
    plt.close(fig)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print_configuration()

    # Open project
    try:
        project = cw.open_project(project_file)
        print(f"[OFFLINE] Loaded project file: {project_file}")
    except Exception as e:
        print(f"[ERROR] Failed to open project file '{project_file}': {e}")
        if not Path(project_file).exists():
            print(
                "[HINT] The ChipWhisperer project file does not exist.\n"
                "       Make sure you have run the power-trace capture notebook "
                "'xheep_capture_AES.ipynb' (or the equivalent capture script) first."
            )
        raise

    try:
        # CPA + cache
        x_axis, pge_per_byte, corr_correct, corr_wrong_max, key = run_cpa_and_cache(project)

        # Plots
        if traces_pge_plot:
            plot_pge(x_axis, pge_per_byte, key)

        if traces_correlation_plot:
            plot_correlation(x_axis, corr_correct, corr_wrong_max)

    finally:
        project.close()
        print("[OFFLINE] Project closed.")


if __name__ == "__main__":
    main()
