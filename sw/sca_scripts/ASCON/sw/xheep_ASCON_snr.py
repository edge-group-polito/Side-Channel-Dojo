#!/usr/bin/env python3
# =====================================================================
# ASCON SNR ranking (all bits, SW traces) -- streaming/chunked version
#
# This script computes the Signal-to-Noise Ratio (SNR) for all 64 bits of
# all five ASCON state words S0..S4, mapped here as x0..x4, at the end
# of the first permutation round.
#
# It is designed for large HDF5 trace files, e.g., tens of GB.
#
# Important:
#   - It does NOT load all traces into RAM.
#   - It reads traces/nonces chunk by chunk.
#   - It accumulates sufficient statistics for binary bit-level SNR.
#   - It saves:
#       1. ranked peak SNR results
#       2. full SNR traces for every register and bit
#
# Output ranked file:
#   /ranked/register   : UTF-8 strings ("x0".."x4")
#   /ranked/bit        : uint16 bit index (0..63)
#   /ranked/snr        : float32 peak SNR value
#
# Output full SNR file:
#   /snr_traces/value          : float32 array, shape (5, 64, n_samples)
#   /snr_traces/register_names : UTF-8 strings ("x0".."x4")
#   /snr_traces/bits           : uint16 array, 0..63
#   /snr_traces/sample_index   : uint32 array, 0..n_samples-1
# =====================================================================

import argparse
import os

# ---------------------------------------------------------------------------
# CPU configuration
# ---------------------------------------------------------------------------
_pre_parser = argparse.ArgumentParser(add_help=False)
_pre_parser.add_argument("--max-cpu-workers", type=int, default=None)
_pre_args, _ = _pre_parser.parse_known_args()

_max_cpu_workers_env = os.environ.get("ASCON_MAX_CPU_WORKERS")
if _pre_args.max_cpu_workers is not None:
    max_cpu_workers = int(_pre_args.max_cpu_workers)
elif _max_cpu_workers_env not in (None, ""):
    max_cpu_workers = int(_max_cpu_workers_env)
else:
    max_cpu_workers = os.cpu_count() or 1

# These affect NumPy / BLAS / OpenMP-backed operations.
# They must be set before importing NumPy.
os.environ["OMP_NUM_THREADS"] = str(max_cpu_workers)
os.environ["OPENBLAS_NUM_THREADS"] = str(max_cpu_workers)
os.environ["MKL_NUM_THREADS"] = str(max_cpu_workers)
os.environ["VECLIB_MAXIMUM_THREADS"] = str(max_cpu_workers)
os.environ["NUMEXPR_NUM_THREADS"] = str(max_cpu_workers)

import sys
from pathlib import Path

import numpy as np
import h5py
from tqdm import tqdm


def _progress_bars_enabled() -> bool:
    value = os.environ.get("ASCON_PROGRESS_BARS")
    if value in (None, ""):
        return sys.stderr.isatty()
    return value.strip().lower() not in {"0", "false", "no", "off"}


TQDM_DISABLE = not _progress_bars_enabled()


try:
    import cupy as cp
    CUPY_AVAILABLE = True
    CUPY_ERROR = None
except Exception as e:
    cp = None
    CUPY_AVAILABLE = False
    CUPY_ERROR = str(e)

