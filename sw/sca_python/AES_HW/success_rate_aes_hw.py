#!/usr/bin/env python3
import sys
sys.path.append( '../../ciphers/AES_python' )
sys.path.append( '../../sca_python' )
from CW305_api import CW305Wrapper
from pico_api import PS5000aWrapper
from AES_golden import AES_golden_model
from analyzer.attack.aes.SBox_leakage_models import AES128SboxResistantLeakageModels
from analyzer.attack.aes.key_schedule import key_schedule_rounds
import os
os.system("pip list | grep chipwhisperer")
import chipwhisperer as cw
import chipwhisperer.analyzer as cwa
from chipwhisperer.common.traces import Trace
import time
from tqdm import tqdm
import matplotlib.pyplot as plt
import numpy as np
import json
# Added for multiprocessing support
from multiprocessing import Pool

"""
Available S-boxes:
    sbox_rijandael (default AES S-Box) (aes_sbox)
    sbox_freyre_1
    sbox_freyre_2
    sbox_freyre_3
    sbox_hussain_6
    sbox_ozkaynak_1
    sbox_azam_1
    sbox_azam_2
    sbox_azam_3
"""

###################### CONFIGURATION ######################

# ---------------------------------------------------------------------------
# This script evaluates the success rate of a CPA attack against a selected
# AES S-box implementation on CW305.
# ---------------------------------------------------------------------------

# Select the S-box implementation to test
tested_sbox = "sbox_freyre_1"          # e.g. "sbox_rijandael", "sbox_freyre_1", ...
sbox_id = tested_sbox.replace("sbox_", "")

# Enable/disable trace acquisition
trace_acquisition = True

# Path to the pre-generated FPGA bitstream for the selected S-box
bitstream = f"../../../hw/fpga/bitstream/aes/aes_single_round/cw305_top_{sbox_id}_lut.bit"

# ChipWhisperer project file used to store/load traces and SCA metadata
project_file = f"../../notebook/examples/aes/traceset/AES_{sbox_id}/{sbox_id}.cwp"

# Cache configuration for success-rate curves
save_SR_to_cache = True                # Save success-rate curve to JSON
save_SR_plot    = True                 # Save success-rate plot as PDF/PNG
resolution      = 25                   # Number of traces added at each evaluation step

# JSON cache file for success-rate results (one file per sbox_id / resolution)
cache_file = f"../../notebook/examples/aes/cache/AES_{sbox_id}_success_rate_{resolution}.json"

# Directory for plots
plot_dir = "../../notebook/examples/aes/Graphs"

# AES key used during trace acquisition
key = [
    0x2b, 0x7e, 0x15, 0x16,
    0x28, 0xae, 0xd2, 0xa6,
    0xab, 0xf7, 0x15, 0x88,
    0x09, 0xcf, 0x4f, 0x3c,
]

# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def save_results(success_rates, resolution, filename):
    """Save success-rate curve and configuration to a JSON cache file."""
    data = {
        "success_rates": list(success_rates),
        "resolution": int(resolution),
    }
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    with open(filename, "w") as f:
        json.dump(data, f)

def load_results(filename):
    """Load success-rate curve and configuration from a JSON cache file."""
    with open(filename, "r") as f:
        return json.load(f)

# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------
def to_hex_str(x):
    """Format a bytes-like / iterable of ints as spaced lowercase hex."""
    return " ".join(f"{b:02x}" for b in x)

###################### PRINT CONFIGURATION ######################
print("\n[CONFIG]")
print("  tested_sbox  :", tested_sbox)
print("  bitstream    :", bitstream)
print("  project_file :", project_file)
print("  cache_file   :", cache_file)
print("  trace_acq    :", trace_acquisition)
print("  resolution   :", resolution)
print("  save_SR_plot :", save_SR_plot, "\n")

###################### ONLINE PHASE ######################
# In this phase we:
#   1. Initialize the Picoscope (oscilloscope) for power measurements.
#   2. Initialize the CW305 FPGA board and program it with the selected AES
#      single-round bitstream.
#   3. Capture 'n_trc' power traces while encrypting random plaintexts
#      under a fixed key, and store the traces into a ChipWhisperer project.

# Number of traces to capture
n_trc = 5000

