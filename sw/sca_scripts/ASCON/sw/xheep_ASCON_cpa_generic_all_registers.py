#!/usr/bin/env python3
"""
ASCON generic leakage CPA attack using SNR-ranked target bits.

Memory-friendly / chunked version.

This script:
  - when run directly, executes all seven S-boxes for negative/positive/both
  - loads only metadata from the trace HDF5 file
  - loads SNR-ranked attack targets for x0..x4
  - attacks targets in key-dependency-aware order
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
import csv
import subprocess
from datetime import datetime, timezone
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
trace_sbox_type = os.environ.get("ASCON_TRACE_SBOX_TYPE", sbox_type)
leakage_model_sbox = os.environ.get("ASCON_LEAKAGE_MODEL_SBOX", sbox_type)
analysis_name = (
    trace_sbox_type
    if trace_sbox_type == leakage_model_sbox
    else f"{trace_sbox_type}__model_{leakage_model_sbox}"
)

cpa_recovery_policy = (
    os.environ.get("ASCON_CPA_POLICY", "dependency_aware")
    .strip()
    .lower()
    .replace("-", "_")
)
if cpa_recovery_policy in {"dependency", "dependencyaware", "equation_aware"}:
    cpa_recovery_policy = "dependency_aware"
elif cpa_recovery_policy in {"generic", "normal"}:
    cpa_recovery_policy = "baseline"
if cpa_recovery_policy not in {"dependency_aware", "baseline"}:
    raise ValueError("ASCON_CPA_POLICY must be one of: dependency_aware, baseline")

# Number of traces to use. The script uses min(n_trc, traces_in_file).
n_trc = int(os.environ.get("ASCON_N_TRC", "1000000"))

# If the trace filename is based on a different size, change this.
# Example:
#   traceset_size_k = 150
# gives:
#   ascon_opt32_lut_lu_7_150k.h5
traceset_size_k = int(os.environ.get("ASCON_TRACESET_SIZE_K", str(n_trc // 1000)))

# Chunk size for trace reading.
# Reduce if memory is high. Increase if I/O overhead is high.
chunk_size = int(os.environ.get("ASCON_CHUNK_SIZE", "20000"))

# Optional sample-window acceleration.
# 0 means full trace width. A positive value uses only that many samples around
# the target's SNR peak sample, if the matching snr_traces_*.h5 file exists.
# The previous fast CPA runs used 201 samples; keep that as the default because
# full-width CPA processes about 57x more samples for the current tracesets.
cpa_sample_window = int(os.environ.get("ASCON_CPA_SAMPLE_WINDOW", "201"))
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

# Standard CPA selects the best known-key-compatible mixed group. Larger values
# can be used for conservative exploratory runs, but they also keep extra
# alternatives and can prevent later k1/k0 derivation from becoming unique.
mixed_top_groups = int(os.environ.get("ASCON_MIXED_TOP_GROUPS", "1"))
if mixed_top_groups < 1:
    raise ValueError("ASCON_MIXED_TOP_GROUPS must be >= 1")

mixed_min_fact_support = int(os.environ.get("ASCON_MIXED_MIN_FACT_SUPPORT", "2"))
if mixed_min_fact_support < 1:
    raise ValueError("ASCON_MIXED_MIN_FACT_SUPPORT must be >= 1")

# Flow flags.
verbose = True
debug_k_idx = 30

# Save result JSON.
save_attack_results = True
save_results = True
run_result_file_env = os.environ.get("ASCON_RUN_RESULT_FILE")
progress_bars_enabled = os.environ.get("ASCON_PROGRESS_BARS", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}

ALL_SBOXES = (
    "lut_ascon",
    "lut_bilgin",
    "lut_allouzi",
    "lut_lu_4",
    "lut_lu_5",
    "lut_lu_6",
    "lut_lu_7",
)
ALL_POLARITIES = ("negative", "positive", "both")


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


def _repo_relative_path(value, default: Path) -> Path:
    if value in (None, ""):
        return Path(default)
    path = Path(value)
    if not path.is_absolute():
        path = (DOJO_ROOT / path).resolve()
    return path


ASCON_PY_DIR = DOJO_ROOT / "sw" / "ciphers" / "ASCON_init_python"
SCA_DIR = DOJO_ROOT / "sw" / "sca_scripts"

BASE_PLOT_DIR = _repo_relative_path(
    os.environ.get("ASCON_PLOT_DIR"),
    DOJO_ROOT / "sw" / "sca_scripts" / "ASCON" / "sw" / "plot",
)
BASE_CACHE_DIR = _repo_relative_path(
    os.environ.get("ASCON_CACHE_DIR"),
    DOJO_ROOT / "sw" / "sca_scripts" / "ASCON" / "sw" / "cache",
)
TRACESET_DIR = DOJO_ROOT / "sw" / "traceset" / "ASCON" / "sw"

sys.path.insert(0, str(ASCON_PY_DIR))
sys.path.insert(0, str(SCA_DIR))

from analyzer.attack.ascon.xheep_ascon_cpa.ascon_generic_leakage_model import (
    ascon_generic_leakage_matrix,
    expand_reduced_hypotheses,
    get_target_key_dependencies,
    propagate_hypothesis_constraints,
    reduce_full_hypotheses,
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


def _target_is_useful_for_dependencies(
    k_idx: np.ndarray,
    dependencies,
    k0_rec,
    k1_rec,
    k0_xor_k1_rec,
) -> bool:
    """
    Decide usefulness using the selected S-box output's actual key dependency.

    A k0-only target cannot reveal unresolved k1 bits, and vice versa. Mixed
    targets retain the generic relation-aware usefulness check.
    """
    dependencies = tuple(dependencies)
    indices = np.asarray(k_idx, dtype=int)

    if dependencies == ("k0",):
        return not np.all(k0_rec[indices])
    if dependencies == ("k1",):
        return not np.all(k1_rec[indices])
    if dependencies == ("k0", "k1"):
        return _target_is_useful(indices, k0_rec, k1_rec, k0_xor_k1_rec)
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
    hypothesis_mode: str = "reduced",
):
    """
    Compute H matrix for one nonce chunk.

    Output:
        H shape = (chunk_len, 64) in full mode, or False/(chunk_len, 8)/
        (chunk_len, 64) in reduced mode.

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
        hypothesis_mode=hypothesis_mode,
    )

    if H64 is False:
        return False

    return H64.astype(np.uint8, copy=False)


