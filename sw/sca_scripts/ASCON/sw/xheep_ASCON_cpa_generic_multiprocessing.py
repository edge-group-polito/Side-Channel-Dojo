#!/usr/bin/env python3
"""
Loads traces from HDF5, prints key/IV/nonce info, and runs the
generic leakage model once on a chosen (state, bit).


"""

import sys
import os
import time
from pathlib import Path
import matplotlib.pyplot as plt  # kept in case you extend the script
import numpy as np
from tqdm import tqdm
import multiprocessing as mp
from multiprocessing import shared_memory
import queue
import h5py

# ---------------------------------------------------------------------------
# Basic configuration
# ---------------------------------------------------------------------------
# Supported S-box types:
#   lut_ascon, lut_bilgin, lut_allouzi, lut_lu_4, lut_lu_5, lut_lu_6, lut_lu_7
sbox_type   = "lut_lu_7"   
n_trc       = 150_000        # total number of traces in the traceset
# Choose processes count 
n_proc = max(1, min(8, mp.cpu_count()))
# Flow flags
verbose                  = True   # Verbose output during key recovery
# CPA / analysis cache control
load_attack_results      = False  # Load CPA cache if available
save_attack_results      = True   # Save CPA results to cache after the run
# Plot control
key_rank_plot            = True   # Plot PGE vs traces
traces_correlation_plot  = True   # Plot correlation vs traces
# Output control
save_plots               = True   # Save plots to disk
save_results             = True   # Save analysis results (JSON, etc.) to disk

# ---------------------------------------------------------------------------
# Project root detection and path setup
# ---------------------------------------------------------------------------

