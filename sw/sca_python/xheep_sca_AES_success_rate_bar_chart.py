#!/usr/bin/env python3


import time
import matplotlib.pyplot as plt
import chipwhisperer as cw
import chipwhisperer.analyzer as cwa
from analyzer.attack.aes.SBox_leakage_models import AES128SboxResistantLeakageModels
from multiprocessing import Pool, cpu_count
import json
import sys

# List of S-box IDs to test (replace with your actual S-box IDs or names)
sbox_ids = [
    "sbox_rijandael",  # default AES S-Box (aes_sbox)
    "sbox_freyre_1",
    "sbox_freyre_2",
    "sbox_freyre_3",
    "sbox_hussain_6",
    "sbox_ozkaynak_1"
]

# Default resolution - It can be overridden via command-line argument "--resolution"
resolution = 25
success_rate_threshold = 1.0 # Values in range [0.0 - 1.0]*100

key = [ 0x2b, 0x7e, 0x15, 0x16, 0x28, 0xae, 0xd2, 0xa6, 0xab, 0xf7, 0x15, 0x88, 0x09, 0xcf, 0x4f, 0x3c ]

def compute_success_rate_for_sbox(sbox_id):
    success_rate = []

    tested_sbox = sbox_id.replace("sbox_", "")
    project_file = f"../../build/xheep_test/CW305_xheep_AES_{tested_sbox}.cwp"
    try:
        project = cw.open_project(project_file)
    except Exception as e:
        print(f"[WARN] Could not open project file {project_file}: {e}")
        return (sbox_id, success_rate)
    global key
    leak_model = AES128SboxResistantLeakageModels().FirstRound_ModifiedSbox_Output(sbox_id)
    attack = cwa.cpa(project, leak_model)

    def success_rate_callback():
        results = attack.results
        guessed_key = [kguess[0][0] for kguess in results.find_maximums()]
        iteration_success_rate = [1 if k == g else 0 for k, g in zip(key, guessed_key)]
        avg_success_rate = sum(iteration_success_rate) / len(iteration_success_rate)
        success_rate.append(avg_success_rate)

    attack.run(success_rate_callback, resolution)
    project.close()
    return (sbox_id, success_rate)

def find_traces_for_threshold(success_rate, threshold, resolution):
    for i, sr in enumerate(success_rate):
        if sr >= threshold:
            return (i + 1) * resolution
    return None


def save_results(success_rates, traces_needed, filename):
    data = {
        "success_rates": success_rates,
        "traces_needed": traces_needed
    }
    with open(filename, "w") as f:
        json.dump(data, f)

def load_results(filename):
    with open(filename, "r") as f:
        return json.load(f)

def plot_traces_needed(traces_needed, success_rate_threshold):
    plt.figure(figsize=(8, 6))
    keys = list(traces_needed.keys())
    values = list(traces_needed.values())
    # Remove 'sbox_' prefix for plot labels
    labels = [k.replace("sbox_", "") for k in keys]
    bar_width = 0.5  # Make bars thinner (default is 0.8)
    bars = plt.bar(labels, values, color="midnightblue", width=bar_width)
    plt.xlabel("S-box")
    plt.ylabel(f"Number of traces")
    # plt.title(f"Number of traces required to achieve {int(success_rate_threshold*100)}% Success Rate per S-box")
    # Add value labels on top of each bar
    for bar in bars:
        height = bar.get_height()
        plt.annotate(f'{int(height)}',
                     xy=(bar.get_x() + bar.get_width() / 2, height),
                     xytext=(0, 1),  # 1 point vertical offset
                     textcoords="offset points",
                     ha='center', va='bottom', fontsize=10)
    # plt.grid(axis="y")
    plt.tight_layout()
    # Format threshold for filename (e.g., 0.9 -> 90, 1.0 -> 100)
    threshold_str = str(int(success_rate_threshold * 100))
    plt.savefig(f"../x-heep/Graphs/AES_c/AES_cpa_success_rate_bar_chart_resolution_{resolution}_thr_{threshold_str}.pdf")
    # plt.show()

def main():
    global resolution, success_rate_threshold

    # Parse resolution argument
    if "--resolution" in sys.argv:
        try:
            idx = sys.argv.index("--resolution")
            resolution = int(sys.argv[idx + 1])
        except Exception:
            print("[ERROR] Invalid resolution argument. Using default.")

    # Set cache_file name based on resolution
    cache_file = f"../x-heep/Graphs/AES_c/AES_success_rate_bar_chart_resolution_{resolution}.json"

    if "--plot-only" in sys.argv:
        print(f"[LOG] Loading cached results and plotting... (resolution={resolution})")
        data = load_results(cache_file)
        # Recompute traces_needed for the current threshold
        traces_needed = {}
        for sbox_id, success_rate in data["success_rates"].items():
            n_traces = find_traces_for_threshold(success_rate, success_rate_threshold, resolution)
            if n_traces is None:
                print(f"[WARN] S-box {sbox_id}: {int(success_rate_threshold*100)}% success rate not reached.")
                n_traces = 0
            traces_needed[sbox_id] = n_traces
        plot_traces_needed(traces_needed, success_rate_threshold)
        print("[LOG] Plot generated from cached data.")
        return

    print(f"Analyzing traces for all S-boxes (this might take a while)... (resolution={resolution})")
    tic = time.perf_counter()

    # Parallel execution using only sbox IDs
    with Pool(processes=min(len(sbox_ids), 4)) as pool:
        results = pool.map(compute_success_rate_for_sbox, sbox_ids)

    # results is a list of (sbox_id, success_rate)
    sbox_to_traces = {}
    success_rates = {}
    for sbox_id, success_rate in results:
        n_traces = find_traces_for_threshold(success_rate, success_rate_threshold, resolution)
        if n_traces is None:
            print(f"[WARN] S-box {sbox_id}: 90% success rate not reached.")
            n_traces = 0
        sbox_to_traces[sbox_id] = n_traces
        success_rates[sbox_id] = success_rate

    # Save results to cache
    save_results(success_rates, sbox_to_traces, cache_file)

    # Bar chart
    plot_traces_needed(sbox_to_traces, success_rate_threshold)
    toc = time.perf_counter()
    print(f"[LOG] Computation completed in {(toc - tic)/60:0.2f} minutes. Results cached.")

if __name__ == "__main__":
    main()
