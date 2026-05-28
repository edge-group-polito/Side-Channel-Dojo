#!/usr/bin/env python3
"""
ASCON generic leakage CPA attack using SNR-ranked target bits.

Memory-friendly / chunked version.

This script:
  - loads only metadata from the trace HDF5 file
  - loads SNR-ranked attack targets for x0..x4
  - attacks targets in SNR-ranked order
  - processes traces in chunks, without loading the full trace matrix
  - uses GPU/CuPy for chunked CPA accumulators if available
  - otherwise falls back to CPU/NumPy with maximum available CPU threads
  - supports all five ASCON state registers: x0, x1, x2, x3, x4

Expected SNR ranked file:
  /ranked/register   : UTF-8 strings, e.g., x0..x4
  /ranked/bit        : uint16/int bit index 0..63
  /ranked/snr        : float32/float64 peak SNR value
"""

import os

# ---------------------------------------------------------------------------
# CPU configuration
# ---------------------------------------------------------------------------
# None means use all available CPU cores/threads.
# Set to e.g. 8, 16, 32 if you want to limit CPU usage.
max_cpu_workers = None

_cpu_count = os.cpu_count() or 1
if max_cpu_workers is None:
    max_cpu_workers = _cpu_count

# Set before importing NumPy.
os.environ["OMP_NUM_THREADS"] = str(max_cpu_workers)
os.environ["OPENBLAS_NUM_THREADS"] = str(max_cpu_workers)
os.environ["MKL_NUM_THREADS"] = str(max_cpu_workers)
os.environ["VECLIB_MAXIMUM_THREADS"] = str(max_cpu_workers)
os.environ["NUMEXPR_NUM_THREADS"] = str(max_cpu_workers)

import sys
import time
import json
from pathlib import Path

import h5py
import numpy as np
from tqdm import tqdm
from typing import List

try:
    import cupy as cp
    CUPY_AVAILABLE = True
    CUPY_ERROR = None
except Exception as e:
    cp = None
    CUPY_AVAILABLE = False
    CUPY_ERROR = str(e)


# ---------------------------------------------------------------------------
# Basic configuration
# ---------------------------------------------------------------------------
# Supported S-box types:
#   lut_ascon, lut_bilgin, lut_allouzi, lut_lu_4, lut_lu_5, lut_lu_6, lut_lu_7
sbox_type = os.environ.get("ASCON_SBOX_TYPE", "lut_ascon")

# Number of traces to use. The script uses min(n_trc, traces_in_file).
n_trc = int(os.environ.get("ASCON_N_TRC", "1000000"))

# If the trace filename is based on a different size, change this.
# Example:
#   traceset_size_k = 150
# gives:
#   ascon_opt32_lut_lu_7_150k.h5
traceset_size_k = n_trc // 1000

# Chunk size for trace reading.
# Reduce if memory is high. Increase if I/O overhead is high.
chunk_size = int(os.environ.get("ASCON_CHUNK_SIZE", "20000"))

# Optional sample-window acceleration.
# 0 means full trace width. A positive value uses only that many samples around
# the target's SNR peak sample, if the matching snr_traces_*.h5 file exists.
cpa_sample_window = int(os.environ.get("ASCON_CPA_SAMPLE_WINDOW", "0"))
if cpa_sample_window < 0:
    raise ValueError("ASCON_CPA_SAMPLE_WINDOW must be >= 0")

# Compute device:
#   "auto" -> use GPU/CuPy if available, otherwise CPU
#   "gpu"  -> require GPU/CuPy
#   "cpu"  -> force CPU
compute_device = os.environ.get("ASCON_CPA_DEVICE", "auto")

# Attack target control.
# None means attack all ranked targets from the SNR file.
# Set e.g. 80 for testing.
_max_targets_env = os.environ.get("ASCON_MAX_TARGETS")
max_targets_to_attack = None if _max_targets_env in (None, "") else int(_max_targets_env)

# CPA only identifies a binary leakage vector up to complement. This selects
# which side of an equivalent group is used after signed correlation is known.
# negative keeps the convention used by earlier runs.
#   negative: signed corr < 0 -> representative side
#   positive: signed corr > 0 -> representative side
#   both    : keep both sides and let existing constraints decide
leakage_polarity = os.environ.get("ASCON_LEAKAGE_POLARITY", "negative").strip().lower()
if leakage_polarity not in {"negative", "positive", "both"}:
    raise ValueError("ASCON_LEAKAGE_POLARITY must be one of: negative, positive, both")

# Flow flags.
verbose = True
debug_k_idx = 30

# Save result JSON.
save_attack_results = True
save_results = True


# ---------------------------------------------------------------------------
# Device selection
# ---------------------------------------------------------------------------
if compute_device == "auto":
    if CUPY_AVAILABLE:
        cpa_backend = "gpu"
        print("[INFO] CuPy is available. Chunked CPA accumulators will use GPU.")
    else:
        cpa_backend = "cpu"
        print(f"[WARN] CuPy is not available. Falling back to CPU with {max_cpu_workers} threads.")

elif compute_device == "gpu":
    if not CUPY_AVAILABLE:
        raise RuntimeError(
            "compute_device='gpu' requested, but CuPy is not available. "
            f"CuPy error: {CUPY_ERROR}"
        )
    cpa_backend = "gpu"

elif compute_device == "cpu":
    cpa_backend = "cpu"
    print(f"[INFO] CPU mode selected. Using up to {max_cpu_workers} CPU threads.")

else:
    raise ValueError("compute_device must be one of: 'auto', 'gpu', 'cpu'")


# ---------------------------------------------------------------------------
# Project root detection and path setup
# ---------------------------------------------------------------------------
def find_project_root(start: Path, markers=("fusesoc.conf", ".dojo_root")) -> Path:
    current = start
    while current != current.parent:
        if any((current / m).exists() for m in markers):
            return current
        current = current.parent

    raise RuntimeError(
        f"Could not find project root. Looked for markers: {markers}. "
        "Please ensure you are inside the Side-Channel-Dojo repository."
    )


try:
    SCRIPT_DIR = Path(__file__).resolve().parent
except NameError:
    SCRIPT_DIR = Path.cwd()

DOJO_ROOT = find_project_root(SCRIPT_DIR)

