#!/usr/bin/env python3
# =====================================================================
# ASCON SNR ranking (all bits, SW traces)
#
# This script computes the Signal-to-Noise Ratio (SNR) for *all* 64 bits of
# both ASCON state words S0 and S1 (mapped here as "x0" and "x1") at the end
# of the first permutation round, using the HW of the target bit as leakage model.
#
# For each (register, bit) pair it computes an SNR trace over time and stores
# the *peak SNR* (max over samples). Results are sorted in descending order of SNR
# and saved to an HDF5 cache file (SNR_OUT_FILE):
#   /ranked/register   : UTF-8 strings ("x0" or "x1")
#   /ranked/bit        : uint16 bit index (0..63)
#   /ranked/snr        : float64 peak SNR value
#
# Configuration:
#   - sbox_type selects the traceset file name.
#   - n_trc selects how many traces are used (clipped to file length).
#   - save_snr_all_bits toggles writing the ranked arrays to disk.
# =====================================================================

import sys
from pathlib import Path

import numpy as np
from tqdm import tqdm
import h5py

# ---------------------------------------------------------------------------
# Script configuration
# ---------------------------------------------------------------------------
# Supported S-box types:
#   lut_ascon, lut_bilgin, lut_allouzi, lut_lu_4, lut_lu_5, lut_lu_6, lut_lu_7
sbox_type = "lut_lu_7"
# Number of traces in the traceset (will use min(n_trc, traces_in_file))
n_trc = 50_000
# Output control
save_snr_all_bits = True
# Flow flags
debug = True

# ---------------------------------------------------------------------------
# Helper: find repo root
# ---------------------------------------------------------------------------
def find_project_root(start: Path, markers=("fusesoc.conf", ".dojo_root")) -> Path:
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

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ASCON_PY_DIR = DOJO_ROOT / "sw" / "ciphers" / "ASCON_init_python"
SCA_DIR      = DOJO_ROOT / "sw" / "sca_scripts"

BASE_CACHE_DIR = DOJO_ROOT / "sw" / "sca_scripts" / "ASCON" / "sw" / "cache"
TRACESET_DIR   = DOJO_ROOT / "sw" / "traceset" / "ASCON" / "sw"

TRACESET_FILE  = TRACESET_DIR / f"ascon_opt32_{sbox_type}_{150_000 // 1000}k.h5"
CACHE_DIR      = BASE_CACHE_DIR / sbox_type
SNR_OUT_FILE   = CACHE_DIR / "snr_ranked.h5"

BASE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
TRACESET_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Make local modules importable
sys.path.insert(0, str(ASCON_PY_DIR))
sys.path.insert(0, str(SCA_DIR))

from analyzer.attack.ascon.xheep_ascon_cpa.ascon_first_round import ascon_first_round

# ---------------------------------------------------------------------------
# Print configuration
# ---------------------------------------------------------------------------
print("\n================= CONFIGURATION =================")
print(f"  Script scope           : SNR computation of target bits for ASCON SW with generic S-box")
print(f"DOJO_ROOT                : {DOJO_ROOT}")
print()
print("Target")
print(f"  Cipher                 : ASCON")
print(f"  S-box implementation   : {sbox_type}")
print(f"  Scope                  : SNR ranking for all bits (x0 and x1)")
print()
print("Paths")
print(f"  Traceset file          : {TRACESET_FILE}")
print(f"  SNR write to           : {SNR_OUT_FILE}")
print()
print("SNR configuration")
print(f" Nr. of analyzed traces  : {n_trc}")
print("=================================================\n")

# ---------------------------------------------------------------------------
# Load traces / nonces
# ---------------------------------------------------------------------------
try:
    with h5py.File(TRACESET_FILE, "r") as f_read:
        if "traces" not in f_read or "nonces" not in f_read:
            raise KeyError("HDF5 file is missing required datasets 'traces' and/or 'nonces'.")

        traces_ds = f_read["traces"]
        nonces_ds = f_read["nonces"]

        total_traces = int(traces_ds.shape[0])
        n_samples    = int(traces_ds.shape[1])

        sampling_interval = f_read.attrs.get("sampling_interval", None)
        key_hex           = f_read.attrs.get("key_hex", None)
        iv_hex            = f_read.attrs.get("iv_hex", None)

        n_used = min(n_trc, total_traces)
        traces = traces_ds[:n_used]
        nonces = nonces_ds[:n_used]

    if traces.shape[0] != nonces.shape[0]:
        raise ValueError(
            f"Number of traces ({traces.shape[0]}) and nonces ({nonces.shape[0]}) do not match."
        )

    if n_trc != total_traces:
        print(f"[WARN] Wanted n_trc={n_trc} differs from dataset length={total_traces}")
    n_trc = n_used

    print(f"[INFO] Loaded {n_trc} traces from {TRACESET_FILE}")
    print(f"[INFO] Samples per trace      : {n_samples}")
    print(f"[INFO] Sampling interval      : {sampling_interval}")

    if key_hex is not None:
        print(f"[INFO] Key                    : 0x{key_hex}")
    else:
        print("[WARN] Key hex attribute 'key_hex' not found in HDF5 file.")
    if iv_hex is not None:
        print(f"[INFO] IV                     : 0x{iv_hex}")
    else:
        print("[WARN] IV hex attribute 'iv_hex' not found in HDF5 file.")

