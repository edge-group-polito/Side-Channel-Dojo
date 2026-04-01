#!/usr/bin/env python3

"""
Batch CPA analysis over multiple AES S-box variants.

For each S-box, this script:
  1. Opens the corresponding ChipWhisperer project (.cwp).
  2. Runs a CPA attack with a chosen leakage model.
  3. Tracks the success rate vs. number of traces.
  4. Computes how many traces are needed to reach a target success rate.
  5. Saves results to a JSON cache and generates a bar chart.

It is designed to be run from anywhere inside the repository, as it
automatically detects the project root (DOJO_ROOT) by walking upwards
until the marker file ('.dojo_root') is found .
"""

import sys
import time
import json
from pathlib import Path
from multiprocessing import Pool, cpu_count

import matplotlib.pyplot as plt
import chipwhisperer as cw
import chipwhisperer.analyzer as cwa
from analyzer.attack.aes.SBox_leakage_models import AES128SboxResistantLeakageModels


# ============================================================================
# Project root detection and path setup
# ============================================================================

def find_dojo_root(start: Path, markers=(".dojo_root")) -> Path:
    """
    Walk upwards from `start` until one of the marker files is found.

    This allows the script to be executed from arbitrary locations inside
    the repository, while still reliably finding the project root.
    """
    current = start
    while current != current.parent:
        if any((current / m).exists() for m in markers):
            return current
        current = current.parent

    raise RuntimeError(
        f"Could not find project root (looked for markers: {markers}). "
        "Please ensure you are inside the DOJO repository."
    )


# Folder where this script lives
SCRIPT_DIR = Path(__file__).resolve().parent

# Top-level project root (containing e.g. 'build', 'hw', 'sw', 'fusesoc.conf', ...)
DOJO_ROOT = find_dojo_root(SCRIPT_DIR)

# Convenience paths inside the repository
SW_DIR = DOJO_ROOT / "sw"
HW_DIR = DOJO_ROOT / "hw"

# Python side-channel analysis code (for imports, sys.path)
SCA_DIR = SW_DIR / "sca_scripts"

# Directory where graphs/results for x-heep AES experiments are stored
XHEEP_GRAPHS_DIR = SW_DIR / "x-heep" / "Graphs" / "AES_c"

# Make local analysis code importable
sys.path.insert(0, str(SCA_DIR))


# ============================================================================
# Configuration
# ============================================================================

# List of S-box IDs to test (replace/extend with your actual S-box IDs or names)
sbox_ids = [
    "sbox_rijandael",  # default AES S-Box (aes_sbox)
    "sbox_freyre_1",
    "sbox_freyre_2",
    "sbox_freyre_3",
    "sbox_hussain_6",
    "sbox_ozkaynak_1",
]

# Default resolution: number of traces added between each success-rate evaluation
# Can be overridden via command-line argument "--resolution <N>"
resolution = 25

# Target average success rate (e.g., 1.0 -> 100%) used to compute "traces needed"
success_rate_threshold = 1.0  # values in range [0.0, 1.0]

# Fixed AES-128 key used by the leakage model / reference
key = [
    0x2B, 0x7E, 0x15, 0x16,
    0x28, 0xAE, 0xD2, 0xA6,
    0xAB, 0xF7, 0x15, 0x88,
    0x09, 0xCF, 0x4F, 0x3C,
]


# ============================================================================
# Core analysis functions
# ============================================================================

def compute_success_rate_for_sbox(sbox_id: str):
    """
    Run a CPA attack for a single S-box and return its success-rate curve.

    Returns:
        (sbox_id, success_rate_list)
    where success_rate_list[i] is the average success rate after (i+1)*resolution traces.
    """
    success_rate = []

    # Remove 'sbox_' prefix for filenames (matches how the .cwp is named)
    tested_sbox = sbox_id.replace("sbox_", "")

    # Path to the ChipWhisperer project for this S-box
    project_file_path = DOJO_ROOT / "build" / "xheep_test" / f"CW305_xheep_AES_{tested_sbox}.cwp"
    project_file = str(project_file_path)

    try:
        project = cw.open_project(project_file)
    except Exception as e:
        print(f"[WARN] Could not open project file {project_file}: {e}")
        return (sbox_id, success_rate)

    # Leakage model and CPA attack configuration
    global key
    leak_model = AES128SboxResistantLeakageModels().FirstRound_ModifiedSbox_Output(sbox_id)
    attack = cwa.cpa(project, leak_model)

    def success_rate_callback():
        """
        Callback invoked by ChipWhisperer after each batch of traces.

        It computes the average byte-wise success rate and appends it
        to the global `success_rate` list for this S-box.
        """
        results = attack.results
        guessed_key = [kguess[0][0] for kguess in results.find_maximums()]
        iteration_success_rate = [1 if k == g else 0 for k, g in zip(key, guessed_key)]
        avg_success_rate = sum(iteration_success_rate) / len(iteration_success_rate)
        success_rate.append(avg_success_rate)

    # Run the CPA attack, evaluating success rate every `resolution` traces
    attack.run(success_rate_callback, resolution)
    project.close()

    return (sbox_id, success_rate)