ASCON_PY_DIR = DOJO_ROOT / "sw" / "ciphers" / "ASCON_init_python"
SCA_DIR = DOJO_ROOT / "sw" / "sca_scripts"

BASE_PLOT_DIR = DOJO_ROOT / "sw" / "sca_scripts" / "ASCON" / "sw" / "plot"
BASE_CACHE_DIR = DOJO_ROOT / "sw" / "sca_scripts" / "ASCON" / "sw" / "cache"
TRACESET_DIR = DOJO_ROOT / "sw" / "traceset" / "ASCON" / "sw"

sys.path.insert(0, str(ASCON_PY_DIR))
sys.path.insert(0, str(SCA_DIR))

from analyzer.attack.ascon.xheep_ascon_cpa.ascon_generic_leakage_model import (
    ascon_generic_leakage_matrix,
)

from analyzer.attack.ascon.xheep_ascon_cpa.ascon_cpa import (
    ascon_cpa_init_accumulators,
    ascon_cpa_update_accumulators,
    ascon_cpa_finalize_corrmax_accumulators,
)


# ---------------------------------------------------------------------------
# Target/key mapping
# ---------------------------------------------------------------------------
def target_to_k_idx(attacked_state_reg: str, attacked_bit: int) -> np.ndarray:
    """
    Given one attacked ASCON state bit, return the three key-bit indices
    constrained by the generic 6-bit leakage model.
    """
    j = int(attacked_bit) % 64

    if attacked_state_reg == "x0":
        return np.array([j, (j + 19) % 64, (j + 28) % 64], dtype=int)
    if attacked_state_reg == "x1":
        return np.array([j, (j + 61) % 64, (j + 39) % 64], dtype=int)
    if attacked_state_reg == "x2":
        return np.array([j, (j + 1) % 64, (j + 6) % 64], dtype=int)
    if attacked_state_reg == "x3":
        return np.array([j, (j + 10) % 64, (j + 17) % 64], dtype=int)
    if attacked_state_reg == "x4":
        return np.array([j, (j + 7) % 64, (j + 41) % 64], dtype=int)

    raise ValueError(f"Invalid attacked_state_register: {attacked_state_reg}")


def _idx_done(idx: int, k0_rec, k1_rec, k0_xor_k1_rec) -> bool:
    return (
        (k0_rec[idx] and k1_rec[idx])
        or (k0_xor_k1_rec[idx] and (k0_rec[idx] or k1_rec[idx]))
    )


def _target_is_useful(k_idx: np.ndarray, k0_rec, k1_rec, k0_xor_k1_rec) -> bool:
    for idx in k_idx:
        if not _idx_done(int(idx), k0_rec, k1_rec, k0_xor_k1_rec):
            return True
    return False


# ---------------------------------------------------------------------------
# General helpers
# ---------------------------------------------------------------------------
def _yn(flag: bool) -> str:
    return "yes" if flag else "no"


def decode_h5_strings(arr) -> List[str]:
    out = []
    for x in arr:
        if isinstance(x, bytes):
            out.append(x.decode("utf-8"))
        else:
            out.append(str(x))
    return out


def bits_to_u64(bits_lsb0: np.ndarray) -> int:
    x = 0
    for i in range(64):
        x |= (int(bits_lsb0[i]) & 1) << i
    return x


def print_key_bits(label: str, bits: np.ndarray) -> None:
    assert bits.shape[0] == 64

    def _with_seps(tokens):
        out = []
        for j, t in enumerate(tokens):
            out.append(t)
            if (j + 1) % 8 == 0 and (j + 1) != len(tokens):
                out.append("|")
        return " ".join(out)

    def _print_block(hi: int, lo: int) -> None:
        idxs = list(range(hi, lo - 1, -1))
        idx_tokens = [f"{i:2d}" for i in idxs]
        val_tokens = [f"{int(bits[i]):2d}" for i in idxs]
        print("idx: " + _with_seps(idx_tokens))
        print("val: " + _with_seps(val_tokens))

    print(f"\n[INFO] {label} bits, index 0 = LSB")
    print("      Byte separators every 8 bits (|)\n")
    _print_block(63, 32)
    print("-" * 106)
    _print_block(31, 0)


# ---------------------------------------------------------------------------
# SNR target loading
# ---------------------------------------------------------------------------
def find_snr_file(cache_dir: Path, sbox_type: str, n_trc: int) -> Path:
    """
    Prefer the new filename, but fall back to the old filename if needed.
    """
    candidates = [
        cache_dir / f"snr_ranked_{sbox_type}_{n_trc // 1000}k.h5",
        cache_dir / "snr_ranked.h5",
    ]

    for p in candidates:
        if p.exists():
            return p

    return candidates[0]


def find_snr_trace_file(cache_dir: Path, sbox_type: str, n_trc: int) -> Path:
    candidates = [
        cache_dir / f"snr_traces_{sbox_type}_{n_trc // 1000}k.h5",
        cache_dir / "snr_traces.h5",
    ]

    for p in candidates:
        if p.exists():
            return p

    return candidates[0]


def load_snr_peak_samples(snr_trace_file: Path):
    """
    Load per-target SNR peak sample indices from the full SNR trace cache.

    Returns:
        dict mapping (reg, bit) -> peak_sample
    """
    if not snr_trace_file.exists():
        return {}

    with h5py.File(snr_trace_file, "r") as f:
        if "snr_traces/value" not in f:
            return {}

        g = f["snr_traces"]
        values = g["value"]

        if "register_names" in g:
            reg_names = decode_h5_strings(g["register_names"][:])
        else:
            reg_names = ["x0", "x1", "x2", "x3", "x4"]

        if "bits" in g:
            bits = g["bits"][:].astype(int)
        else:
            bits = np.arange(values.shape[1], dtype=int)

        peak_samples = {}
        for reg_i, reg in enumerate(reg_names):
            if reg_i >= values.shape[0]:
                break
            for bit_i, bit in enumerate(bits):
                if bit_i >= values.shape[1]:
                    break
                peak_samples[(str(reg), int(bit))] = int(np.argmax(values[reg_i, bit_i, :]))

    return peak_samples