except FileNotFoundError:
    raise SystemExit(
        f"[ERROR] Traces file {TRACESET_FILE} not found. "
        "Please run the trace acquisition phase first."
    )
except Exception as e:
    raise SystemExit(f"[ERROR] Could not read traces file {TRACESET_FILE}: {e}")

# ---------------------------------------------------------------------------
# Utility: SNR trace for binary labels
# ---------------------------------------------------------------------------
def _snr_trace_binary(trace_set: np.ndarray, labels_set: np.ndarray) -> np.ndarray:
    """
    Compute SNR trace for binary labels (0/1):
      SNR = Var( class_means ) / Var( within_class_noise )

    trace_set  : (n_traces, n_samples)
    labels_set : (n_traces,) values in {0,1}
    returns    : (n_samples,)
    """
    labels_set = labels_set.astype(np.uint8)
    idx0 = (labels_set == 0)
    idx1 = ~idx0

    n0 = int(np.sum(idx0))
    n1 = int(np.sum(idx1))
    if n0 == 0 or n1 == 0:
        return np.zeros(trace_set.shape[1], dtype=np.float64)

    m0 = np.mean(trace_set[idx0], axis=0)
    m1 = np.mean(trace_set[idx1], axis=0)

    v0 = np.var(trace_set[idx0], axis=0, ddof=0)
    v1 = np.var(trace_set[idx1], axis=0, ddof=0)

    # Weighted variance of means + weighted mean of variances
    w0 = n0 / (n0 + n1)
    w1 = n1 / (n0 + n1)

    mean_of_means = w0 * m0 + w1 * m1
    var_of_means  = w0 * (m0 - mean_of_means) ** 2 + w1 * (m1 - mean_of_means) ** 2
    mean_of_vars  = w0 * v0 + w1 * v1

    eps = 1e-12
    return var_of_means / (mean_of_vars + eps)

# ---------------------------------------------------------------------------
# Key setup (endianness match with C)
# ---------------------------------------------------------------------------
key_bytes    = [key_hex[i:i + 2] for i in range(0, len(key_hex), 2)]
key_reversed = "".join(key_bytes[::-1])
key_int      = int(key_reversed, 16)

# ---------------------------------------------------------------------------
# Compute peak SNR for all bits of x0 and x1, then rank
# ---------------------------------------------------------------------------
rank_regs = []
rank_bits = []
rank_snr  = []

for bit_i in tqdm(range(64), desc="Computing peak SNR for all bits (x0,x1)"):
    labels_x0 = np.empty(n_trc, dtype=np.uint8)
    labels_x1 = np.empty(n_trc, dtype=np.uint8)

    for i in range(n_trc):
        nonce = (int(nonces[i][0]) << 64) | int(nonces[i][1])
        S = ascon_first_round(key_int, nonce, sbox_type)

        labels_x0[i] = (S[0] >> bit_i) & 0x01
        labels_x1[i] = (S[1] >> bit_i) & 0x01

    snr_x0 = _snr_trace_binary(traces, labels_x0)
    snr_x1 = _snr_trace_binary(traces, labels_x1)

    max_snr_x0 = float(np.max(snr_x0))
    max_snr_x1 = float(np.max(snr_x1))

    rank_regs.append("x0"); rank_bits.append(bit_i); rank_snr.append(max_snr_x0)
    rank_regs.append("x1"); rank_bits.append(bit_i); rank_snr.append(max_snr_x1)

    if debug:
        print(f"[DBG] bit {bit_i:2d} -> x0 SNR_max={max_snr_x0:.6g}, x1 SNR_max={max_snr_x1:.6g}")

rank_regs = np.array(rank_regs, dtype=h5py.string_dtype(encoding="utf-8"))
rank_bits = np.array(rank_bits, dtype=np.uint16)
rank_snr  = np.array(rank_snr,  dtype=np.float64)

order = np.argsort(rank_snr)[::-1]
rank_regs = rank_regs[order]
rank_bits = rank_bits[order]
rank_snr  = rank_snr[order]

if debug:
    print("\n[DBG] Top 10 ranked (reg, bit, peakSNR):")
    for k in range(min(10, len(rank_snr))):
        print(f"  [{rank_regs[k]}, {int(rank_bits[k])}, {rank_snr[k]:.6g}]")

# ---------------------------------------------------------------------------
# Save ranked results to cache file
# ---------------------------------------------------------------------------
if save_snr_all_bits:
    with h5py.File(SNR_OUT_FILE, "w") as f:
        g = f.create_group("ranked")
        g.create_dataset("register", data=rank_regs)
        g.create_dataset("bit",      data=rank_bits)
        g.create_dataset("snr",      data=rank_snr)

    print(f"\n[INFO] Saved ranked SNR results to: {SNR_OUT_FILE}")
else:
    print("\n[INFO] save_snr_all_bits=False, not writing output.")