def find_project_root(start: Path, markers=("fusesoc.conf", ".dojo_root")) -> Path:
    """
    Walk upwards from 'start' until a directory containing one of 'markers'
    is found. This directory is assumed to be the Side-Channel-Dojo root.
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


# Script directory (works both when installed and when run from source)
try:
    SCRIPT_DIR = Path(__file__).resolve().parent
except NameError:
    # Fallback for interactive runs (should not happen in script form)
    SCRIPT_DIR = Path.cwd()

DOJO_ROOT = find_project_root(SCRIPT_DIR)

# ---------------------------------------------------------------------------
# Global paths (independent of S-Box / run configuration)
# ---------------------------------------------------------------------------
ASCON_PY_DIR = DOJO_ROOT / "sw" / "ciphers" / "ASCON_init_python"
SCA_DIR      = DOJO_ROOT / "sw" / "sca_scripts"
# Base dirs for ASCON SW SCA
BASE_PLOT_DIR  = DOJO_ROOT / "sw" / "sca_scripts" / "ASCON" / "sw" / "plot"
BASE_CACHE_DIR = DOJO_ROOT / "sw" / "sca_scripts" / "ASCON" / "sw" / "cache"
# Traceset (HDF5) for ASCON SW
TRACESET_DIR  = DOJO_ROOT / "sw" / "traceset" / "ASCON" / "sw"

# Import local modules
sys.path.insert(0, str(ASCON_PY_DIR))
sys.path.insert(0, str(SCA_DIR))

from analyzer.attack.ascon.xheep_ascon_cpa.ascon_generic_leakage_model import ascon_generic_leakage_model
from analyzer.attack.ascon.xheep_ascon_cpa.ascon_cpa import ascon_cpa_fast

# -----------------------------------------------------------------------------
# Multiprocessing shared-memory bindings
# -----------------------------------------------------------------------------
# These globals are populated once per worker process by _mp_init_worker().
# Workers then reuse them for every task without copying traces/nonces.
_MP_TRACES = None
_MP_NONCES = None
_MP_TRACES_SHM = None
_MP_NONCES_SHM = None
_MP_IV_INT = None
_MP_SBOX_TYPE = None
_MP_N_TRC = None


# -----------------------------------------------------------------------------
# target_to_k_idx() : compute which key bits are recovered. 
# -----------------------------------------------------------------------------
def target_to_k_idx(attacked_state_reg: str, attacked_bit: int) -> np.ndarray:
    """
    Cheap mapping: given (state_reg, bit) returns the key-bit indices affected by this target.
    Must match exactly the worker mapping.
    """
    j = int(attacked_bit) % 64
    if attacked_state_reg == "x0":
        return np.array([j, (j + 19) % 64, (j + 28) % 64], dtype=int)
    elif attacked_state_reg == "x1":
        return np.array([j, (j + 61) % 64, (j + 39) % 64], dtype=int)
    elif attacked_state_reg == "x2":
        return np.array([j, (j + 1) % 64, (j + 6) % 64], dtype=int)
    elif attacked_state_reg == "x3":
        return np.array([j, (j + 10) % 64, (j + 17) % 64], dtype=int)
    elif attacked_state_reg == "x4":
        return np.array([j, (j + 7) % 64, (j + 41) % 64], dtype=int)
    else:
        raise ValueError(f"Invalid attacked_state_register: {attacked_state_reg}")


def _mp_init_worker(
    traces_shm_name,
    nonces_shm_name,
    traces_shape,
    nonces_shape,
    traces_dtype,
    nonces_dtype,
    iv_int,
    sbox_type,
    n_trc,
    k0_rec_shm_name,
    k1_rec_shm_name,
    kxor_rec_shm_name,
):
    global _MP_TRACES_SHM, _MP_NONCES_SHM, _MP_TRACES, _MP_NONCES
    global _MP_K0_REC_SHM, _MP_K1_REC_SHM, _MP_KXOR_REC_SHM
    global _MP_K0_REC, _MP_K1_REC, _MP_KXOR_REC
    global _MP_IV_INT, _MP_SBOX_TYPE, _MP_N_TRC

    _MP_TRACES_SHM = shared_memory.SharedMemory(name=traces_shm_name)
    _MP_NONCES_SHM = shared_memory.SharedMemory(name=nonces_shm_name)
    _MP_TRACES = np.ndarray(traces_shape, dtype=np.dtype(traces_dtype), buffer=_MP_TRACES_SHM.buf, order="C")
    _MP_NONCES = np.ndarray(nonces_shape, dtype=np.dtype(nonces_dtype), buffer=_MP_NONCES_SHM.buf, order="C")

    _MP_K0_REC_SHM  = shared_memory.SharedMemory(name=k0_rec_shm_name)
    _MP_K1_REC_SHM  = shared_memory.SharedMemory(name=k1_rec_shm_name)
    _MP_KXOR_REC_SHM = shared_memory.SharedMemory(name=kxor_rec_shm_name)

    _MP_K0_REC   = np.ndarray((64,), dtype=np.uint8, buffer=_MP_K0_REC_SHM.buf)
    _MP_K1_REC   = np.ndarray((64,), dtype=np.uint8, buffer=_MP_K1_REC_SHM.buf)
    _MP_KXOR_REC = np.ndarray((64,), dtype=np.uint8, buffer=_MP_KXOR_REC_SHM.buf)

    _MP_IV_INT = iv_int
    _MP_SBOX_TYPE = sbox_type
    _MP_N_TRC = n_trc

# -----------------------------------------------------------------------------
# _mp_worker_attack_target(): per-target CPA done in parallel (no shared writes)
# -----------------------------------------------------------------------------
def _mp_worker_attack_target(task):
    """
    Worker task.
    - Builds H (N x 64) for ONE attacked target (state_register[bit]).
    - Groups hypotheses by leakage pattern up to complement.
    - Runs CPA on grouped hypotheses and returns the winning hypothesis group.

    The worker returns ONLY data; the calling process (main) performs all writes to
    k0/k1/xor containers in the original order.
    """
    order_idx, attacked_state_reg, attacked_bit = task

    # --- 1) compute k_idx mapping for this attacked target ---
    k_idx = target_to_k_idx(attacked_state_reg, attacked_bit)

    # --- early skip based on current recovered flags ---
    useful = False
    for idx in k_idx:
        idx = int(idx)
        idx_done = (_MP_K0_REC[idx] and _MP_K1_REC[idx]) or (_MP_KXOR_REC[idx] and (_MP_K0_REC[idx] or _MP_K1_REC[idx]))
        if not idx_done:
            useful = True
            break

    if not useful:
        return {
            "order_idx": order_idx,
            "attacked_state_reg": attacked_state_reg,
            "attacked_bit": int(attacked_bit),
            "k_idx": k_idx,
            "skipped": True,
        }

    # Build H: (N, 64) for this (state, bit)
    H = np.empty((_MP_N_TRC, 64), dtype=np.uint8)
    for i in range(_MP_N_TRC):
        nonce_lsb = int(_MP_NONCES[i, 0])
        nonce_msb = int(_MP_NONCES[i, 1])

        # Uses global imports: ascon_generic_leakage_model()
        H[i] = ascon_generic_leakage_model(
            _MP_IV_INT,
            nonce_msb,
            nonce_lsb,
            attacked_state_reg,
            int(attacked_bit),
            _MP_SBOX_TYPE,
        )

    # Group hypotheses by leakage pattern up to complement
    _, n_hyp = H.shape
    canonical_to_group = {}
    key_hyp_groups = []
    group_cols = []

    for k_guess in range(n_hyp):
        col = H[:, k_guess].astype(np.uint8)
        compl = 1 - col

        col_b = col.tobytes()
        compl_b = compl.tobytes()
        canon_b = col_b if col_b <= compl_b else compl_b

        if canon_b in canonical_to_group:
            g = canonical_to_group[canon_b]
            key_hyp_groups[g].append(k_guess)
        else:
            g = len(key_hyp_groups)
            canonical_to_group[canon_b] = g
            key_hyp_groups.append([k_guess])
            group_cols.append(col)

    H_group = np.column_stack(group_cols)           # (N, num_groups)

    R_group = ascon_cpa_fast(_MP_TRACES[:_MP_N_TRC], H_group)  # (num_groups, n_samples)
    corr_group = np.max(np.abs(R_group), axis=1)          # (num_groups,)

    best_group_idx = int(np.argmax(corr_group))
    best_key_group = key_hyp_groups[best_group_idx]

    return {
        "order_idx": order_idx,
        "attacked_state_reg": attacked_state_reg,
        "attacked_bit": int(attacked_bit),
        "k_idx": k_idx,
        "best_key_group": best_key_group,
        "skipped" : False,
        "num_groups" : H_group.shape[1],
        "best_group_idx" : best_group_idx, 
    }

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _yn(flag: bool) -> str:
    """Return 'yes' or 'no' for a boolean flag."""
    return "yes" if flag else "no"

def print_key_bits(label: str, bits: np.ndarray) -> None:
    assert bits.shape[0] == 64
    def _print_block(hi: int, lo: int) -> None:
        idxs = list(range(hi, lo - 1, -1))
        # Build strings with fixed-width tokens
        idx_line = "idx: " + " ".join(f"{i:2d}" for i in idxs)
        val_line = "val: " + " ".join(f"{int(bits[i]):2d}" for i in idxs)  # width-2 too
        # Insert byte separators (every 8 bits) for readability
        # (spaces already included by join, so we rebuild with separators)
        def _with_seps(tokens):
            out = []
            for j, t in enumerate(tokens):
                out.append(t)
                if (j + 1) % 8 == 0 and (j + 1) != len(tokens):
                    out.append("|")
            return " ".join(out)
        idx_tokens = [f"{i:2d}" for i in idxs]
        val_tokens = [f"{int(bits[i]):2d}" for i in idxs]
        idx_line = "idx: " + _with_seps(idx_tokens)
        val_line = "val: " + _with_seps(val_tokens)
        print(idx_line)
        print(val_line)
    print(f"\n[INFO] {label} bits (bit63 = LSB ... bit0 = MSB)")
    print("      Byte separators every 8 bits (|)\n")
    _print_block(63, 32)
    print("-" * 106)
    _print_block(31, 0)

def _idx_done(idx: int, k0_rec, k1_rec, k0_xor_k1_rec) -> bool:
    return (k0_rec[idx] and k1_rec[idx]) or (k0_xor_k1_rec[idx] and (k0_rec[idx] or k1_rec[idx]))

def _target_is_useful(k_idx: np.ndarray, k0_rec, k1_rec, k0_xor_k1_rec) -> bool:
    for idx in k_idx:
        if not _idx_done(int(idx), k0_rec, k1_rec, k0_xor_k1_rec):
            return True
    return False

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:

    TRACESET_FILE = TRACESET_DIR / f"ascon_opt32_{sbox_type}_{n_trc // 1000}k.h5"

    # Per-S-box dirs / files
    PLOT_DIR        = BASE_PLOT_DIR / sbox_type
    CACHE_DIR       = BASE_CACHE_DIR / sbox_type
    SNR_FILE    = CACHE_DIR / "snr_ranked.h5"
    CPA_CACHE_FILE  = CACHE_DIR / f"CPA_results_{sbox_type}.json"

    # Ensure directories exist
    BASE_PLOT_DIR.mkdir(parents=True, exist_ok=True)
    BASE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    PLOT_DIR.mkdir(parents=True, exist_ok=True)
    TRACESET_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    CPA_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)

    # -----------------------------------------------------------------------
    # Configuration printout
    # -----------------------------------------------------------------------
    print("\n================= CONFIGURATION =================")
    print(f"  Script scope              : Multiprocess CPA attack to ASCON SW with generic S-box")
    print(f"DOJO_ROOT           : {DOJO_ROOT}")
    print()
    print("Target")
    print(f"  S-box used                : {sbox_type}")
    print(f"  Number of used traces     : {n_trc:,}")
    print(f"  Number of process         : {n_proc}")
    print()
    print("Paths")
    print(f"  Traceset file             : {TRACESET_FILE}")
    print(f"  SNR file of attacked bits : {SNR_FILE}")
    print(f"  Plot dir                  : {PLOT_DIR}")
    print(f"  CPA cache file            : {CPA_CACHE_FILE}")
    print()
    print("Analysis Configuration")
    print(f"  Save plots                : {_yn(save_plots)}")
    print(f"  Save results              : {_yn(save_results)}")
    print(f"  Load CPA results (cache)  : {_yn(load_attack_results)}")
    print(f"  Save CPA results (cache)  : {_yn(save_attack_results)}")
    print()
    print(f"  Key rank plot             : {_yn(key_rank_plot)}")
    print(f"  Correlation plot          : {_yn(traces_correlation_plot)}")
    print("=================================================\n")

    # -----------------------------------------------------------------------
    # Load traces & metadata
    # -----------------------------------------------------------------------
    try:
        with h5py.File(TRACESET_FILE, "r") as f_read_traces:
            # Basic sanity: check that required datasets exist
            if "traces" not in f_read_traces or "nonces" not in f_read_traces:
                raise KeyError(
                    "HDF5 file is missing required datasets 'traces' and/or 'nonces'."
                )

            traces_ds = f_read_traces["traces"]
            nonces_ds = f_read_traces["nonces"]

            total_traces = traces_ds.shape[0]
            n_samples    = traces_ds.shape[1]

            # Load metadata attributes (if present)
            sampling_interval = f_read_traces.attrs.get("sampling_interval", None)
            n_samples         = f_read_traces.attrs.get("n_samples", n_samples)
            key_hex           = f_read_traces.attrs.get("key_hex", None)
            iv_hex            = f_read_traces.attrs.get("iv_hex", None)

            # Use at most n_trc traces, but do not exceed what's in the file
            n_used = min(n_trc, total_traces)

            # Use slicing so data are actually loaded into RAM
            traces = traces_ds[:n_used]
            nonces = nonces_ds[:n_used]

        # Sanity check: traces and nonces should have the same number of rows
        if traces.shape[0] != nonces.shape[0]:
            raise ValueError(
                f"Number of traces ({traces.shape[0]}) and nonces ({nonces.shape[0]}) "
                "do not match. Check the traces file."
            )

        # Optional sanity checks vs metadata
        if n_trc != total_traces:
            print(
                f"[WARN] Wanted n_trc={n_trc} "
                f"differs from dataset length={total_traces}"
            )
        
        # Rebuild the first nonce in big-endian hex (undo byte reversal)
        nonce_msb = int(nonces[0, 0])  # 0x0F0E0D0C0B0A0908
        nonce_lsb = int(nonces[0, 1])  # 0x0706050403020100
        nonce_stored_int = (nonce_msb << 64) | nonce_lsb
        nonce_original_bytes = nonce_stored_int.to_bytes(16, byteorder="big")[::-1]
        nonce_original_hex = nonce_original_bytes.hex().upper()

        print(f"[INFO] Loaded {traces.shape[0]} traces from {TRACESET_FILE}")
        print(f"[INFO] Sampling interval      : {sampling_interval}")
        print(f"[INFO] Samples per trace      : {n_samples}")
        if key_hex is not None:
            print(f"[INFO] Key                    : 0x{key_hex}")
        else:
            print("[WARN] Key hex attribute 'key_hex' not found in HDF5 file.")
        if iv_hex is not None:
            print(f"[INFO] IV                     : 0x{iv_hex}")
        else:
            print("[WARN] IV hex attribute 'iv_hex' not found in HDF5 file.")
        print(f"[INFO] Initial nonce          : 0x{nonce_original_hex}")

    except FileNotFoundError:
        print(
            f"[ERROR] Traces file {TRACESET_FILE} not found. "
            "Please run the trace acquisition phase first."
        )
        return
    except Exception as e:
        print(f"[ERROR] Could not read traces file {TRACESET_FILE}: {e}")
        return

    if key_hex is None or iv_hex is None:
        print("[ERROR] Missing key_hex or iv_hex in attributes, cannot proceed.")
        return

    # -----------------------------------------------------------------------
    # Decode key/IV and pretty-print expected halves
    # -----------------------------------------------------------------------

    # IV as integer (already in correct endianness)
    iv_int = int(iv_hex, 16)

    key_b = bytes.fromhex(key_hex)
    # Matching how the the C code loads k_0->s[1], k_1->s[2] (little endian)
    k0_int = int.from_bytes(key_b[0:8],  byteorder="little")  # 07 06 05 04 03 02 01 00
    k1_int = int.from_bytes(key_b[8:16], byteorder="little")  # 0F 0E 0D 0C 0B 0A 09 08

    # Expected bits, LSB at index 0
    k0_bits = np.array([(k0_int >> i) & 1 for i in range(64)], dtype=np.uint8)
    k1_bits = np.array([(k1_int >> i) & 1 for i in range(64)], dtype=np.uint8)

    # Pretty-print bytes explicitly as stored in Little-Endian (LSB byte -> MSB byte)
    k0_bytes_le = [f"{b:02X}" for b in k0_int.to_bytes(8, "little")]
    k1_bytes_le = [f"{b:02X}" for b in k1_int.to_bytes(8, "little")]

    # Pretty-printed table by byte
    label_width = 12
    byte_indices = list(range(7, -1, -1))

    print("\n[INFO] Key halves by byte (big-endian)")
    print(f"{'':<{label_width}}" + "  " + "  ".join(f"{b:>2}" for b in byte_indices))
    print(f"{'k0':<{label_width}}" + "  " + "  ".join(f"{b:>2}" for b in k0_bytes_le))
    print(f"{'k1':<{label_width}}" + "  " + "  ".join(f"{b:>2}" for b in k1_bytes_le))
    if verbose:
        print_key_bits("k0", k0_bits)
        print_key_bits("k1", k1_bits)

    # -----------------------------------------------------------------------
    # Simple leakage-model sanity check on one attacked bit
    # -----------------------------------------------------------------------
    H = np.empty((n_trc, 64), dtype=np.uint8)

    # Containers for recovered key bits
    # -------------------------------------------------------------------
    k0_rec_bits      = np.zeros(64, dtype=np.uint8)   # most significant 64 bits
    k0_rec = np.zeros(64, dtype=bool)
    k1_rec_bits      = np.zeros(64, dtype=np.uint8)   # least significant 64 bits
    k1_rec = np.zeros(64, dtype=bool)
    k0_xor_k1_rec_bits = np.zeros(64, dtype=np.uint8)
    k0_xor_k1_rec = np.zeros(64, dtype=bool)

    # -------------------------------------------------------------------
    # Shared flags so workers can skip useless targets early
    # (uint8: 0/1 mirrors the bool arrays)
    # -------------------------------------------------------------------
    k0_rec_shm    = shared_memory.SharedMemory(create=True, size=64)
    k1_rec_shm    = shared_memory.SharedMemory(create=True, size=64)
    kxor_rec_shm  = shared_memory.SharedMemory(create=True, size=64)

    k0_rec_shared   = np.ndarray((64,), dtype=np.uint8, buffer=k0_rec_shm.buf)
    k1_rec_shared   = np.ndarray((64,), dtype=np.uint8, buffer=k1_rec_shm.buf)
    kxor_rec_shared = np.ndarray((64,), dtype=np.uint8, buffer=kxor_rec_shm.buf)

    # init from your bool arrays
    k0_rec_shared[:]   = k0_rec.astype(np.uint8)
    k1_rec_shared[:]   = k1_rec.astype(np.uint8)
    kxor_rec_shared[:] = k0_xor_k1_rec.astype(np.uint8)

    tic = time.perf_counter()
    print("\n=== Recovering k0 and k1 (generic 6-bit leakage model) ===\n")

    if not os.path.exists(SNR_FILE):
        raise FileNotFoundError(f"Attacked bits file not found: {SNR_FILE}")

    try:
        with h5py.File(SNR_FILE, "r") as f:
            regs = f["ranked/register"][:].astype(str)
            bits = f["ranked/bit"][:].astype(int)
    except Exception as e:
        print(f"[ERROR] Could not read SNR file {SNR_FILE}: {e}")
        raise
    attacked_targets = list(zip(regs.tolist(), bits.tolist()))
    print(f"[INFO] Loaded {len(attacked_targets)} attacked targets from {SNR_FILE}")
    if verbose : 
        print(f"[INFO] Top-5 targets: {[(attacked_targets[i][0], attacked_targets[i][1]) for i in range(min(5,len(attacked_targets)))]}")

    # -----------------------------------------------------------------------
    # Attack loop (multiprocessing: compute per-target CPA in workers,
    # but commit recovered bits strictly in-order in main)
    # -----------------------------------------------------------------------
    full_key_recovered = False

    # Prepare shared memory for traces and nonces (read-only for workers)
    traces_shm = shared_memory.SharedMemory(create=True, size=traces.nbytes)
    nonces_shm = shared_memory.SharedMemory(create=True, size=nonces.nbytes)

    traces_shared = np.ndarray(traces.shape, dtype=traces.dtype, buffer=traces_shm.buf, order="C")
    nonces_shared = np.ndarray(nonces.shape, dtype=nonces.dtype, buffer=nonces_shm.buf, order="C")
    traces_shared[:] = traces[:]
    nonces_shared[:] = nonces[:]

    # Build ordered tasks (order_idx preserves commit order deterministically)
    tasks = [(i, attacked_state_reg, attacked_bit) for i, (attacked_state_reg, attacked_bit) in enumerate(attacked_targets)]

    try:
        with mp.Pool(
            processes=n_proc,
            initializer=_mp_init_worker,
            initargs=(
                traces_shm.name,
                nonces_shm.name,
                traces.shape,
                nonces.shape,
                str(traces.dtype),
                str(nonces.dtype),
                iv_int,
                sbox_type,
                n_trc,
                k0_rec_shm.name,
                k1_rec_shm.name,
                kxor_rec_shm.name,
            ),
        ) as pool:

            # imap preserves the input order -> results arrive in the same order as tasks
            for res in tqdm(
                pool.imap(_mp_worker_attack_target, tasks, chunksize=1),
                total=len(tasks),
                desc="Attack targets (parallel)",
            ):
                if res.get("skipped", False):
                    if verbose:
                        print(f"\n[INFO] Skipped {res['attacked_state_reg']}[{res['attacked_bit']}] (no new key bits expected)")
                    continue

                if full_key_recovered:
                    # Stop early if we already have full key
                    pool.terminate()
                    break

                attacked_state_reg = res["attacked_state_reg"]
                attacked_bit = res["attacked_bit"]
                k_idx = res["k_idx"]
                best_key_group = res["best_key_group"]

                # -------------------------------------------------------------------
                # Decide if this target can add new info (same logic as your code)
                # -------------------------------------------------------------------
                useful = False
                for idx in k_idx:
                    idx_done = (k0_rec[idx] and k1_rec[idx]) or (k0_xor_k1_rec[idx] and (k0_rec[idx] or k1_rec[idx]))
                    if not idx_done:
                        useful = True
                        break

                if not useful:
                    if verbose:
                        print(f"\n[INFO] Skipping {attacked_state_reg}[{attacked_bit}] (no new key bits expected)")
                    continue

                print(f"\n[INFO] Attacking state register {attacked_state_reg}, bit {attacked_bit}")
                print(f"[INFO] This attack constrains key bit indices: {k_idx.tolist()}")

                # -------------------------------------------------------------------
                # Commit stage (write in-order only here in main process)
                # -------------------------------------------------------------------
                if verbose:
                    print(f"\n[INFO] Finished CPA for {attacked_state_reg}[{attacked_bit}]")
                    print(f"\nTotal number of groups: {res['num_groups']}")
                    print(f"Best group index: {res['best_group_idx']}\n")
                    print("group   hyp   k1    k0")
                    print("------------------------")
                    members = best_key_group
                    if not members:
                        print(f"{res['best_group_idx']:5d}  <empty group>")
                    else:
                        for line_idx, hyp_idx in enumerate(members):
                            k1_loc = (int(hyp_idx) >> 3) & 0b111
                            k0_loc =  int(hyp_idx)       & 0b111
                            group_label = f"{res['best_group_idx']:5d}" if line_idx == 0 else " " * 5
                            print(f"{group_label}  {int(hyp_idx):3d}  {k1_loc:03b}  {k0_loc:03b}")
                    print()
                
                group_size = len(best_key_group)

                if group_size == 1:
                    hyp = int(best_key_group[0])

                    # local k0 bits: [b2, b1, b0]
                    k0_local = np.array([(hyp >> (2 - b)) & 1 for b in range(3)], dtype=np.uint8)
                    # local k1 bits: [b5, b4, b3]
                    k1_local = np.array([(hyp >> (5 - b)) & 1 for b in range(3)], dtype=np.uint8)

                    for local_pos, idx in enumerate(k_idx):
                        val0 = int(k0_local[local_pos])
                        val1 = int(k1_local[local_pos])

                        # Commit k0 bit
                        if not k0_rec[idx]:
                            k0_rec_bits[idx] = val0
                            k0_rec[idx] = True
                            if verbose:
                                print(f"[INFO] Recovered k0[{idx}]={val0}")
                                print(f"[WARN] Expected k0[{idx}]={k0_bits[idx]} but got {val0}") if val0 != k0_bits[idx] else None
                        elif k0_rec_bits[idx] != val0 and verbose:
                            print(f"[WARN] Conflicting recovery for k0[{idx}]: existing={k0_rec_bits[idx]}, new={val0} (ignored)")

                        # Commit k1 bit
                        if not k1_rec[idx]:
                            k1_rec_bits[idx] = val1
                            k1_rec[idx] = True
                            if verbose:
                                print(f"[INFO] Recovered k1[{idx}]={val1}")
                                print(f"[WARN] Expected k1[{idx}]={k1_bits[idx]} but got {val1}") if val1 != k1_bits[idx] else None
                        elif k1_rec_bits[idx] != val1 and verbose:
                            print(f"[WARN] Conflicting recovery for k1[{idx}]: existing={k1_rec_bits[idx]}, new={val1} (ignored)")

                        # If xor known, check consistency with known k0/k1 bits
                        if k0_xor_k1_rec[idx]:
                            xb = int(k0_xor_k1_rec_bits[idx])
                            xb_comp = int(k0_rec_bits[idx] ^ k1_rec_bits[idx])
                            if xb != xb_comp and verbose:
                                print(f"[WARN] Conflicting recovery for (k0^k1)[{idx}]: stored={xb}, computed={xb_comp} (ignored)")

                else:
                    # Grouping ambiguity: Scenario A (const bits) + Scenario B (xor const)
                    k0_local_list = []
                    k1_local_list = []
                    for hyp in best_key_group:
                        hyp = int(hyp)
                        k0_local = np.array([(hyp >> (2 - b)) & 1 for b in range(3)], dtype=np.uint8)
                        k1_local = np.array([(hyp >> (5 - b)) & 1 for b in range(3)], dtype=np.uint8)
                        k0_local_list.append(k0_local)
                        k1_local_list.append(k1_local)

                    k0_local_all = np.vstack(k0_local_list).astype(np.uint8)
                    k1_local_all = np.vstack(k1_local_list).astype(np.uint8)

                    # Scenario A: recover constants across the group
                    k0_const = np.all(k0_local_all == k0_local_all[0:1, :], axis=0)
                    k1_const = np.all(k1_local_all == k1_local_all[0:1, :], axis=0)

                    for local_pos, idx in enumerate(k_idx):
                        if k0_const[local_pos]:
                            val0 = int(k0_local_all[0, local_pos])
                            if not k0_rec[idx]:
                                k0_rec_bits[idx] = val0
                                k0_rec[idx] = True
                                if verbose:
                                    print(f"[INFO] Recovered k0[{idx}]={val0}")
                                    print(f"[WARN] Expected k0[{idx}]={k0_bits[idx]} but got {val0}") if val0 != k0_bits[idx] else None
                            elif k0_rec_bits[idx] != val0 and verbose:
                                print(f"[WARN] Conflicting recovery for k0[{idx}]: existing={k0_rec_bits[idx]}, new={val0} (ignored)")

                        if k1_const[local_pos]:
                            val1 = int(k1_local_all[0, local_pos])
                            if not k1_rec[idx]:
                                k1_rec_bits[idx] = val1
                                k1_rec[idx] = True
                                if verbose:
                                    print(f"[INFO] Recovered k1[{idx}]={val1}")
                                    print(f"[WARN] Expected k1[{idx}]={k1_bits[idx]} but got {val1}") if val1 != k1_bits[idx] else None
                            elif k1_rec_bits[idx] != val1 and verbose:
                                print(f"[WARN] Conflicting recovery for k1[{idx}]: existing={k1_rec_bits[idx]}, new={val1} (ignored)")

                        # Propagate if xor already known
                        if k0_xor_k1_rec[idx]:
                            xb = int(k0_xor_k1_rec_bits[idx])

                            if k0_rec[idx] and not k1_rec[idx]:
                                k1_rec_bits[idx] = int(k0_rec_bits[idx] ^ xb)
                                k1_rec[idx] = True
                                if verbose:
                                    print(f"[INFO] Recovered k1[{idx}]={k1_rec_bits[idx]} using k0[{idx}] and k0^k1[{idx}]")
                                    print(f"[WARN] Expected k1[{idx}]={k1_bits[idx]} but got {k1_rec_bits[idx]}") if k1_rec_bits[idx] != k1_bits[idx] else None
                                    
                            if k1_rec[idx] and not k0_rec[idx]:
                                k0_rec_bits[idx] = int(k1_rec_bits[idx] ^ xb)
                                k0_rec[idx] = True
                                if verbose:
                                    print(f"[INFO] Recovered k0[{idx}]={k0_rec_bits[idx]} using k1[{idx}] and k0^k1[{idx}]")
                                    print(f"[WARN] Expected k0[{idx}]={k0_bits[idx]} but got {k0_rec_bits[idx]}") if k0_rec_bits[idx] != k0_bits[idx] else None

                    # Scenario B: XOR-only influence
                    xor_mat = k0_local_all ^ k1_local_all
                    xor_val = xor_mat[0]
                    all_cols_ok = bool(np.all(xor_mat == xor_val[None, :]))

                    if all_cols_ok:
                        for local_pos, idx in enumerate(k_idx):
                            xor_bit = int(xor_val[local_pos])

                            if not k0_xor_k1_rec[idx]:
                                k0_xor_k1_rec_bits[idx] = xor_bit
                                k0_xor_k1_rec[idx] = True

                                # Derive missing side if possible
                                if k0_rec[idx] and not k1_rec[idx]:
                                    k1_rec_bits[idx] = int(k0_rec_bits[idx] ^ xor_bit)
                                    k1_rec[idx] = True
                                    if verbose:
                                        print(f"[INFO] Recovered k1[{idx}]={k1_rec_bits[idx]} using k0[{idx}] and k0^k1[{idx}]")
                                        print(f"[WARN] Expected k1[{idx}]={k1_bits[idx]} but got {k1_rec_bits[idx]}") if k1_rec_bits[idx] != k1_bits[idx] else None

                                if k1_rec[idx] and not k0_rec[idx]:
                                    k0_rec_bits[idx] = int(k1_rec_bits[idx] ^ xor_bit)
                                    k0_rec[idx] = True
                                    if verbose:
                                        print(f"[INFO] Recovered k0[{idx}]={k0_rec_bits[idx]} using k1[{idx}] and k0^k1[{idx}]")
                                        print(f"[WARN] Expected k0[{idx}]={k0_bits[idx]} but got {k0_rec_bits[idx]}") if k0_rec_bits[idx] != k0_bits[idx] else None

                            elif k0_xor_k1_rec_bits[idx] != xor_bit and verbose:
                                print(f"[WARN] Conflicting recovery for (k0^k1)[{idx}]: existing={k0_xor_k1_rec_bits[idx]}, new={xor_bit} (ignored)")

                k0_rec_shared[:]   = k0_rec.astype(np.uint8)
                k1_rec_shared[:]   = k1_rec.astype(np.uint8)
                kxor_rec_shared[:] = k0_xor_k1_rec.astype(np.uint8)

                # Update termination condition
                full_key_recovered = bool(np.all(k0_rec) and np.all(k1_rec))
                print(f"[INFO] Progress: k0={np.sum(k0_rec)}/64, k1={np.sum(k1_rec)}/64, k0_xor_k1={np.sum(k0_xor_k1_rec)}/64")

                if full_key_recovered:
                    pool.terminate()
                    break

    finally:
        # Cleanup shared memory
        try:
            traces_shm.close()
            traces_shm.unlink()
        except Exception:
            pass

        try:
            nonces_shm.close()
            nonces_shm.unlink()
        except Exception:
            pass
        for shm in (k0_rec_shm, k1_rec_shm, kxor_rec_shm):
            try:
                shm.close()
                shm.unlink()
            except Exception:
                pass


    toc = time.perf_counter()
    print(f"\n key recovery attack completed in {(toc - tic)/60:.2f} minutes.") 
    # -------------------------------------------------------------------
    # After the attack: build recovered ints and compare to expected key
    # Assumes you already have:
    #   - expected: k0_int, k1_int (uint64 values)
    #   - expected bits: k0_rec_bits_exp, k1_bits_exp (0/1 arrays)   <-- rename to avoid clash
    #   - recovered bits arrays + masks: k0_rec_bits, k1_rec_bits, k0_rec, k1_rec
    # -------------------------------------------------------------------
    
    def bits_to_u64(bits_lsb0: np.ndarray) -> int:
        """bits_lsb0[i] is bit i (LSB at index 0)."""
        x = 0
        for i in range(64):
            x |= (int(bits_lsb0[i]) & 1) << i
        return x
    
    # Build recovered ints (unknown bits are currently 0 in your arrays)
    k0_rec_int = bits_to_u64(k0_rec_bits)
    k1_rec_int = bits_to_u64(k1_rec_bits)
    
    print("\n================= KEY CHECK =================")
    print(f"[INFO] Expected k0 : 0x{k0_int:016X}")
    print(f"[INFO] Recovered k0: 0x{k0_rec_int:016X}  ({np.sum(k0_rec)}/64 bits recovered)")
    
    print(f"[INFO] Expected k1 : 0x{k1_int:016X}")
    print(f"[INFO] Recovered k1: 0x{k1_rec_int:016X}  ({np.sum(k1_rec)}/64 bits recovered)")
    
    # Count correct bits (only count positions you actually recovered)
    #k0_correct = int(np.sum((k0_rec_bits == np.array([(k0_int >> i) & 1 for i in range(64)], dtype=np.uint8)) & k0_rec))
    #k1_correct = int(np.sum((k1_rec_bits == np.array([(k1_int >> i) & 1 for i in range(64)], dtype=np.uint8)) & k1_rec))
    k0_correct = int(np.sum((k0_rec_bits == k0_bits) & k0_rec))
    k1_correct = int(np.sum((k1_rec_bits == k1_bits) & k1_rec))


    print(f"[INFO] Correct recovered bits:")
    print(f"       k0: {k0_correct}/{int(np.sum(k0_rec))} correct (among recovered)")
    print(f"       k1: {k1_correct}/{int(np.sum(k1_rec))} correct (among recovered)")
    
    # Optional: strict full-key check (only meaningful if fully recovered)
    if np.all(k0_rec) and np.all(k1_rec):
        ok = (k0_rec_int == k0_int) and (k1_rec_int == k1_int)
        print(f"[INFO] Full key match: {'YES' if ok else 'NO'}")
    else:
        print("[INFO] Full key match: N/A (not all bits recovered)")
    print("=============================================\n")
    print()
    print("--- DEBUG LOGS BELOW (if any) ---")


if __name__ == "__main__":
    main()