def load_snr_ranked_targets(snr_file: Path, max_targets=None, peak_samples=None):
    """
    Load ranked target bits from SNR HDF5 file.

    Expected:
      /ranked/register
      /ranked/bit
      /ranked/snr
    """
    if not snr_file.exists():
        raise FileNotFoundError(f"SNR ranked file not found: {snr_file}")

    with h5py.File(snr_file, "r") as f:
        regs = decode_h5_strings(f["ranked/register"][:])
        bits = f["ranked/bit"][:].astype(int)

        if "ranked/snr" in f:
            snrs = f["ranked/snr"][:].astype(float)
        else:
            snrs = np.full(len(bits), np.nan, dtype=float)

    targets = []

    for reg, bit, snr in zip(regs, bits, snrs):
        reg = str(reg)

        if reg not in {"x0", "x1", "x2", "x3", "x4"}:
            print(f"[WARN] Ignoring invalid SNR target: {reg}[{bit}]")
            continue

        if bit < 0 or bit > 63:
            print(f"[WARN] Ignoring invalid bit index: {reg}[{bit}]")
            continue

        target = {
            "order_idx": len(targets),
            "reg": reg,
            "bit": int(bit),
            "snr": float(snr),
        }

        if peak_samples is not None:
            peak_sample = peak_samples.get((reg, int(bit)))
            if peak_sample is not None:
                target["snr_peak_sample"] = int(peak_sample)

        targets.append(target)

    if max_targets is not None:
        targets = targets[: int(max_targets)]

    return targets


# ---------------------------------------------------------------------------
# Leakage and grouping helpers
# ---------------------------------------------------------------------------
def compute_H64_chunk(
    nonces_chunk: np.ndarray,
    iv_int: int,
    attacked_state_reg: str,
    attacked_bit: int,
    sbox_type: str,
    backend: str = "cpu",
) -> np.ndarray:
    """
    Compute H matrix for one nonce chunk.

    Output:
        H64 shape = (chunk_len, 64)

    Nonce convention follows the old attack script:
        nonces[:, 0] = nonce LSB
        nonces[:, 1] = nonce MSB
    """
    nonce_lsb = nonces_chunk[:, 0]
    nonce_msb = nonces_chunk[:, 1]

    H64 = ascon_generic_leakage_matrix(
        iv_int,
        nonce_msb,
        nonce_lsb,
        attacked_state_reg,
        int(attacked_bit),
        sbox_type,
        backend=backend,
    )

    return H64.astype(np.uint8, copy=False)


def build_hypothesis_groups_streaming(
    nonces: np.ndarray,
    n_used: int,
    iv_int: int,
    attacked_state_reg: str,
    attacked_bit: int,
    sbox_type: str,
    chunk_size: int,
):
    """
    Build complement-equivalence hypothesis groups without loading traces.

    This streams the already loaded nonce array and constructs the 64 binary
    leakage vectors for the selected target. Memory use is roughly:

        64 * n_used bytes

    For 1,000,000 traces, this is about 64 MB for signatures.
    """
    signatures = [bytearray() for _ in range(64)]

    for start in range(0, n_used, chunk_size):
        end = min(start + chunk_size, n_used)
        nonces_chunk = nonces[start:end]

        H64 = compute_H64_chunk(
            nonces_chunk,
            iv_int,
            attacked_state_reg,
            attacked_bit,
            sbox_type,
            backend="cpu",
        )

        for k in range(64):
            signatures[k].extend(H64[:, k].tobytes())

        del H64

    canonical_to_group = {}
    key_hyp_groups = []
    rep_indices = []

    for k in range(64):
        col_b = bytes(signatures[k])

        col_arr = np.frombuffer(col_b, dtype=np.uint8)
        compl_b = (1 - col_arr).astype(np.uint8, copy=False).tobytes()

        canon_b = col_b if col_b <= compl_b else compl_b

        if canon_b in canonical_to_group:
            g = canonical_to_group[canon_b]
            key_hyp_groups[g].append(k)
        else:
            g = len(key_hyp_groups)
            canonical_to_group[canon_b] = g
            key_hyp_groups.append([k])
            rep_indices.append(k)

    oriented_key_hyp_groups = []

    for rep, members in zip(rep_indices, key_hyp_groups):
        rep_b = bytes(signatures[rep])
        rep_arr = np.frombuffer(rep_b, dtype=np.uint8)
        rep_compl_b = (1 - rep_arr).astype(np.uint8, copy=False).tobytes()

        same_members = []
        complement_members = []

        for hyp in members:
            hyp_b = bytes(signatures[hyp])
            if hyp_b == rep_b:
                same_members.append(hyp)
            elif hyp_b == rep_compl_b:
                complement_members.append(hyp)
            else:
                raise RuntimeError(
                    f"Hypothesis {hyp} is neither identical nor complement "
                    f"to representative {rep}"
                )

        oriented_key_hyp_groups.append(
            {
                "same": same_members,
                "complement": complement_members,
                "all": members,
            }
        )

    return np.array(rep_indices, dtype=np.int64), oriented_key_hyp_groups


def _acc_array_to_numpy(x):
    if CUPY_AVAILABLE and cp is not None and isinstance(x, cp.ndarray):
        return cp.asnumpy(x)
    return np.asarray(x)


def signed_corr_at_samples_from_accumulators(
    acc,
    sample_idx: np.ndarray,
    eps: float = 1e-12,
) -> np.ndarray:
    """
    Return signed correlation for each hypothesis at its selected sample.

    This uses only streaming CPA accumulators, avoiding the full K x samples
    correlation matrix except for the small K-element diagnostic output.
    """
    n_used = float(acc["n_used"])
    sample_idx = np.asarray(sample_idx, dtype=np.int64)
    hyp_idx = np.arange(sample_idx.shape[0], dtype=np.int64)

    sum_t = _acc_array_to_numpy(acc["sum_t"])
    sumsq_t = _acc_array_to_numpy(acc["sumsq_t"])
    sum_h = _acc_array_to_numpy(acc["sum_h"])
    sumsq_h = _acc_array_to_numpy(acc["sumsq_h"])
    sum_ht = _acc_array_to_numpy(acc["sum_ht"])

    cov = sum_ht[hyp_idx, sample_idx] - (sum_h * sum_t[sample_idx]) / n_used
    var_h = sumsq_h - (sum_h * sum_h) / n_used
    var_t = sumsq_t[sample_idx] - (sum_t[sample_idx] * sum_t[sample_idx]) / n_used

    var_h = np.maximum(var_h, 0.0)
    var_t = np.maximum(var_t, 0.0)
    denom = np.sqrt(var_h + eps) * np.sqrt(var_t + eps)

    signed_corr = np.zeros_like(cov, dtype=np.float64)
    ok = denom > eps
    signed_corr[ok] = cov[ok] / denom[ok]
    return signed_corr