def find_traces_for_threshold(success_rate, threshold: float, resolution: int):
    """
    Given a success-rate curve, find the number of traces required
    to reach a given success-rate threshold.

    Args:
        success_rate: list of success-rate values in [0.0, 1.0]
        threshold: target success rate in [0.0, 1.0]
        resolution: number of traces added between curve points

    Returns:
        traces_needed (int) or None if the threshold is never reached.
    """
    for i, sr in enumerate(success_rate):
        if sr >= threshold:
            return (i + 1) * resolution
    return None


def save_results(success_rates, traces_needed, filename: Path):
    """
    Serialize success-rate curves and traces-needed values to a JSON file.
    """
    data = {
        "success_rates": success_rates,
        "traces_needed": traces_needed,
    }
    filename.parent.mkdir(parents=True, exist_ok=True)
    with open(filename, "w") as f:
        json.dump(data, f, indent=2)


def load_results(filename: Path):
    """
    Load cached success-rate data from JSON.
    """
    with open(filename, "r") as f:
        return json.load(f)


def plot_traces_needed(traces_needed, success_rate_threshold: float):
    """
    Generate a bar chart showing the number of traces needed to reach
    `success_rate_threshold` for each S-box.

    The plot is saved under:
        DOJO_ROOT/sw/x-heep/Graphs/AES_c/AES_cpa_success_rate_bar_chart_...
    """
    plt.figure(figsize=(8, 6))

    keys = list(traces_needed.keys())
    values = list(traces_needed.values())

    # Remove 'sbox_' prefix for plot labels
    labels = [k.replace("sbox_", "") for k in keys]

    bar_width = 0.5
    bars = plt.bar(labels, values, width=bar_width)

    plt.xlabel("S-box")
    plt.ylabel("Number of traces")

    # Add value labels on top of each bar
    for bar in bars:
        height = bar.get_height()
        plt.annotate(
            f"{int(height)}",
            xy=(bar.get_x() + bar.get_width() / 2, height),
            xytext=(0, 1),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=10,
        )

    plt.tight_layout()

    # Format threshold for filename (e.g., 0.9 -> "90", 1.0 -> "100")
    threshold_str = str(int(success_rate_threshold * 100))

    out_file = (
        XHEEP_GRAPHS_DIR
        / f"AES_cpa_success_rate_bar_chart_resolution_{resolution}_thr_{threshold_str}.pdf"
    )
    XHEEP_GRAPHS_DIR.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_file)
    # plt.show()


# ============================================================================
# Main entry point
# ============================================================================

def main():
    global resolution, success_rate_threshold

    # -----------------------------------------------------------------------
    # Parse command-line arguments (minimalistic)
    #   --resolution <N> : override default resolution
    #   --plot-only      : skip CPA and only plot from cached JSON
    # -----------------------------------------------------------------------
    if "--resolution" in sys.argv:
        try:
            idx = sys.argv.index("--resolution")
            resolution = int(sys.argv[idx + 1])
        except Exception:
            print("[ERROR] Invalid resolution argument. Using default.")

    # Cache file where success-rate curves and traces-needed are stored
    cache_file = (
        XHEEP_GRAPHS_DIR
        / f"AES_success_rate_bar_chart_resolution_{resolution}.json"
    )

    # -----------------------------------------------------------------------
    # Plot-only mode: reuse cached results
    # -----------------------------------------------------------------------
    if "--plot-only" in sys.argv:
        print(f"[LOG] Loading cached results and plotting... (resolution={resolution})")
        data = load_results(cache_file)

        traces_needed = {}
        for sbox_id, success_rate in data["success_rates"].items():
            n_traces = find_traces_for_threshold(
                success_rate, success_rate_threshold, resolution
            )
            if n_traces is None:
                print(
                    f"[WARN] S-box {sbox_id}: "
                    f"{int(success_rate_threshold * 100)}% success rate not reached."
                )
                n_traces = 0
            traces_needed[sbox_id] = n_traces

        plot_traces_needed(traces_needed, success_rate_threshold)
        print("[LOG] Plot generated from cached data.")
        return

    # -----------------------------------------------------------------------
    # Full analysis: run CPA for all S-boxes and compute traces needed
    # -----------------------------------------------------------------------
    print(
        f"Analyzing traces for all S-boxes (this might take a while)... "
        f"(resolution={resolution})"
    )
    tic = time.perf_counter()

    # Parallel execution over S-box IDs
    # Limit number of processes to avoid oversubscribing cores
    n_processes = min(len(sbox_ids), cpu_count())
    with Pool(processes=n_processes) as pool:
        results = pool.map(compute_success_rate_for_sbox, sbox_ids)

    # results is a list of (sbox_id, success_rate_list)
    sbox_to_traces = {}
    success_rates = {}

    for sbox_id, success_rate in results:
        n_traces = find_traces_for_threshold(
            success_rate, success_rate_threshold, resolution
        )
        if n_traces is None:
            print(
                f"[WARN] S-box {sbox_id}: "
                f"{int(success_rate_threshold * 100)}% success rate not reached."
            )
            n_traces = 0

        sbox_to_traces[sbox_id] = n_traces
        success_rates[sbox_id] = success_rate

    # Save results to cache
    save_results(success_rates, sbox_to_traces, cache_file)

    # Generate bar chart
    plot_traces_needed(sbox_to_traces, success_rate_threshold)

    toc = time.perf_counter()
    print(
        f"[LOG] Computation completed in {(toc - tic) / 60:0.2f} minutes. "
        f"Results cached to: {cache_file}"
    )


if __name__ == "__main__":
    main()