if trace_acquisition:
    print(f"[ONLINE] Trace acquisition enabled. Target traces: {n_trc}")
    print(f"[ONLINE] Using project file: {project_file}")
    print(f"[ONLINE] Programming bitstream: {bitstream}")

    # -----------------------------------------------------------------------
    # Initialize measurement instruments
    # -----------------------------------------------------------------------
    try:
        # Initialize Picoscope
        ps = PS5000aWrapper()
        ps.scope_setup()
        print("\n[ONLINE] Picoscope initialized.")
        print(f"[ONLINE] Picoscope info: {ps.get_unitInfo()}")
    except Exception as e:
        print(f"[ERROR] Failed to initialize Picoscope: {e}")
        exit(1)

    try:
        # Initialize CW305 and program FPGA
        cw305 = CW305Wrapper(ps, bitstream)
        print("[ONLINE] CW305 initialized and FPGA programmed.")
    except Exception as e:
        print(f"[ERROR] Failed to initialize CW305: {e}")
        ps.dis()
        exit(1)

    # -----------------------------------------------------------------------
    # Key / plaintext setup
    # -----------------------------------------------------------------------
    # Initialize key/plaintext generator
    ktp = cw.ktp.Basic()
    key, pt = ktp.next()

    # Software AES model for sanity checks
    cipher = AES_golden_model()

    # Key as hex string, used by the software AES model
    formatted_key = "".join(format(el, "02x") for el in key)
    print(f"[ONLINE] Fixed key used for acquisition: {[hex(subkey) for subkey in key]}")

    # Program the key into the CW305 target
    cw305.set_key(key)

    # Dummy capture call due to CW305 AC-coupling quirk
    cw305.capture_trace(pt)

    # -----------------------------------------------------------------------
    # Capture loop
    # -----------------------------------------------------------------------
    try:
        print("[ONLINE] Starting trace capture...")
        # Ensure the directory for the project file exists
        project_dir = os.path.dirname(project_file)
        os.makedirs(project_dir, exist_ok=True)
        project = cw.create_project(project_file, overwrite=True)

        for i in tqdm(range(n_trc), desc="Capturing traces"):
            # Capture a single trace and ciphertext
            ct, trace = cw305.capture_trace(pt)

            # Sanity-check: verify ciphertext against the software AES model
            formatted_pt = (format(el, "02x") for el in pt)
            text = [int(subbyte, 16) for subbyte in formatted_pt]
            expected_ct = cipher.encrypt(formatted_key, text, tested_sbox)
            if list(ct) != list(expected_ct):
                got_hex = to_hex_str(ct)
                exp_hex = to_hex_str(expected_ct)
                raise RuntimeError(
                    "Incorrect encryption result!\n"
                    f"Got : {got_hex}\n"
                    f"Exp : {exp_hex}\n"
                )

            # Store only the region of interest around the last round
            trace_struct = Trace(trace[400:600], pt, ct, key)
            project.traces.append(trace_struct)

            # Generate next plaintext for the next capture
            if i < n_trc - 1:
                _, pt = ktp.next()

        project.save()
        print(f"[ONLINE] Capture completed. Traces saved to: {project_file}")

    except Exception as e:
        print(f"[ERROR] Capture aborted: {e}")
        raise

    # -----------------------------------------------------------------------
    # Cleanup
    # -----------------------------------------------------------------------
    finally:
        # Close project if it was created
        if project is not None:
            try:
                project.close()
            except Exception as e:
                print(f"[WARN] Could not close project cleanly: {e}")

        # Always try to disconnect hardware
        try:
            cw305.dis()
        except Exception as e:
            print(f"[WARN] Could not disconnect CW305: {e}")

        try:
            ps.dis()
        except Exception as e:
            print(f"[WARN] Could not disconnect Picoscope: {e}")

        print("[ONLINE] Cleanup completed (project closed, CW305 and Picoscope disconnected).")
else:
    print(f"[ONLINE] Trace acquisition disabled. Existing project will be used: {project_file}")


####################### OFFLINE PHASE #######################