def print_top_hypothesis_diagnostics(
    attacked_state_reg: str,
    attacked_bit: int,
    k_idx: np.ndarray,
    corr_abs: np.ndarray,
    argmax_samples: np.ndarray,
    signed_corr: np.ndarray,
    top_n: int = 8,
) -> None:
    order = np.argsort(corr_abs)[::-1][:top_n]

    print(
        f"\n[DBG] Target {attacked_state_reg}[{attacked_bit}] touches "
        f"k_idx={k_idx.tolist()} including {debug_k_idx}"
    )
    print("[DBG] Top CPA hypotheses, ranked by max |corr|:")
    print("rank  hyp  k1     k0     signed_corr   abs_corr     sample")
    print("------------------------------------------------------------")

    for rank, hyp in enumerate(order, start=1):
        hyp = int(hyp)
        k1_loc = (hyp >> 3) & 0b111
        k0_loc = hyp & 0b111
        print(
            f"{rank:4d}  {hyp:3d}  {k1_loc:03b}  {k0_loc:03b}  "
            f"{signed_corr[hyp]: .6g}  {corr_abs[hyp]: .6g}  "
            f"{int(argmax_samples[hyp]):7d}"
        )


def print_top_group_diagnostics(
    attacked_state_reg: str,
    attacked_bit: int,
    k_idx: np.ndarray,
    rep_indices: np.ndarray,
    oriented_key_hyp_groups: list,
    corr_abs: np.ndarray,
    argmax_samples: np.ndarray,
    signed_corr: np.ndarray,
    best_group_idx: int,
    selected_members: list,
    top_n: int = 8,
) -> None:
    order = np.argsort(corr_abs)[::-1][:top_n]

    print(
        f"\n[DBG] Target {attacked_state_reg}[{attacked_bit}] touches "
        f"k_idx={k_idx.tolist()} including {debug_k_idx}"
    )
    print("[DBG] Top CPA groups, ranked by max |corr|:")
    print("rank  grp  rep  signed_corr   abs_corr     sample  same_members  complement_members")
    print("-----------------------------------------------------------------------------------")

    for rank, group_idx in enumerate(order, start=1):
        group_idx = int(group_idx)
        group = oriented_key_hyp_groups[group_idx]
        print(
            f"{rank:4d}  {group_idx:3d}  {int(rep_indices[group_idx]):3d}  "
            f"{signed_corr[group_idx]: .6g}  {corr_abs[group_idx]: .6g}  "
            f"{int(argmax_samples[group_idx]):7d}  "
            f"{group['same']}  {group['complement']}"
        )

    print(
        f"[DBG] Selected members from group {best_group_idx}: "
        f"{selected_members}"
    )


# ---------------------------------------------------------------------------
# Chunked CPA attack for one target
# ---------------------------------------------------------------------------
def attack_one_target_chunked(
    trace_file: Path,
    nonces: np.ndarray,
    n_used: int,
    n_samples: int,
    iv_int: int,
    attacked_state_reg: str,
    attacked_bit: int,
    sbox_type: str,
    chunk_size: int,
    cpa_backend: str,
    sample_start: int = 0,
    sample_stop: int = None,
):
    """
    Attack one target bit using chunked CPA.

    This does not load the full trace matrix.
    It streams:
      - traces[start:end]
      - nonces[start:end]

    It groups complement-equivalent hypotheses, accumulates CPA statistics
    chunk by chunk, then uses the signed correlation of the representative
    to select the same/complement side before committing exact bits.
    """
    k_idx = target_to_k_idx(attacked_state_reg, attacked_bit)

    if sample_stop is None:
        sample_stop = n_samples

    sample_start = int(max(0, sample_start))
    sample_stop = int(min(n_samples, sample_stop))
    if sample_stop <= sample_start:
        raise ValueError(
            f"Invalid CPA sample window [{sample_start}, {sample_stop}) "
            f"for n_samples={n_samples}"
        )

    n_cpa_samples = sample_stop - sample_start

    rep_indices, oriented_key_hyp_groups = build_hypothesis_groups_streaming(
        nonces=nonces,
        n_used=n_used,
        iv_int=iv_int,
        attacked_state_reg=attacked_state_reg,
        attacked_bit=attacked_bit,
        sbox_type=sbox_type,
        chunk_size=chunk_size,
    )

    n_groups = len(rep_indices)

    acc = ascon_cpa_init_accumulators(
        n_samples=n_cpa_samples,
        n_hypotheses=n_groups,
        backend=cpa_backend,
    )

    with h5py.File(trace_file, "r") as f:
        traces_ds = f["traces"]

        for start in range(0, n_used, chunk_size):
            end = min(start + chunk_size, n_used)

            traces_chunk = traces_ds[start:end, sample_start:sample_stop].astype(
                np.float32,
                copy=False,
            )
            nonces_chunk = nonces[start:end]

            H64 = compute_H64_chunk(
                nonces_chunk,
                iv_int,
                attacked_state_reg,
                attacked_bit,
                sbox_type,
                backend="cpu",
            )

            H_group_chunk = H64[:, rep_indices].astype(np.float32, copy=False)

            ascon_cpa_update_accumulators(
                acc,
                traces_chunk,
                H_group_chunk,
            )

            del traces_chunk, nonces_chunk, H64, H_group_chunk

    corr_group, argmax_samples = ascon_cpa_finalize_corrmax_accumulators(
        acc,
        return_argmax_samples=True,
    )

    signed_corr = signed_corr_at_samples_from_accumulators(acc, argmax_samples)
    argmax_samples_abs = argmax_samples + sample_start
    best_group_idx = int(np.argmax(corr_group))
    best_group = oriented_key_hyp_groups[best_group_idx]

    if leakage_polarity == "both":
        best_key_group = best_group["all"]
    elif leakage_polarity == "positive":
        best_key_group = (
            best_group["same"]
            if signed_corr[best_group_idx] > 0.0
            else best_group["complement"]
        )
    else:
        # Convention used by earlier measurements: the measured bit leakage is
        # inverted relative to the model bit value.
        best_key_group = (
            best_group["same"]
            if signed_corr[best_group_idx] < 0.0
            else best_group["complement"]
        )

    if not best_key_group:
        best_key_group = best_group["all"]

    if debug_k_idx in set(map(int, k_idx)):
        print_top_group_diagnostics(
            attacked_state_reg=attacked_state_reg,
            attacked_bit=attacked_bit,
            k_idx=k_idx,
            rep_indices=rep_indices,
            oriented_key_hyp_groups=oriented_key_hyp_groups,
            corr_abs=corr_group,
            argmax_samples=argmax_samples_abs,
            signed_corr=signed_corr,
            best_group_idx=best_group_idx,
            selected_members=best_key_group,
        )

    return {
        "attacked_state_reg": attacked_state_reg,
        "attacked_bit": int(attacked_bit),
        "k_idx": k_idx,
        "best_key_group": best_key_group,
        "skipped": False,
        "num_groups": int(n_groups),
        "best_group_idx": best_group_idx,
        "best_corr": float(corr_group[best_group_idx]),
        "best_signed_corr": float(signed_corr[best_group_idx]),
        "best_sample": int(argmax_samples_abs[best_group_idx]),
        "sample_start": int(sample_start),
        "sample_stop": int(sample_stop),
        "n_cpa_samples": int(n_cpa_samples),
    }