def build_hypothesis_groups_streaming(
    nonces: np.ndarray,
    n_used: int,
    iv_int: int,
    attacked_state_reg: str,
    attacked_bit: int,
    sbox_type: str,
    chunk_size: int,
    hypothesis_mode: str = "reduced",
    target_info=None,
):
    """
    Build complement-equivalence hypothesis groups without loading traces.

    This streams the already loaded nonce array and constructs the binary
    leakage vectors for the selected target. Memory use is roughly:

        n_hypotheses * n_used bytes

    For 1,000,000 traces and 64 hypotheses, this is about 64 MB for signatures.
    """
    hypothesis_mode = str(hypothesis_mode).strip().lower()
    if hypothesis_mode == "full":
        n_hypotheses = 64
    else:
        if target_info is None:
            target_info = get_target_key_dependencies(
                iv_int,
                attacked_state_reg,
                attacked_bit,
                sbox_type,
            )
        n_hypotheses = int(target_info["n_hypotheses"])

    if n_hypotheses == 0:
        return np.empty(0, dtype=np.int64), []

    signatures = [bytearray() for _ in range(n_hypotheses)]

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
            hypothesis_mode=hypothesis_mode,
        )

        if H64 is False:
            return np.empty(0, dtype=np.int64), []

        if H64.shape[1] != n_hypotheses:
            raise ValueError(
                f"Leakage matrix has {H64.shape[1]} columns, expected "
                f"{n_hypotheses} for hypothesis_mode={hypothesis_mode!r}"
            )

        for k in range(n_hypotheses):
            signatures[k].extend(H64[:, k].tobytes())

        del H64

    canonical_to_group = {}
    key_hyp_groups = []
    rep_indices = []

    for k in range(n_hypotheses):
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
    compatible_hypotheses=None,
    dependencies=(),
    target_info=None,
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
    hypothesis_mode = "full" if cpa_recovery_policy == "baseline" else "reduced"

    if target_info is None:
        target_info = get_target_key_dependencies(
            iv_int,
            attacked_state_reg,
            attacked_bit,
            sbox_type,
        )

    dependency_kind = (
        "mixed" if hypothesis_mode == "full" else target_info["dependency_kind"]
    )
    dependencies = tuple(dependencies)
    if hypothesis_mode != "full" and not dependencies:
        dependencies = tuple(target_info["key_dependencies"])
    n_hypotheses = 64 if hypothesis_mode == "full" else int(target_info["n_hypotheses"])

    if n_hypotheses == 0:
        return {
            "attacked_state_reg": attacked_state_reg,
            "attacked_bit": int(attacked_bit),
            "k_idx": k_idx,
            "best_key_group": [],
            "best_key_group_reduced": [],
            "skipped": True,
            "skip_reason": "no nonce-varying key dependency",
            "hypothesis_mode": hypothesis_mode,
            "dependency_kind": target_info["dependency_kind"],
            "n_hypotheses": 0,
            "num_groups": 0,
            "sample_start": int(sample_start),
            "sample_stop": int(sample_stop) if sample_stop is not None else int(n_samples),
        }

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
        hypothesis_mode=hypothesis_mode,
        target_info=target_info,
    )

    n_groups = len(rep_indices)
    if n_groups == 0:
        return {
            "attacked_state_reg": attacked_state_reg,
            "attacked_bit": int(attacked_bit),
            "k_idx": k_idx,
            "best_key_group": [],
            "best_key_group_reduced": [],
            "skipped": True,
            "skip_reason": "no hypothesis groups",
            "hypothesis_mode": hypothesis_mode,
            "dependency_kind": target_info["dependency_kind"],
            "n_hypotheses": int(n_hypotheses),
            "num_groups": 0,
            "sample_start": int(sample_start),
            "sample_stop": int(sample_stop),
            "n_cpa_samples": int(n_cpa_samples),
        }

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
                hypothesis_mode=hypothesis_mode,
            )

            if H64 is False:
                raise RuntimeError(
                    f"No leakage hypotheses for {attacked_state_reg}[{attacked_bit}]"
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
    compatible_full_set = (
        set(range(64))
        if compatible_hypotheses is None
        else set(map(int, compatible_hypotheses))
    )
    if hypothesis_mode == "full":
        compatible_set = compatible_full_set
    else:
        compatible_set = set(
            reduce_full_hypotheses(compatible_full_set, dependency_kind)
        )
    ranked_compatible_groups = []

    for group_idx, group in enumerate(oriented_key_hyp_groups):
        if leakage_polarity == "both":
            oriented_members = group["all"]
        elif leakage_polarity == "positive":
            oriented_members = (
                group["same"]
                if signed_corr[group_idx] > 0.0
                else group["complement"]
            )
        else:
            oriented_members = (
                group["same"]
                if signed_corr[group_idx] < 0.0
                else group["complement"]
            )

        members = [
            int(hypothesis)
            for hypothesis in oriented_members
            if int(hypothesis) in compatible_set
        ]
        polarity_overridden = False

        # Known key facts are stronger than a global leakage-polarity
        # convention. Allow the opposite orientation when it is the only one
        # compatible with already recovered bits.
        if not members:
            members = [
                int(hypothesis)
                for hypothesis in group["all"]
                if int(hypothesis) in compatible_set
            ]
            polarity_overridden = bool(members)

        if members:
            ranked_compatible_groups.append(
                {
                    "group_idx": int(group_idx),
                    "members": members,
                    "corr": float(corr_group[group_idx]),
                    "signed_corr": float(signed_corr[group_idx]),
                    "sample": int(argmax_samples_abs[group_idx]),
                    "polarity_overridden": polarity_overridden,
                }
            )

    ranked_compatible_groups.sort(key=lambda item: item["corr"], reverse=True)
    retained_group_count = mixed_top_groups if len(dependencies) == 2 else 1
    retained_groups = ranked_compatible_groups[:retained_group_count]

    if retained_groups:
        best_group_idx = retained_groups[0]["group_idx"]
        best_key_group_reduced = sorted(
            {
                hypothesis
                for retained_group in retained_groups
                for hypothesis in retained_group["members"]
            }
        )
    else:
        best_group_idx = int(np.argmax(corr_group))
        best_key_group_reduced = []

    if hypothesis_mode == "full":
        best_key_group = best_key_group_reduced
    else:
        best_key_group = expand_reduced_hypotheses(
            best_key_group_reduced,
            dependency_kind,
        )

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
            selected_members=best_key_group_reduced,
        )

    return {
        "attacked_state_reg": attacked_state_reg,
        "attacked_bit": int(attacked_bit),
        "k_idx": k_idx,
        "best_key_group": best_key_group,
        "best_key_group_reduced": best_key_group_reduced,
        "skipped": False,
        "hypothesis_mode": hypothesis_mode,
        "dependency_kind": target_info["dependency_kind"],
        "n_hypotheses": int(n_hypotheses),
        "num_groups": int(n_groups),
        "best_group_idx": best_group_idx,
        "best_corr": float(corr_group[best_group_idx]),
        "best_signed_corr": float(signed_corr[best_group_idx]),
        "best_sample": int(argmax_samples_abs[best_group_idx]),
        "retained_group_indices": [
            retained_group["group_idx"] for retained_group in retained_groups
        ],
        "retained_group_correlations": [
            retained_group["corr"] for retained_group in retained_groups
        ],
        "polarity_overridden": any(
            retained_group["polarity_overridden"]
            for retained_group in retained_groups
        ),
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

    This is the generic constraint step: the winning CPA group
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
    commit_bits=True,
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
        if "retained_group_indices" in res:
            print(
                f"[INFO] Retained groups  : "
                f"{res['retained_group_indices']}"
            )
        if res.get("polarity_overridden", False):
            print("[INFO] Known key facts overrode the configured leakage polarity")
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

    if not commit_bits:
        if verbose:
            print(
                "[INFO] Mixed-target candidates stored for cross-target "
                "constraint agreement; no bits committed directly."
            )
        return

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
    trace_file = TRACESET_DIR / f"ascon_opt32_{trace_sbox_type}_{traceset_size_k}k.h5"

    plot_dir = BASE_PLOT_DIR / analysis_name
    cache_dir = BASE_CACHE_DIR / analysis_name

    snr_file = find_snr_file(cache_dir, analysis_name, n_trc)
    snr_trace_file = find_snr_trace_file(cache_dir, analysis_name, n_trc)
    if run_result_file_env:
        cpa_cache_file = Path(run_result_file_env).expanduser()
        if not cpa_cache_file.is_absolute():
            cpa_cache_file = (DOJO_ROOT / cpa_cache_file).resolve()
    else:
        cpa_cache_file = cache_dir / f"CPA_results_chunked_{analysis_name}_{n_trc // 1000}k.json"

    BASE_PLOT_DIR.mkdir(parents=True, exist_ok=True)
    BASE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    plot_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cpa_cache_file.parent.mkdir(parents=True, exist_ok=True)

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
    if cpa_recovery_policy == "baseline":
        print("  Chunked baseline SNR-ranked generic CPA attack for ASCON SW")
    else:
        print("  Chunked key-dependency-aware CPA attack for ASCON SW")
    print("  Full trace matrix is NOT loaded into RAM")
    print()
    print(f"DOJO_ROOT                  : {DOJO_ROOT}")
    print()
    print("Target")
    print(f"  Trace S-box              : {trace_sbox_type}")
    print(f"  Leakage-model S-box      : {leakage_model_sbox}")
    print(f"  Analysis name            : {analysis_name}")
    print(f"  Requested traces         : {n_trc:,}")
    print(f"  Traces in file           : {total_traces:,}")
    print(f"  Used traces              : {n_used:,} (prefix rows 0:{n_used})")
    print(f"  Samples per trace        : {n_samples}")
    print(f"  Traceset size in name    : {traceset_size_k}k")
    print()
    print("Compute")
    print(f"  compute_device           : {compute_device}")
    print(f"  CPA backend              : {cpa_backend}")
    print(f"  CPA recovery policy      : {cpa_recovery_policy}")
    print(f"  Leakage polarity         : {leakage_polarity}")
    if cpa_recovery_policy == "baseline":
        print("  Leakage model            : generic S-box output bits")
        print("  Key relation handling    : generic complement-equivalence groups")
    else:
        print("  Leakage model            : selected equivalent S-box equations")
        print("  Key relation handling    : equivalent dependency constraints")
        print(f"  Mixed retained groups    : {mixed_top_groups}")
        print(f"  Mixed fact support       : {mixed_min_fact_support} targets")
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
            max_targets=None,
            peak_samples=peak_samples,
        )
    except Exception as e:
        print(f"[ERROR] Could not read SNR ranked file: {e}")
        return

    def equation_priority(target):
        target_info = get_target_key_dependencies(
            iv_int,
            target["reg"],
            target["bit"],
            leakage_model_sbox,
        )
        n_hypotheses = int(target_info["n_hypotheses"])
        if n_hypotheses == 8:
            return 0
        if n_hypotheses == 64:
            return 1
        return 2

    if cpa_recovery_policy == "dependency_aware":
        # Stable sort preserves the original SNR order inside each dependency class.
        attacked_targets = sorted(attacked_targets, key=equation_priority)
    if max_targets_to_attack is not None:
        attacked_targets = attacked_targets[: int(max_targets_to_attack)]

    if cpa_recovery_policy == "baseline":
        print(f"\n[INFO] Loaded {len(attacked_targets)} SNR-ranked targets from {snr_file}")
        print("[INFO] Baseline order: raw SNR ranking from the selected leakage model")
    else:
        print(f"\n[INFO] Loaded {len(attacked_targets)} equation-ranked targets from {snr_file}")
        print("[INFO] Equation-aware order: single-key, mixed-key, then no-key dependencies")

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
    equation_constraints = []

    tic = time.perf_counter()
    print("\n=== Recovering k0 and k1 using chunked SNR-ranked targets ===\n")

    attack_log = []

    # -----------------------------------------------------------------------
    # Chunked attack loop
    # -----------------------------------------------------------------------
    for t in tqdm(
        attacked_targets,
        desc="Attack targets, chunked CPA",
        disable=not progress_bars_enabled,
    ):
        if np.all(k0_rec) and np.all(k1_rec):
            print("[INFO] Full k0 and k1 recovered. Stopping early.")
            break

        attacked_state_reg = t["reg"]
        attacked_bit = t["bit"]
        dependencies = ()
        target_info = None
        if cpa_recovery_policy == "dependency_aware":
            target_info = get_target_key_dependencies(
                iv_int,
                attacked_state_reg,
                attacked_bit,
                leakage_model_sbox,
            )
            dependencies = tuple(target_info["key_dependencies"])
            if not dependencies:
                if verbose:
                    print(
                        f"\n[INFO] Skipping {attacked_state_reg}[{attacked_bit}] "
                        "(equivalent equation has no nonce-varying key dependency)"
                    )
                continue
            if verbose:
                print(
                    f"\n[INFO] Equivalent equation for "
                    f"{attacked_state_reg}[{attacked_bit}] depends on: "
                    f"{', '.join(dependencies)} "
                    f"({target_info['n_hypotheses']} hypotheses)"
                )

        sample_start, sample_stop = target_sample_window(
            t,
            n_samples,
            effective_sample_window,
        )

        k_idx = target_to_k_idx(attacked_state_reg, attacked_bit)

        if cpa_recovery_policy == "baseline":
            target_is_useful = _target_is_useful(
                k_idx,
                k0_rec,
                k1_rec,
                k0_xor_k1_rec,
            )
        else:
            target_is_useful = _target_is_useful_for_dependencies(
                k_idx,
                dependencies,
                k0_rec,
                k1_rec,
                k0_xor_k1_rec,
            )

        if not target_is_useful:
            if verbose:
                if cpa_recovery_policy == "baseline":
                    print(
                        f"\n[INFO] Skipping {attacked_state_reg}[{attacked_bit}] "
                        "because no new bits are expected."
                    )
                else:
                    print(
                        f"\n[INFO] Skipping {attacked_state_reg}[{attacked_bit}] "
                        f"because its {', '.join(dependencies)} dependencies are "
                        "already resolved at these indices."
                    )
            continue

        try:
            compatible_hypotheses = None
            if cpa_recovery_policy == "dependency_aware":
                compatible_hypotheses = filter_hypotheses_by_known_bits(
                    range(64),
                    k_idx,
                    k0_rec_bits,
                    k0_rec,
                    k1_rec_bits,
                    k1_rec,
                    k0_xor_k1_rec_bits,
                    k0_xor_k1_rec,
                )
            res = attack_one_target_chunked(
                trace_file=trace_file,
                nonces=nonces,
                n_used=n_used,
                n_samples=n_samples,
                iv_int=iv_int,
                attacked_state_reg=attacked_state_reg,
                attacked_bit=attacked_bit,
                sbox_type=leakage_model_sbox,
                chunk_size=chunk_size,
                cpa_backend=cpa_backend,
                sample_start=sample_start,
                sample_stop=sample_stop,
                compatible_hypotheses=compatible_hypotheses,
                dependencies=dependencies,
                target_info=target_info,
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
            commit_bits=(
                cpa_recovery_policy == "baseline" or len(dependencies) == 1
            ),
        )

        if cpa_recovery_policy == "dependency_aware" and res["best_key_group"]:
            equation_constraints.append(
                {
                    "target": (attacked_state_reg, int(attacked_bit)),
                    "dependencies": tuple(dependencies),
                    "key_indices": k_idx.copy(),
                    "hypotheses": list(map(int, res["best_key_group"])),
                }
            )
        if cpa_recovery_policy == "dependency_aware":
            propagate_hypothesis_constraints(
                equation_constraints,
                k0_rec_bits,
                k0_rec,
                k1_rec_bits,
                k1_rec,
                k0_xor_k1_rec_bits,
                k0_xor_k1_rec,
                verbose=verbose,
                minimum_fact_support=mixed_min_fact_support,
            )

        attack_log.append(
            {
                "target": f"{attacked_state_reg}[{attacked_bit}]",
                "equivalent_key_dependencies": list(dependencies),
                "dependency_kind": res.get("dependency_kind"),
                "n_hypotheses": res.get("n_hypotheses"),
                "hypothesis_mode": res.get("hypothesis_mode"),
                "snr": t["snr"],
                "best_group_idx": res.get("best_group_idx"),
                "best_corr": res.get("best_corr"),
                "best_sample": res.get("best_sample"),
                "retained_group_indices": res.get("retained_group_indices"),
                "retained_group_correlations": res.get(
                    "retained_group_correlations"
                ),
                "polarity_overridden": res.get("polarity_overridden"),
                "sample_start": res.get("sample_start"),
                "sample_stop": res.get("sample_stop"),
                "n_cpa_samples": res.get("n_cpa_samples"),
                "num_groups": res.get("num_groups"),
                "k0_recovered": int(np.sum(k0_rec)),
                "k1_recovered": int(np.sum(k1_rec)),
                "kx_recovered": int(np.sum(k0_xor_k1_rec)),
                "equation_constraints": int(len(equation_constraints)),
            }
        )

        print(
            f"[INFO] Progress: "
            f"k0={np.sum(k0_rec)}/64, "
            f"k1={np.sum(k1_rec)}/64, "
            f"k0_xor_k1={np.sum(k0_xor_k1_rec)}/64"
            + (
                f", equation_constraints={len(equation_constraints)}"
                if cpa_recovery_policy == "dependency_aware"
                else ""
            )
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
            "sbox_type": analysis_name,
            "trace_sbox_type": trace_sbox_type,
            "leakage_model_sbox": leakage_model_sbox,
            "analysis_name": analysis_name,
            "n_traces": int(n_used),
            "n_samples": int(n_samples),
            "chunk_size": int(chunk_size),
            "cpa_sample_window_requested": int(cpa_sample_window),
            "cpa_sample_window_effective": int(effective_sample_window),
            "compute_device": compute_device,
            "cpa_backend": cpa_backend,
            "cpa_recovery_policy": cpa_recovery_policy,
            "leakage_polarity": leakage_polarity,
            "leakage_model": (
                "generic-sbox-output-bits"
                if cpa_recovery_policy == "baseline"
                else "selected-equivalent-sbox-equations"
            ),
            "trace_selection": "prefix-from-start",
            "key_relation_handling": (
                "generic-complement-equivalence-groups"
                if cpa_recovery_policy == "baseline"
                else "equivalent-dependency-constraints"
            ),
            "mixed_top_groups": int(mixed_top_groups),
            "mixed_min_fact_support": int(mixed_min_fact_support),
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
            "equation_constraints": [
                {
                    "target": f"{constraint['target'][0]}[{constraint['target'][1]}]",
                    "dependencies": list(constraint.get("dependencies", ())),
                    "key_indices": [
                        int(index) for index in constraint["key_indices"]
                    ],
                    "remaining_hypotheses": [
                        int(hypothesis) for hypothesis in constraint["hypotheses"]
                    ],
                    "conflict": bool(constraint.get("conflict", False)),
                    "overlap_conflict": bool(
                        constraint.get("overlap_conflict", False)
                    ),
                }
                for constraint in equation_constraints
            ],
            "attack_log": attack_log,
        }

        temporary_file = cpa_cache_file.with_suffix(cpa_cache_file.suffix + ".tmp")
        with open(temporary_file, "w") as f:
            json.dump(result, f, indent=2)
            f.write("\n")
        temporary_file.replace(cpa_cache_file)

        print(f"[INFO] Saved attack result summary to: {cpa_cache_file}")