# ---------------------------------------------------------------------------
# Script configuration
# ---------------------------------------------------------------------------
def _env_flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value in (None, ""):
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _parse_args():
    parser = argparse.ArgumentParser(
        description="Compute ASCON bit-level SNR caches for x0..x4.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--sbox",
        default=os.environ.get("ASCON_SBOX_TYPE", "lut_ascon"),
        help="S-box implementation name.",
    )
    parser.add_argument(
        "--n-traces",
        type=int,
        default=int(os.environ.get("ASCON_N_TRC", "1000000")),
        help="Number of prefix traces used for SNR.",
    )
    parser.add_argument(
        "--traceset-size-k",
        type=int,
        default=(
            int(os.environ["ASCON_TRACESET_SIZE_K"])
            if os.environ.get("ASCON_TRACESET_SIZE_K") not in (None, "")
            else None
        ),
        help="Trace-file size tag in thousands, e.g. 1000 for *_1000k.h5.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=int(os.environ.get("ASCON_CHUNK_SIZE", "10000")),
        help="Streaming chunk size.",
    )
    parser.add_argument(
        "--device",
        choices=["cpu", "gpu", "auto"],
        default=os.environ.get("ASCON_SNR_DEVICE", "cpu"),
        help="Requested compute device. CPU is recommended for this streaming SNR.",
    )
    parser.add_argument(
        "--chunk-dtype",
        choices=["float32", "float64"],
        default=os.environ.get("ASCON_SNR_CHUNK_DTYPE", "float64"),
        help="Working dtype inside each SNR chunk.",
    )
    parser.add_argument(
        "--max-cpu-workers",
        type=int,
        default=max_cpu_workers,
        help="NumPy/BLAS thread limit. Parsed early before NumPy import.",
    )
    parser.set_defaults(
        save_ranked=_env_flag("ASCON_SAVE_SNR_RANKED", True),
        save_traces=_env_flag("ASCON_SAVE_SNR_TRACES", True),
        debug=_env_flag("ASCON_SNR_DEBUG", False),
    )
    parser.add_argument("--save-ranked", dest="save_ranked", action="store_true")
    parser.add_argument("--no-save-ranked", dest="save_ranked", action="store_false")
    parser.add_argument("--save-traces", dest="save_traces", action="store_true")
    parser.add_argument("--no-save-traces", dest="save_traces", action="store_false")
    parser.add_argument("--debug", dest="debug", action="store_true")
    parser.add_argument("--no-debug", dest="debug", action="store_false")
    return parser.parse_args()


ARGS = _parse_args()

# Supported S-box types:
#   lut_ascon, lut_bilgin, lut_allouzi, lut_lu_4, lut_lu_5, lut_lu_6, lut_lu_7
sbox_type = ARGS.sbox

# Number of traces to analyze. The script will use min(n_trc, traces_in_file).
n_trc = int(ARGS.n_traces)