# ---------------------------------------------------------------------------
# Commit/recovery logic
# ---------------------------------------------------------------------------
def hypothesis_to_local_bits(hyp: int):
    hyp = int(hyp)
    k0_local = np.array([(hyp >> (2 - b)) & 1 for b in range(3)], dtype=np.uint8)
    k1_local = np.array([(hyp >> (5 - b)) & 1 for b in range(3)], dtype=np.uint8)
    return k0_local, k1_local


def filter_hypotheses_by_known_bits(
    hypotheses,
    k_idx,
    k0_rec_bits,
    k0_rec,
    k1_rec_bits,
    k1_rec,
    k0_xor_k1_rec_bits,
    k0_xor_k1_rec,
):
    """
    Keep only hypotheses consistent with bits recovered from earlier targets.

    This is the generic constraint step from the paper: the winning CPA group
    may represent a unique assignment, k0-only, k1-only, AND/OR-like, XOR-like,
    or mixed relation. Existing knowledge can reduce that group further.
    """
    filtered = []

    for hyp in hypotheses:
        k0_local, k1_local = hypothesis_to_local_bits(hyp)
        ok = True

        for local_pos, idx in enumerate(k_idx):
            idx = int(idx)
            val0 = int(k0_local[local_pos])
            val1 = int(k1_local[local_pos])

            if k0_rec[idx] and int(k0_rec_bits[idx]) != val0:
                ok = False
                break

            if k1_rec[idx] and int(k1_rec_bits[idx]) != val1:
                ok = False
                break

            if k0_xor_k1_rec[idx]:
                xor_val = val0 ^ val1
                if int(k0_xor_k1_rec_bits[idx]) != xor_val:
                    ok = False
                    break

        if ok:
            filtered.append(int(hyp))

    return filtered


def _commit_single_bit(name, idx, value, rec_bits, rec_flags, expected_bits, verbose):
    idx = int(idx)
    value = int(value)

    if not rec_flags[idx]:
        rec_bits[idx] = value
        rec_flags[idx] = True
        if verbose:
            print(f"[INFO] Recovered {name}[{idx}]={value}")
            if value != int(expected_bits[idx]):
                print(f"[WARN] Expected {name}[{idx}]={int(expected_bits[idx])} but got {value}")
        return True

    if int(rec_bits[idx]) != value and verbose:
        print(f"[WARN] Conflict for {name}[{idx}]: existing={int(rec_bits[idx])}, new={value}")

    return False


def propagate_group_constraints(
    candidates,
    k_idx,
    k0_bits,
    k1_bits,
    k0_rec_bits,
    k0_rec,
    k1_rec_bits,
    k1_rec,
    k0_xor_k1_rec_bits,
    k0_xor_k1_rec,
    verbose=True,
):
    """
    Commit every key bit, k0/k1 XOR bit, and derived bit forced by candidates.

    Unlike the older special cases, this does not assume a specific Boolean
    form. It repeatedly filters the CPA-winning hypothesis set by known facts,
    then commits any columns that are constant across all remaining candidates.
    """
    candidates = list(map(int, candidates))

    if not candidates:
        if verbose:
            print("[WARN] CPA selected an empty hypothesis set; no bits committed.")
        return []

    while True:
        filtered = filter_hypotheses_by_known_bits(
            candidates,
            k_idx,
            k0_rec_bits,
            k0_rec,
            k1_rec_bits,
            k1_rec,
            k0_xor_k1_rec_bits,
            k0_xor_k1_rec,
        )

        if not filtered:
            if verbose:
                print(
                    "[WARN] Winning hypothesis set conflicts with previously "
                    "recovered bits; keeping previous bits and committing nothing."
                )
            return []

        k0_all = []
        k1_all = []
        for hyp in filtered:
            k0_local, k1_local = hypothesis_to_local_bits(hyp)
            k0_all.append(k0_local)
            k1_all.append(k1_local)

        k0_all = np.vstack(k0_all).astype(np.uint8)
        k1_all = np.vstack(k1_all).astype(np.uint8)
        xor_all = k0_all ^ k1_all

        changed = False

        for local_pos, idx in enumerate(k_idx):
            idx = int(idx)

            if np.all(k0_all[:, local_pos] == k0_all[0, local_pos]):
                changed |= _commit_single_bit(
                    "k0",
                    idx,
                    int(k0_all[0, local_pos]),
                    k0_rec_bits,
                    k0_rec,
                    k0_bits,
                    verbose,
                )

            if np.all(k1_all[:, local_pos] == k1_all[0, local_pos]):
                changed |= _commit_single_bit(
                    "k1",
                    idx,
                    int(k1_all[0, local_pos]),
                    k1_rec_bits,
                    k1_rec,
                    k1_bits,
                    verbose,
                )

            if np.all(xor_all[:, local_pos] == xor_all[0, local_pos]):
                xor_bit = int(xor_all[0, local_pos])

                if not k0_xor_k1_rec[idx]:
                    k0_xor_k1_rec_bits[idx] = xor_bit
                    k0_xor_k1_rec[idx] = True
                    changed = True
                    if verbose:
                        print(f"[INFO] Recovered (k0^k1)[{idx}]={xor_bit}")
                elif int(k0_xor_k1_rec_bits[idx]) != xor_bit and verbose:
                    print(
                        f"[WARN] Conflict for (k0^k1)[{idx}]: "
                        f"existing={int(k0_xor_k1_rec_bits[idx])}, new={xor_bit}"
                    )

            if k0_xor_k1_rec[idx] and k0_rec[idx] and not k1_rec[idx]:
                derived = int(k0_rec_bits[idx] ^ k0_xor_k1_rec_bits[idx])
                changed |= _commit_single_bit(
                    "k1",
                    idx,
                    derived,
                    k1_rec_bits,
                    k1_rec,
                    k1_bits,
                    verbose,
                )

            if k0_xor_k1_rec[idx] and k1_rec[idx] and not k0_rec[idx]:
                derived = int(k1_rec_bits[idx] ^ k0_xor_k1_rec_bits[idx])
                changed |= _commit_single_bit(
                    "k0",
                    idx,
                    derived,
                    k0_rec_bits,
                    k0_rec,
                    k0_bits,
                    verbose,
                )

        if not changed:
            return filtered