def _write_json_atomic(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _write_all_config_manifests(output_dir: Path, records) -> None:
    _write_json_atomic(output_dir / "manifest.json", records)
    columns = (
        "sbox_type",
        "polarity",
        "status",
        "exit_code",
        "started_at",
        "finished_at",
        "elapsed_seconds",
        "log_file",
        "result_file",
    )
    temporary = output_dir / "manifest.csv.tmp"
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for record in records:
            writer.writerow({column: record.get(column) for column in columns})
    temporary.replace(output_dir / "manifest.csv")


def run_all_sboxes_and_polarities() -> int:
    """
    Run exactly 7 S-boxes x 3 leakage-polarity configurations.

    Child processes set ASCON_SINGLE_RUN=1 and execute main() above. Keeping
    each configuration in a child process isolates GPU/CPU resources and makes
    every log/result independently resumable and inspectable.
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_env = os.environ.get("ASCON_ALL_RUNS_OUTPUT_DIR")
    output_dir = (
        Path(output_env).expanduser()
        if output_env
        else BASE_CACHE_DIR / "cpa_generic_dependency_all_configs" / timestamp
    )
    if not output_dir.is_absolute():
        output_dir = (DOJO_ROOT / output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    dry_run = os.environ.get("ASCON_ALL_RUNS_DRY_RUN", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    records = []
    script_path = Path(__file__).resolve()
    batch_log_path = output_dir / "all_configs.log"

    config = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "script": str(script_path),
        "key_relation_handling": "equivalent-dependency-constraints",
        "sboxes": list(ALL_SBOXES),
        "polarities": list(ALL_POLARITIES),
        "total_analyses": len(ALL_SBOXES) * len(ALL_POLARITIES),
        "n_traces": int(n_trc),
        "traceset_size_k": int(traceset_size_k),
        "cpa_sample_window": int(cpa_sample_window),
        "mixed_top_groups": int(mixed_top_groups),
        "mixed_min_fact_support": int(mixed_min_fact_support),
        "dry_run": dry_run,
    }
    _write_json_atomic(output_dir / "all_configs.json", config)
    total_analyses = len(ALL_SBOXES) * len(ALL_POLARITIES)

    with batch_log_path.open("a", encoding="utf-8") as batch_log:
        for analysis_index, (selected_sbox, selected_polarity) in enumerate(
            (
                (candidate_sbox, candidate_polarity)
                for candidate_sbox in ALL_SBOXES
                for candidate_polarity in ALL_POLARITIES
            ),
            start=1,
        ):
            run_dir = output_dir / selected_sbox / selected_polarity
            run_dir.mkdir(parents=True, exist_ok=True)
            log_file = run_dir / "run.log"
            result_file = run_dir / "result.json"
            started_at = datetime.now(timezone.utc).isoformat()
            start = time.monotonic()

            message = (
                f"[{analysis_index}/{total_analyses}] Starting {selected_sbox} "
                f"with polarity={selected_polarity}"
            )
            print(message, flush=True)
            batch_log.write(message + "\n")
            batch_log.flush()

            environment = os.environ.copy()
            environment.update(
                {
                    "ASCON_SINGLE_RUN": "1",
                    "ASCON_SBOX_TYPE": selected_sbox,
                    "ASCON_LEAKAGE_POLARITY": selected_polarity,
                    "ASCON_RUN_RESULT_FILE": str(result_file),
                    "ASCON_PROGRESS_BARS": "0",
                    "PYTHONUNBUFFERED": "1",
                }
            )

            if dry_run:
                exit_code = None
                status = "dry_run"
                log_file.write_text(
                    "\n".join(
                        [
                            "DRY RUN",
                            f"ASCON_SBOX_TYPE={selected_sbox}",
                            f"ASCON_LEAKAGE_POLARITY={selected_polarity}",
                            f"ASCON_RUN_RESULT_FILE={result_file}",
                        ]
                    )
                    + "\n",
                    encoding="utf-8",
                )
            else:
                with log_file.open("w", encoding="utf-8") as run_log:
                    completed = subprocess.run(
                        [sys.executable, str(script_path)],
                        cwd=DOJO_ROOT,
                        env=environment,
                        stdout=run_log,
                        stderr=subprocess.STDOUT,
                        check=False,
                    )
                exit_code = int(completed.returncode)
                if exit_code != 0:
                    status = "failed"
                elif result_file.exists():
                    status = "success"
                else:
                    status = "failed_missing_result"

            elapsed_seconds = time.monotonic() - start
            record = {
                "sbox_type": selected_sbox,
                "polarity": selected_polarity,
                "status": status,
                "exit_code": exit_code,
                "started_at": started_at,
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "elapsed_seconds": elapsed_seconds,
                "log_file": str(log_file),
                "result_file": str(result_file),
            }
            records.append(record)
            _write_all_config_manifests(output_dir, records)

            message = (
                f"[{analysis_index}/21] Finished {selected_sbox} "
                f"with polarity={selected_polarity}: {status}, "
                f"{elapsed_seconds:.1f}s"
            )
            print(message, flush=True)
            batch_log.write(message + "\n")
            batch_log.flush()

    print(f"[INFO] All-configuration logs and results: {output_dir}")
    return 1 if any(record["status"].startswith("failed") for record in records) else 0


if __name__ == "__main__":
    if os.environ.get("ASCON_SINGLE_RUN") == "1":
        main()
    else:
        raise SystemExit(run_all_sboxes_and_polarities())