# If your file name is not based on n_trc, set this separately.
# Example:
#   traceset_size_k = 150
# gives:
#   ascon_opt32_lut_lu_4_150k.h5
#
# If your real file is ascon_opt32_lut_lu_4_1000k.h5, but you only want to
# compute SNR from a prefix such as 1k traces, use --traceset-size-k 1000.
traceset_size_k = int(ARGS.traceset_size_k or (n_trc // 1000))

# Chunk size for streaming.
# Reduce this if RAM usage is too high.
# Typical safe values: 2_000, 5_000, 10_000, 20_000
chunk_size = int(ARGS.chunk_size)

# Output control
save_snr_ranked_all_bits = bool(ARGS.save_ranked)
save_snr_traces_all_bits = bool(ARGS.save_traces)

# Flow flags
debug = bool(ARGS.debug)

# Compute device:
# For this streaming version, CPU is recommended.
# GPU support is intentionally not used by default because 50 GB files should
# not be copied to GPU memory in full.
compute_device = ARGS.device   # "cpu" recommended

# Numeric precision used while processing each chunk.
# float64 is safer for SNR accumulation but uses more RAM per chunk.
# float32 is lighter but slightly less numerically stable.
chunk_work_dtype = np.float64 if ARGS.chunk_dtype == "float64" else np.float32

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

TRACESET_FILE = TRACESET_DIR / f"ascon_opt32_{sbox_type}_{traceset_size_k}k.h5"

CACHE_DIR = BASE_CACHE_DIR / sbox_type
SNR_OUT_FILE = CACHE_DIR / f"snr_ranked_{sbox_type}_{n_trc // 1000}k.h5"
SNR_TRACE_OUT_FILE = CACHE_DIR / f"snr_traces_{sbox_type}_{n_trc // 1000}k.h5"

BASE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
TRACESET_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Make local modules importable
sys.path.insert(0, str(ASCON_PY_DIR))
sys.path.insert(0, str(SCA_DIR))

from analyzer.attack.ascon.xheep_ascon_cpa.ascon_first_round import ascon_first_round

# ---------------------------------------------------------------------------
# Read only metadata first
# ---------------------------------------------------------------------------
try:
    with h5py.File(TRACESET_FILE, "r") as f_read:
        if "traces" not in f_read or "nonces" not in f_read:
            raise KeyError("HDF5 file is missing required datasets 'traces' and/or 'nonces'.")

        traces_ds = f_read["traces"]
        nonces_ds = f_read["nonces"]

        total_traces = int(traces_ds.shape[0])
        n_samples = int(traces_ds.shape[1])

        sampling_interval = f_read.attrs.get("sampling_interval", None)
        key_hex = f_read.attrs.get("key_hex", None)
        iv_hex = f_read.attrs.get("iv_hex", None)

        n_used = min(n_trc, total_traces)

except FileNotFoundError:
    raise SystemExit(
        f"[ERROR] Traces file {TRACESET_FILE} not found. "
        "Please check traceset_size_k, sbox_type, and TRACESET_DIR."
    )
except Exception as e:
    raise SystemExit(f"[ERROR] Could not read traces file {TRACESET_FILE}: {e}")

n_trc_requested = n_trc
n_trc = n_used

if key_hex is None:
    raise SystemExit("[ERROR] HDF5 attribute 'key_hex' not found. Cannot compute ASCON state labels.")

# ---------------------------------------------------------------------------
# Key setup: endianness match with C
# ---------------------------------------------------------------------------
key_bytes = [key_hex[i:i + 2] for i in range(0, len(key_hex), 2)]
key_reversed = "".join(key_bytes[::-1])
key_int = int(key_reversed, 16)

# ---------------------------------------------------------------------------
# Print configuration
# ---------------------------------------------------------------------------
print("\n================= CONFIGURATION =================")
print("Script scope")
print("  ASCON bit-level SNR computation for all x0..x4 bits")
print("  Streaming/chunked mode: full trace matrix is NOT loaded into RAM")
print()
print(f"DOJO_ROOT                 : {DOJO_ROOT}")
print()
print("Target")
print(f"  Cipher                  : ASCON")
print(f"  S-box implementation    : {sbox_type}")
print(f"  Scope                   : all bits of x0, x1, x2, x3, x4")
print()
print("Paths")
print(f"  Traceset file           : {TRACESET_FILE}")
print(f"  SNR ranked write to     : {SNR_OUT_FILE}")
print(f"  SNR traces write to     : {SNR_TRACE_OUT_FILE}")
print()
print("Trace information")
print(f"  Traces in file          : {total_traces}")
print(f"  Requested traces        : {n_trc_requested}")
print(f"  Analyzed traces         : {n_trc}")
print(f"  Samples per trace       : {n_samples}")
print(f"  Sampling interval       : {sampling_interval}")
print(f"  Key                     : 0x{key_hex}")
if iv_hex is not None:
    print(f"  IV                      : 0x{iv_hex}")
else:
    print("  IV                      : not found")
print()
print("Compute")
print(f"  Compute device requested: {compute_device}")
print(f"  CuPy available          : {CUPY_AVAILABLE}")
if not CUPY_AVAILABLE and CUPY_ERROR is not None:
    print(f"  CuPy error              : {CUPY_ERROR}")
print(f"  CPU workers/threads     : {max_cpu_workers}")
print(f"  Chunk size              : {chunk_size}")
print(f"  Chunk work dtype        : {chunk_work_dtype}")
print("=================================================\n")

# ---------------------------------------------------------------------------
# Helpers for streaming SNR
# ---------------------------------------------------------------------------
reg_names = ["x0", "x1", "x2", "x3", "x4"]
n_regs = 5
n_bits = 64
n_targets = n_regs * n_bits


def compute_state_chunk(nonces_chunk: np.ndarray) -> np.ndarray:
    """
    Compute ASCON first-round states for one chunk of nonces.

    Parameters
    ----------
    nonces_chunk : array-like, shape (chunk_len, 2)
        Captured nonce layout:
            nonces[:, 0] = S4 / nonce LSB half used by CPA
            nonces[:, 1] = S3 / nonce MSB half used by CPA

    Returns
    -------
    states : np.ndarray, shape (chunk_len, 5), dtype uint64
        First-round ASCON state words x0..x4.
    """
    chunk_len = nonces_chunk.shape[0]
    states = np.empty((chunk_len, 5), dtype=np.uint64)

    for i in range(chunk_len):
        # ascon_first_round() loads S[3] from nonce low 64 bits and S[4]
        # from nonce high 64 bits, so reconstruct the integer as S4:S3.
        nonce = (int(nonces_chunk[i][0]) << 64) | int(nonces_chunk[i][1])
        S = ascon_first_round(key_int, nonce, sbox_type)

        states[i, 0] = np.uint64(S[0])
        states[i, 1] = np.uint64(S[1])
        states[i, 2] = np.uint64(S[2])
        states[i, 3] = np.uint64(S[3])
        states[i, 4] = np.uint64(S[4])

    return states


def build_labels_flat(states: np.ndarray, dtype=np.float64) -> np.ndarray:
    """
    Build binary labels for all 5 registers and all 64 bits.

    Output shape:
        (chunk_len, 320)

    Target mapping:
        target = reg_i * 64 + bit_i

    where:
        reg_i = 0 -> x0
        reg_i = 1 -> x1
        reg_i = 2 -> x2
        reg_i = 3 -> x3
        reg_i = 4 -> x4
    """
    chunk_len = states.shape[0]
    labels = np.empty((chunk_len, n_targets), dtype=dtype)

    target = 0
    for reg_i in range(n_regs):
        word = states[:, reg_i]
        for bit_i in range(n_bits):
            labels[:, target] = ((word >> np.uint64(bit_i)) & np.uint64(1)).astype(dtype)
            target += 1

    return labels


# ---------------------------------------------------------------------------
# Allocate accumulators
# ---------------------------------------------------------------------------
# These arrays are small compared to the full trace matrix:
#   total_sum   : (n_samples,)
#   total_sumsq : (n_samples,)
#   sum1        : (320, n_samples)
#   sumsq1      : (320, n_samples)
#   count1      : (320,)
#
# They are sufficient to compute binary SNR after streaming.
total_sum = np.zeros(n_samples, dtype=np.float64)
total_sumsq = np.zeros(n_samples, dtype=np.float64)

sum1 = np.zeros((n_targets, n_samples), dtype=np.float64)
sumsq1 = np.zeros((n_targets, n_samples), dtype=np.float64)

count1 = np.zeros(n_targets, dtype=np.float64)

# ---------------------------------------------------------------------------
# Streaming accumulation pass
# ---------------------------------------------------------------------------
print(f"[INFO] Streaming traces in chunks of {chunk_size}")
print("[INFO] No full trace matrix will be loaded into RAM")

with h5py.File(TRACESET_FILE, "r") as f_read:
    traces_ds = f_read["traces"]
    nonces_ds = f_read["nonces"]

    for start in tqdm(
        range(0, n_trc, chunk_size),
        desc="Streaming SNR accumulation",
        disable=TQDM_DISABLE,
    ):
        end = min(start + chunk_size, n_trc)

        # Read only one chunk from disk.
        traces_chunk = traces_ds[start:end]
        nonces_chunk = nonces_ds[start:end]

        # Convert only this chunk for computation.
        x = traces_chunk.astype(chunk_work_dtype, copy=False)

        # Total sums over all traces.
        total_sum += np.sum(x, axis=0, dtype=np.float64)

        # x2 is a temporary per-chunk array only.
        x2 = x * x
        total_sumsq += np.sum(x2, axis=0, dtype=np.float64)

        # Compute ASCON states and labels for this chunk only.
        states_chunk = compute_state_chunk(nonces_chunk)
        labels = build_labels_flat(states_chunk, dtype=chunk_work_dtype)

        # Count class-1 occurrences for each target bit.
        count1 += np.sum(labels, axis=0, dtype=np.float64)

        # Accumulate class-1 sums.
        #
        # labels.T shape : (320, chunk_len)
        # x shape        : (chunk_len, n_samples)
        # result         : (320, n_samples)
        sum1 += labels.T @ x
        sumsq1 += labels.T @ x2

        # Drop references to large per-chunk arrays.
        del traces_chunk, nonces_chunk, x, x2, states_chunk, labels

print("[INFO] Finished streaming accumulation")

# ---------------------------------------------------------------------------
# Finalize SNR traces
# ---------------------------------------------------------------------------
print("[INFO] Computing final SNR traces from accumulated statistics")

n_total = float(n_trc)
count0 = n_total - count1

snr_flat = np.zeros((n_targets, n_samples), dtype=np.float32)

for target in tqdm(range(n_targets), desc="Finalizing SNR", disable=TQDM_DISABLE):
    n1 = count1[target]
    n0 = count0[target]

    if n0 == 0 or n1 == 0:
        continue

    s1 = sum1[target]
    ss1 = sumsq1[target]

    s0 = total_sum - s1
    ss0 = total_sumsq - ss1

    m0 = s0 / n0
    m1 = s1 / n1

    v0 = (ss0 / n0) - (m0 * m0)
    v1 = (ss1 / n1) - (m1 * m1)

    # Numerical safety against tiny negative values from floating-point error.
    v0 = np.maximum(v0, 0.0)
    v1 = np.maximum(v1, 0.0)

    w0 = n0 / n_total
    w1 = n1 / n_total

    mean_of_means = w0 * m0 + w1 * m1

    var_of_means = (
        w0 * (m0 - mean_of_means) ** 2
        + w1 * (m1 - mean_of_means) ** 2
    )

    mean_of_vars = w0 * v0 + w1 * v1

    snr = var_of_means / (mean_of_vars + 1e-12)

    snr_flat[target, :] = snr.astype(np.float32)

snr_all = snr_flat.reshape(n_regs, n_bits, n_samples)

# ---------------------------------------------------------------------------
# Build ranked results from full SNR traces
# ---------------------------------------------------------------------------
rank_regs = []
rank_bits = []
rank_snr = []

for reg_i, reg_name in enumerate(reg_names):
    for bit_i in range(n_bits):
        max_snr = float(np.max(snr_all[reg_i, bit_i, :]))

        rank_regs.append(reg_name)
        rank_bits.append(bit_i)
        rank_snr.append(max_snr)

rank_regs = np.array(rank_regs, dtype=h5py.string_dtype(encoding="utf-8"))
rank_bits = np.array(rank_bits, dtype=np.uint16)
rank_snr = np.array(rank_snr, dtype=np.float32)

order = np.argsort(rank_snr)[::-1]
rank_regs = rank_regs[order]
rank_bits = rank_bits[order]
rank_snr = rank_snr[order]

if debug:
    print("\n[DBG] Top 10 ranked (reg, bit, peakSNR):")
    for k in range(min(10, len(rank_snr))):
        print(f"  [{rank_regs[k]}, {int(rank_bits[k])}, {rank_snr[k]:.6g}]")

# ---------------------------------------------------------------------------
# Save ranked results to cache file
# ---------------------------------------------------------------------------
if save_snr_ranked_all_bits:
    with h5py.File(SNR_OUT_FILE, "w") as f:
        f.attrs["sbox_type"] = sbox_type
        f.attrs["n_traces"] = n_trc
        f.attrs["n_samples"] = n_samples
        f.attrs["snr_model"] = "binary bit-level SNR"
        f.attrs["snr_formula"] = "Var(E[T|bit]) / E[Var(T|bit)]"
        f.attrs["chunk_size"] = chunk_size
        f.attrs["nonce_layout"] = "nonces[:,0]=S4/nonce_lsb, nonces[:,1]=S3/nonce_msb"

        if sampling_interval is not None:
            f.attrs["sampling_interval"] = sampling_interval
        if key_hex is not None:
            f.attrs["key_hex"] = key_hex
        if iv_hex is not None:
            f.attrs["iv_hex"] = iv_hex

        g = f.create_group("ranked")
        g.create_dataset("register", data=rank_regs)
        g.create_dataset("bit", data=rank_bits)
        g.create_dataset("snr", data=rank_snr)

    print(f"\n[INFO] Saved ranked SNR results to: {SNR_OUT_FILE}")
else:
    print("\n[INFO] save_snr_ranked_all_bits=False, not writing ranked output")

# ---------------------------------------------------------------------------
# Save full SNR traces to cache file
# ---------------------------------------------------------------------------
if save_snr_traces_all_bits:
    with h5py.File(SNR_TRACE_OUT_FILE, "w") as f:
        f.attrs["sbox_type"] = sbox_type
        f.attrs["n_traces"] = n_trc
        f.attrs["n_samples"] = n_samples
        f.attrs["snr_model"] = "binary bit-level SNR"
        f.attrs["snr_formula"] = "Var(E[T|bit]) / E[Var(T|bit)]"
        f.attrs["chunk_size"] = chunk_size
        f.attrs["nonce_layout"] = "nonces[:,0]=S4/nonce_lsb, nonces[:,1]=S3/nonce_msb"

        if sampling_interval is not None:
            f.attrs["sampling_interval"] = sampling_interval
        if key_hex is not None:
            f.attrs["key_hex"] = key_hex
        if iv_hex is not None:
            f.attrs["iv_hex"] = iv_hex

        g = f.create_group("snr_traces")

        g.create_dataset(
            "value",
            data=snr_all,
            compression="gzip",
            compression_opts=4,
            chunks=(1, 1, n_samples),
        )

        g.create_dataset(
            "register_names",
            data=np.array(reg_names, dtype=h5py.string_dtype(encoding="utf-8")),
        )

        g.create_dataset(
            "bits",
            data=np.arange(n_bits, dtype=np.uint16),
        )

        g.create_dataset(
            "sample_index",
            data=np.arange(n_samples, dtype=np.uint32),
        )

    print(f"[INFO] Saved full SNR traces to: {SNR_TRACE_OUT_FILE}")
else:
    print("\n[INFO] save_snr_traces_all_bits=False, not writing SNR traces output")