def commit_attack_result(
    res,
    k0_bits,
    k1_bits,
    k0_rec_bits,
    k0_rec,
    k1_rec_bits,
    k1_rec,
    k0_xor_k1_rec_bits,
    k0_xor_k1_rec,
    verbose=True,
):
    attacked_state_reg = res["attacked_state_reg"]
    attacked_bit = res["attacked_bit"]
    k_idx = res["k_idx"]
    best_key_group = res["best_key_group"]

    useful = _target_is_useful(k_idx, k0_rec, k1_rec, k0_xor_k1_rec)

    if not useful:
        if verbose:
            print(f"\n[INFO] Skipping {attacked_state_reg}[{attacked_bit}] after CPA result; no new bits needed.")
        return

    print(f"\n[INFO] Attacking state register {attacked_state_reg}, bit {attacked_bit}")
    print(f"[INFO] This attack constrains key bit indices: {k_idx.tolist()}")

    if verbose:
        print(f"[INFO] Finished CPA for {attacked_state_reg}[{attacked_bit}]")
        print(f"[INFO] Number of groups : {res.get('num_groups', 'N/A')}")
        print(f"[INFO] Best group index : {res.get('best_group_idx', 'N/A')}")
        print(f"[INFO] Best correlation : {res.get('best_corr', float('nan')):.6g}")
        print(f"[INFO] Best sample      : {res.get('best_sample', 'N/A')}")
        if "sample_start" in res and "sample_stop" in res:
            print(
                f"[INFO] CPA sample range : "
                f"[{res['sample_start']}, {res['sample_stop']})"
            )
        print()
        print("group   hyp   k1    k0")
        print("------------------------")

        members = best_key_group
        if not members:
            print(f"{res.get('best_group_idx', -1):5d}  <empty group>")
        else:
            for line_idx, hyp_idx in enumerate(members):
                k1_loc = (int(hyp_idx) >> 3) & 0b111
                k0_loc = int(hyp_idx) & 0b111
                group_label = f"{res.get('best_group_idx', -1):5d}" if line_idx == 0 else " " * 5
                print(f"{group_label}  {int(hyp_idx):3d}  {k1_loc:03b}  {k0_loc:03b}")
        print()

    remaining = propagate_group_constraints(
        best_key_group,
        k_idx,
        k0_bits,
        k1_bits,
        k0_rec_bits,
        k0_rec,
        k1_rec_bits,
        k1_rec,
        k0_xor_k1_rec_bits,
        k0_xor_k1_rec,
        verbose=verbose,
    )

    if verbose and remaining:
        print(f"[INFO] Remaining compatible hypotheses after propagation: {remaining}")