# In this phase we evaluate the success rate of a CPA attack using an increasing
# number of traces.
#
# Concept:
#   1. The total traces are conceptually divided into chunks (e.g., 25, 50, 75, ... traces),
#      controlled by the 'resolution' parameter.
#   2. After each chunk is processed, ChipWhisperer Analyzer performs a CPA attack
#      and we extract the current best guess for each key byte.
#   3. For each byte i we set:
#         SR[i] = 1 if guessed_key_byte[i] == correct_key_byte[i]
#               = 0 otherwise
#   4. The global success rate at that step is the average over all key bytes:
#         SR_global = (SR[0] + SR[1] + ... + SR[15]) / 16
#      (for AES-128, there are 16 key bytes).
#
# ChipWhisperer Analyzer supports a callback function that is invoked
# periodically as more traces are processed. We use this callback to:
#   - read the current best key guess from the CPA results
#   - compare it with the true last-round key
#   - update the success_rate curve.
#
# The 'resolution' argument of 'attack.run(callback, resolution)' controls how
# often the callback is called (e.g., every 25 traces), effectively acting as
# the step size for our success-rate curve.

print(f"[OFFLINE] Computing success rate for S-box '{tested_sbox}' (resolution = {resolution} traces)...")

tic = time.perf_counter()

# List of global success-rate values, one per callback call
success_rate = []

# Compute the AES last-round key for comparison against CPA guesses
key_last_round = key_schedule_rounds(key, 0, 10, tested_sbox)

def success_rate_callback():
    """Callback invoked by ChipWhisperer Analyzer after each batch of traces.

    It reads the current key guesses, compares them with the true last-round
    key, and appends the average success rate over all key bytes to 'success_rate'.
    """
    # Get the CPA results (guessed key bytes).
    # results.find_maximums() returns a list of subkey data:
    #   - results[sk] is the list of guesses for subkey 'sk', ordered by correlation strength
    #   - results[sk][0] is the best guess for subkey 'sk'
    #   - results[sk][0][0] is the guessed key byte value
    results = attack.results
    guessed_key = [kguess[0][0] for kguess in results.find_maximums()]

    iteration_success_rate = []
    # Compare the guessed key bytes with the correct key bytes
    for key_byte, guessed_key_byte in zip(key_last_round, guessed_key):
        # Per-byte success: 1 if the guess is correct, 0 otherwise
        success_rate_i = 1 if key_byte == guessed_key_byte else 0
        iteration_success_rate.append(success_rate_i)

    # Average success over all key bytes for this iteration
    avg_success_rate = sum(iteration_success_rate) / len(iteration_success_rate)
    success_rate.append(avg_success_rate)

# ---------------------------------------------------------------------------
# Run CPA attack
# ---------------------------------------------------------------------------

try:
    project = cw.open_project(project_file)
except Exception as e:
    print(f"[ERROR] Could not open project file '{project_file}': {e}")
    exit(1)

# Use Hamming Weight leakage model of last round for the CPA attack
leak_model = AES128SboxResistantLeakageModels().LastroundStateDiff_ModifiedSbox(tested_sbox)

attack = cwa.cpa(project, leak_model)

print("[OFFLINE] Starting Success Rate computation via ChipWhisperer Analyzer...")
attack.run(success_rate_callback, resolution)
project.close()
# Drop reference so __del__ runs now, not at interpreter shutdown
attack = None

# ---------------------------------------------------------------------------
# Cache success-rate results
# ---------------------------------------------------------------------------

if save_SR_to_cache:
    save_results(success_rate, resolution, cache_file)
    print(f"[OFFLINE] Success-rate curve cached to: {cache_file}")

# ---------------------------------------------------------------------------
# Plot success-rate curve
# ---------------------------------------------------------------------------

print("[OFFLINE] Generating success-rate plot...")

xrange = [i * resolution for i in range(len(success_rate))]

plt.figure(figsize=(10, 5))
plt.plot(xrange, success_rate, color="red")
plt.xlabel("Number of traces")
plt.ylabel("Success rate")
plt.title(f"AES CPA Success Rate ({sbox_id})")
plt.grid(True)

if save_SR_plot:
    os.makedirs(plot_dir, exist_ok=True)
    out_path = os.path.join(plot_dir, f"AES_cpa_success_rate_{sbox_id}.pdf")
    plt.savefig(out_path, dpi=300)
    print(f"[OFFLINE] Success-rate plot saved to: {out_path}")

toc = time.perf_counter()
print(f"[LOG] OFFLINE PHASE: completed in {(toc - tic) / 60:0.2f} minutes.")
exit(0)