def target_sample_window(target: dict, n_samples: int, window_size: int):
    if window_size <= 0 or "snr_peak_sample" not in target:
        return 0, int(n_samples)

    width = min(int(window_size), int(n_samples))
    peak = int(target["snr_peak_sample"])

    start = peak - width // 2
    stop = start + width

    if start < 0:
        start = 0
        stop = width

    if stop > n_samples:
        stop = int(n_samples)
        start = max(0, stop - width)

    return int(start), int(stop)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    trace_file = TRACESET_DIR / f"ascon_opt32_{sbox_type}_{traceset_size_k}k.h5"

    plot_dir = BASE_PLOT_DIR / sbox_type
    cache_dir = BASE_CACHE_DIR / sbox_type

    snr_file = find_snr_file(cache_dir, sbox_type, n_trc)
    snr_trace_file = find_snr_trace_file(cache_dir, sbox_type, n_trc)
    cpa_cache_file = cache_dir / f"CPA_results_chunked_{sbox_type}_{n_trc // 1000}k.json"

    BASE_PLOT_DIR.mkdir(parents=True, exist_ok=True)
    BASE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    plot_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    # -----------------------------------------------------------------------
    # Read metadata only
    # -----------------------------------------------------------------------
    try:
        with h5py.File(trace_file, "r") as f:
            if "traces" not in f or "nonces" not in f:
                raise KeyError("HDF5 file is missing required datasets 'traces' and/or 'nonces'.")

            traces_ds = f["traces"]
            nonces_ds = f["nonces"]

            total_traces = int(traces_ds.shape[0])
            n_samples = int(traces_ds.shape[1])

            sampling_interval = f.attrs.get("sampling_interval", None)
            key_hex = f.attrs.get("key_hex", None)
            iv_hex = f.attrs.get("iv_hex", None)

            n_used = min(int(n_trc), total_traces)
            first_nonce = nonces_ds[0]
            nonces = np.asarray(nonces_ds[:n_used])

    except FileNotFoundError:
        print(f"[ERROR] Traces file not found: {trace_file}")
        return
    except Exception as e:
        print(f"[ERROR] Could not read trace metadata from {trace_file}: {e}")
        return

    if key_hex is None:
        print("[ERROR] Missing key_hex in HDF5 attributes.")
        return

    if iv_hex is None:
        print("[ERROR] Missing iv_hex in HDF5 attributes.")
        return

    # Nonce convention used in the old attack code:
    #   nonces[:, 0] = nonce LSB
    #   nonces[:, 1] = nonce MSB
    nonce_lsb = int(first_nonce[0])
    nonce_msb = int(first_nonce[1])
    nonce_stored_int = (nonce_msb << 64) | nonce_lsb
    nonce_original_bytes = nonce_stored_int.to_bytes(16, byteorder="big")[::-1]
    nonce_original_hex = nonce_original_bytes.hex().upper()

    # -----------------------------------------------------------------------
    # Decode key and IV
    # -----------------------------------------------------------------------
    iv_int = int(iv_hex, 16)

    key_b = bytes.fromhex(key_hex)

    k0_int = int.from_bytes(key_b[0:8], byteorder="little")
    k1_int = int.from_bytes(key_b[8:16], byteorder="little")

    k0_bits = np.array([(k0_int >> i) & 1 for i in range(64)], dtype=np.uint8)
    k1_bits = np.array([(k1_int >> i) & 1 for i in range(64)], dtype=np.uint8)

    # -----------------------------------------------------------------------
    # Print configuration
    # -----------------------------------------------------------------------
    print("\n================= CONFIGURATION =================")
    print("Script scope")
    print("  Chunked SNR-ranked generic CPA attack for ASCON SW")
    print("  Full trace matrix is NOT loaded into RAM")
    print()
    print(f"DOJO_ROOT                  : {DOJO_ROOT}")
    print()
    print("Target")
    print(f"  S-box used               : {sbox_type}")
    print(f"  Requested traces         : {n_trc:,}")
    print(f"  Traces in file           : {total_traces:,}")
    print(f"  Used traces              : {n_used:,}")
    print(f"  Samples per trace        : {n_samples}")
    print(f"  Traceset size in name    : {traceset_size_k}k")
    print()
    print("Compute")
    print(f"  compute_device           : {compute_device}")
    print(f"  CPA backend              : {cpa_backend}")
    print(f"  Leakage polarity         : {leakage_polarity}")
    print(f"  CuPy available           : {CUPY_AVAILABLE}")
    if not CUPY_AVAILABLE and CUPY_ERROR is not None:
        print(f"  CuPy error               : {CUPY_ERROR}")
    print(f"  CPU workers/threads      : {max_cpu_workers}")
    print(f"  Chunk size               : {chunk_size}")
    print(f"  CPA sample window        : {cpa_sample_window if cpa_sample_window > 0 else 'full trace'}")
    print()
    print("Paths")
    print(f"  Traceset file            : {trace_file}")
    print(f"  SNR ranked file          : {snr_file}")
    print(f"  SNR trace file           : {snr_trace_file}")
    print(f"  Plot dir                 : {plot_dir}")
    print(f"  CPA cache file           : {cpa_cache_file}")
    print()
    print("Metadata")
    print(f"  Sampling interval        : {sampling_interval}")
    print(f"  Key                      : 0x{key_hex}")
    print(f"  IV                       : 0x{iv_hex}")
    print(f"  Initial nonce            : 0x{nonce_original_hex}")
    print("=================================================\n")

    # -----------------------------------------------------------------------
    # Key display
    # -----------------------------------------------------------------------
    k0_bytes_le = [f"{b:02X}" for b in k0_int.to_bytes(8, "little")]
    k1_bytes_le = [f"{b:02X}" for b in k1_int.to_bytes(8, "little")]

    print("\n[INFO] Key halves by byte")
    label_width = 12
    byte_indices = list(range(7, -1, -1))
    print(f"{'':<{label_width}}" + "  " + "  ".join(f"{b:>2}" for b in byte_indices))
    print(f"{'k0':<{label_width}}" + "  " + "  ".join(f"{b:>2}" for b in k0_bytes_le))
    print(f"{'k1':<{label_width}}" + "  " + "  ".join(f"{b:>2}" for b in k1_bytes_le))

    if verbose:
        print_key_bits("k0", k0_bits)
        print_key_bits("k1", k1_bits)

    # -----------------------------------------------------------------------
    # Load SNR-ranked targets
    # -----------------------------------------------------------------------
    try:
        peak_samples = load_snr_peak_samples(snr_trace_file) if cpa_sample_window > 0 else {}
        if cpa_sample_window > 0 and not peak_samples:
            print(
                "[WARN] CPA sample window requested, but no SNR peak samples "
                "were available. Falling back to full trace samples."
            )
            effective_sample_window = 0
        else:
            effective_sample_window = cpa_sample_window

        attacked_targets = load_snr_ranked_targets(
            snr_file,
            max_targets=max_targets_to_attack,
            peak_samples=peak_samples,
        )
    except Exception as e:
        print(f"[ERROR] Could not read SNR ranked file: {e}")
        return

    print(f"\n[INFO] Loaded {len(attacked_targets)} SNR-ranked targets from {snr_file}")

    if len(attacked_targets) == 0:
        print("[ERROR] No valid attacked targets were loaded.")
        return

    regs_present = sorted(set(t["reg"] for t in attacked_targets))
    print(f"[INFO] Registers present in SNR target list: {regs_present}")

    if verbose:
        top_n = min(10, len(attacked_targets))
        print("[INFO] Top targets:")
        for i in range(top_n):
            t = attacked_targets[i]
            peak_str = (
                f"  peak_sample={t['snr_peak_sample']}"
                if "snr_peak_sample" in t else ""
            )
            print(f"  {i:3d}: {t['reg']}[{t['bit']}]  SNR={t['snr']:.6g}{peak_str}")

    # -----------------------------------------------------------------------
    # Recovery containers
    # -----------------------------------------------------------------------
    k0_rec_bits = np.zeros(64, dtype=np.uint8)
    k0_rec = np.zeros(64, dtype=bool)

    k1_rec_bits = np.zeros(64, dtype=np.uint8)
    k1_rec = np.zeros(64, dtype=bool)

    k0_xor_k1_rec_bits = np.zeros(64, dtype=np.uint8)
    k0_xor_k1_rec = np.zeros(64, dtype=bool)

    tic = time.perf_counter()
    print("\n=== Recovering k0 and k1 using chunked SNR-ranked targets ===\n")

    attack_log = []

    # -----------------------------------------------------------------------
    # Chunked attack loop
    # -----------------------------------------------------------------------
    for t in tqdm(attacked_targets, desc="Attack targets, chunked CPA"):
        if np.all(k0_rec) and np.all(k1_rec):
            print("[INFO] Full k0 and k1 recovered. Stopping early.")
            break

        attacked_state_reg = t["reg"]
        attacked_bit = t["bit"]
        sample_start, sample_stop = target_sample_window(
            t,
            n_samples,
            effective_sample_window,
        )

        k_idx = target_to_k_idx(attacked_state_reg, attacked_bit)

        if not _target_is_useful(k_idx, k0_rec, k1_rec, k0_xor_k1_rec):
            if verbose:
                print(f"\n[INFO] Skipping {attacked_state_reg}[{attacked_bit}] because no new bits are expected.")
            continue

        try:
            res = attack_one_target_chunked(
                trace_file=trace_file,
                nonces=nonces,
                n_used=n_used,
                n_samples=n_samples,
                iv_int=iv_int,
                attacked_state_reg=attacked_state_reg,
                attacked_bit=attacked_bit,
                sbox_type=sbox_type,
                chunk_size=chunk_size,
                cpa_backend=cpa_backend,
                sample_start=sample_start,
                sample_stop=sample_stop,
            )
        except Exception as e:
            print(f"[ERROR] Attack failed for {attacked_state_reg}[{attacked_bit}]: {e}")
            raise

        commit_attack_result(
            res,
            k0_bits,
            k1_bits,
            k0_rec_bits,
            k0_rec,
            k1_rec_bits,
            k1_rec,
            k0_xor_k1_rec_bits,
            k0_xor_k1_rec,
            verbose=verbose,
        )

        attack_log.append(
            {
                "target": f"{attacked_state_reg}[{attacked_bit}]",
                "snr": t["snr"],
                "best_group_idx": res.get("best_group_idx"),
                "best_corr": res.get("best_corr"),
                "best_sample": res.get("best_sample"),
                "sample_start": res.get("sample_start"),
                "sample_stop": res.get("sample_stop"),
                "n_cpa_samples": res.get("n_cpa_samples"),
                "num_groups": res.get("num_groups"),
                "k0_recovered": int(np.sum(k0_rec)),
                "k1_recovered": int(np.sum(k1_rec)),
                "kx_recovered": int(np.sum(k0_xor_k1_rec)),
            }
        )

        print(
            f"[INFO] Progress: "
            f"k0={np.sum(k0_rec)}/64, "
            f"k1={np.sum(k1_rec)}/64, "
            f"k0_xor_k1={np.sum(k0_xor_k1_rec)}/64"
        )

    toc = time.perf_counter()
    print(f"\n[INFO] Key recovery attack completed in {(toc - tic) / 60:.2f} minutes.")

    # -----------------------------------------------------------------------
    # Final key check
    # -----------------------------------------------------------------------
    k0_rec_int = bits_to_u64(k0_rec_bits)
    k1_rec_int = bits_to_u64(k1_rec_bits)

    print("\n================= KEY CHECK =================")
    print(f"[INFO] Expected k0 : 0x{k0_int:016X}")
    print(f"[INFO] Recovered k0: 0x{k0_rec_int:016X}  ({np.sum(k0_rec)}/64 bits recovered)")

    print(f"[INFO] Expected k1 : 0x{k1_int:016X}")
    print(f"[INFO] Recovered k1: 0x{k1_rec_int:016X}  ({np.sum(k1_rec)}/64 bits recovered)")

    k0_correct = int(np.sum((k0_rec_bits == k0_bits) & k0_rec))
    k1_correct = int(np.sum((k1_rec_bits == k1_bits) & k1_rec))

    print("[INFO] Correct recovered bits:")
    print(f"       k0: {k0_correct}/{int(np.sum(k0_rec))} correct among recovered")
    print(f"       k1: {k1_correct}/{int(np.sum(k1_rec))} correct among recovered")

    if np.all(k0_rec) and np.all(k1_rec):
        ok = (k0_rec_int == k0_int) and (k1_rec_int == k1_int)
        print(f"[INFO] Full key match: {'YES' if ok else 'NO'}")
    else:
        print("[INFO] Full key match: N/A, not all bits recovered")

    print("=============================================\n")

    # -----------------------------------------------------------------------
    # Save result summary
    # -----------------------------------------------------------------------
    if save_results or save_attack_results:
        result = {
            "sbox_type": sbox_type,
            "n_traces": int(n_used),
            "n_samples": int(n_samples),
            "chunk_size": int(chunk_size),
            "cpa_sample_window_requested": int(cpa_sample_window),
            "cpa_sample_window_effective": int(effective_sample_window),
            "compute_device": compute_device,
            "cpa_backend": cpa_backend,
            "leakage_polarity": leakage_polarity,
            "cupy_available": bool(CUPY_AVAILABLE),
            "cpu_threads": int(max_cpu_workers),
            "snr_file": str(snr_file),
            "snr_trace_file": str(snr_trace_file),
            "trace_file": str(trace_file),
            "expected_k0_hex": f"{k0_int:016X}",
            "expected_k1_hex": f"{k1_int:016X}",
            "recovered_k0_hex": f"{k0_rec_int:016X}",
            "recovered_k1_hex": f"{k1_rec_int:016X}",
            "k0_recovered_count": int(np.sum(k0_rec)),
            "k1_recovered_count": int(np.sum(k1_rec)),
            "k0_xor_k1_recovered_count": int(np.sum(k0_xor_k1_rec)),
            "k0_correct_recovered_count": int(k0_correct),
            "k1_correct_recovered_count": int(k1_correct),
            "full_key_match": bool((k0_rec_int == k0_int) and (k1_rec_int == k1_int))
            if (np.all(k0_rec) and np.all(k1_rec)) else None,
            "registers_in_snr_file": regs_present,
            "attack_log": attack_log,
        }

        with open(cpa_cache_file, "w") as f:
            json.dump(result, f, indent=2)

        print(f"[INFO] Saved attack result summary to: {cpa_cache_file}")


if __name__ == "__main__":
    main()
