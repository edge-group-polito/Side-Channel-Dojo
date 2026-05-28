#!/usr/bin/env python3
"""
ASCON key-recovery progression for all generic S-boxes.

The trace files are streamed from row 0 to N. This keeps memory bounded for the
large HDF5 trace sets and matches the assumption that trace capture order was
already randomized.

Environment controls:
  ASCON_PROGRESS_SBOXES       comma list, or "all"
  ASCON_PROGRESS_N            max prefix traces to use, default 1000000
  ASCON_TRACESET_SIZE_K       traceset filename tag, defaults to N//1000
  ASCON_SNR_N                 SNR cache trace count, defaults to PROGRESS_N
  ASCON_PROGRESS_RESOLUTION   trace-count step, default 50000
  ASCON_PROGRESS_COUNTS       comma list of explicit trace counts
  ASCON_PROGRESS_APPEND_MAX   append max trace count to explicit counts, default 1
  ASCON_MAX_TARGETS           optional cap on SNR-ranked targets
  ASCON_CHUNK_SIZE            streaming chunk size, default 20000
  ASCON_CPA_SAMPLE_WINDOW     0 for full trace, otherwise SNR-peak window width
  ASCON_LEAKAGE_POLARITY      negative | positive | both, default negative
  ASCON_CPA_DEVICE            auto | cpu | gpu
  ASCON_PROGRESS_OUTPUT_DIR   output directory for JSON/CSV/NPZ files
  ASCON_PROGRESS_PLOT_DIR     output directory for plots
  ASCON_SAVE_PLOTS            1/0, default 1
  ASCON_PROGRESS_SAVE_TARGET_LOG 1/0, default 0
"""

import os

# ---------------------------------------------------------------------------
# CPU configuration: set before importing NumPy.
# ---------------------------------------------------------------------------
_max_cpu_workers_env = os.environ.get("ASCON_MAX_CPU_WORKERS")
max_cpu_workers = (
    os.cpu_count() or 1
    if _max_cpu_workers_env in (None, "")
    else int(_max_cpu_workers_env)
)

os.environ["OMP_NUM_THREADS"] = str(max_cpu_workers)
os.environ["OPENBLAS_NUM_THREADS"] = str(max_cpu_workers)
os.environ["MKL_NUM_THREADS"] = str(max_cpu_workers)
os.environ["VECLIB_MAXIMUM_THREADS"] = str(max_cpu_workers)
os.environ["NUMEXPR_NUM_THREADS"] = str(max_cpu_workers)

import csv
import json
import sys
import time
from pathlib import Path

import h5py
import numpy as np
from tqdm import tqdm


# ---------------------------------------------------------------------------
# Project root and imports
# ---------------------------------------------------------------------------
def find_project_root(start: Path, markers=("fusesoc.conf", ".dojo_root")) -> Path:
    current = start
    while current != current.parent:
        if any((current / marker).exists() for marker in markers):
            return current
        current = current.parent
    raise RuntimeError(
        f"Could not find project root. Looked for markers: {markers}. "
        "Please run from inside the Side-Channel-Dojo repository."
    )


try:
    SCRIPT_DIR = Path(__file__).resolve().parent
except NameError:
    SCRIPT_DIR = Path.cwd()

DOJO_ROOT = find_project_root(SCRIPT_DIR)
SCA_DIR = DOJO_ROOT / "sw" / "sca_scripts"
TRACESET_DIR = DOJO_ROOT / "sw" / "traceset" / "ASCON" / "sw"
BASE_CACHE_DIR = SCA_DIR / "ASCON" / "sw" / "cache"
DEFAULT_OUTPUT_DIR = BASE_CACHE_DIR / "key_recovery_progression_all_sboxes"
DEFAULT_PLOT_DIR = SCA_DIR / "ASCON" / "sw" / "plot" / "key_recovery_progression_all_sboxes"

sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCA_DIR))

from analyzer.attack.ascon.xheep_ascon_cpa.ascon_cpa import (  # noqa: E402
    ascon_cpa_finalize_corrmax_accumulators,
    ascon_cpa_init_accumulators,
    ascon_cpa_update_accumulators,
    get_cpa_backend_name,
)

from xheep_ASCON_cpa import (  # noqa: E402
    bits_to_u64,
    compute_H64_chunk,
    find_snr_file,
    find_snr_trace_file,
    load_snr_peak_samples,
    load_snr_ranked_targets,
    propagate_group_constraints,
    signed_corr_at_samples_from_accumulators,
    target_sample_window,
    target_to_k_idx,
)


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------
ALL_SBOXES = [
    "lut_ascon",
    "lut_bilgin",
    "lut_allouzi",
    "lut_lu_4",
    "lut_lu_5",
    "lut_lu_6",
    "lut_lu_7",
]


def _parse_sboxes(value: str):
    value = str(value).strip()
    if not value or value.lower() == "all":
        return list(ALL_SBOXES)

    sboxes = [x.strip() for x in value.split(",") if x.strip()]
    unknown = sorted(set(sboxes) - set(ALL_SBOXES))
    if unknown:
        raise ValueError(f"Unknown S-box names: {unknown}")
    return sboxes


def _env_flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value in (None, ""):
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _format_trace_count_tag(trace_count: int) -> str:
    trace_count = int(trace_count)
    if trace_count % 1000 == 0:
        return f"{trace_count // 1000}k"
    return str(trace_count)


def _build_trace_counts(max_traces: int, resolution: int):
    explicit = os.environ.get("ASCON_PROGRESS_COUNTS")
    if explicit not in (None, ""):
        append_max = _env_flag("ASCON_PROGRESS_APPEND_MAX", True)
        counts = sorted({int(x.strip()) for x in explicit.split(",") if x.strip()})
        counts = [count for count in counts if 1 < count <= int(max_traces)]
        if not counts:
            raise ValueError("ASCON_PROGRESS_COUNTS did not contain any usable counts > 1")
        if append_max and counts[-1] != int(max_traces):
            counts.append(int(max_traces))
        return counts

    if int(resolution) <= 1:
        raise ValueError("ASCON_PROGRESS_RESOLUTION must be greater than 1")

    counts = list(range(int(resolution), int(max_traces) + 1, int(resolution)))
    if not counts or counts[-1] != int(max_traces):
        counts.append(int(max_traces))
    return counts


def _attr_to_str(value):
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


def _find_trace_file(sbox_type: str, traceset_size_k: int, max_traces_requested: int) -> Path:
    preferred = TRACESET_DIR / f"ascon_opt32_{sbox_type}_{traceset_size_k}k.h5"
    if preferred.exists():
        return preferred

    if os.environ.get("ASCON_TRACESET_SIZE_K") not in (None, ""):
        return preferred

    candidates = sorted(TRACESET_DIR.glob(f"ascon_opt32_{sbox_type}_*.h5"))
    if not candidates:
        return preferred

    inspected = []
    for candidate in candidates:
        try:
            with h5py.File(candidate, "r") as f:
                n_traces = int(f["traces"].shape[0])
        except Exception:
            n_traces = -1
        inspected.append((n_traces, candidate))

    sufficient = [
        item
        for item in inspected
        if item[0] >= int(max_traces_requested)
    ]
    if sufficient:
        selected = sorted(sufficient, key=lambda item: item[0])[0][1]
    else:
        selected = sorted(inspected, key=lambda item: item[0], reverse=True)[0][1]

    print(
        f"[INFO] Requested trace file was not found: {preferred}. "
        f"Using available trace file instead: {selected}"
    )
    return selected


def _hamming64(x: int) -> int:
    return bin(int(x) & 0xFFFFFFFFFFFFFFFF).count("1")


# ---------------------------------------------------------------------------
# Recovery state and summaries
# ---------------------------------------------------------------------------
def _state_template():
    return {
        "k0_rec_bits": np.zeros(64, dtype=np.uint8),
        "k0_rec": np.zeros(64, dtype=bool),
        "k1_rec_bits": np.zeros(64, dtype=np.uint8),
        "k1_rec": np.zeros(64, dtype=bool),
        "kx_rec_bits": np.zeros(64, dtype=np.uint8),
        "kx_rec": np.zeros(64, dtype=bool),
        "targets_used": 0,
        "targets_skipped": 0,
        "full_key_recovered": False,
    }


def _idx_done(idx: int, state) -> bool:
    idx = int(idx)
    return bool(
        (state["k0_rec"][idx] and state["k1_rec"][idx])
        or (
            state["kx_rec"][idx]
            and (state["k0_rec"][idx] or state["k1_rec"][idx])
        )
    )


def _target_is_useful_for_state(k_idx, state) -> bool:
    return any(not _idx_done(int(idx), state) for idx in k_idx)


def _summarize_state(
    state,
    trace_count: int,
    k0_bits_expected,
    k1_bits_expected,
    k0_int_expected: int,
    k1_int_expected: int,
):
    k0_rec_count = int(np.sum(state["k0_rec"]))
    k1_rec_count = int(np.sum(state["k1_rec"]))
    kx_rec_count = int(np.sum(state["kx_rec"]))

    k0_correct = int(np.sum((state["k0_rec_bits"] == k0_bits_expected) & state["k0_rec"]))
    k1_correct = int(np.sum((state["k1_rec_bits"] == k1_bits_expected) & state["k1_rec"]))
    k0_wrong = k0_rec_count - k0_correct
    k1_wrong = k1_rec_count - k1_correct

    known_key_bits = k0_rec_count + k1_rec_count
    correct_key_bits = k0_correct + k1_correct
    wrong_recovered_bits = k0_wrong + k1_wrong

    k0_int = bits_to_u64(state["k0_rec_bits"])
    k1_int = bits_to_u64(state["k1_rec_bits"])
    all_bits_recovered = bool(k0_rec_count == 64 and k1_rec_count == 64)
    full_key_match = bool(
        all_bits_recovered
        and k0_int == int(k0_int_expected)
        and k1_int == int(k1_int_expected)
    )

    return {
        "trace_count": int(trace_count),
        "k0_recovered_count": k0_rec_count,
        "k1_recovered_count": k1_rec_count,
        "kx_recovered_count": kx_rec_count,
        "known_key_bits_count": known_key_bits,
        "k0_correct_recovered_count": k0_correct,
        "k1_correct_recovered_count": k1_correct,
        "correct_key_bits_count": correct_key_bits,
        "k0_wrong_recovered_count": k0_wrong,
        "k1_wrong_recovered_count": k1_wrong,
        "wrong_recovered_key_bits_count": wrong_recovered_bits,
        "recovered_key_bits_percent": float(100.0 * known_key_bits / 128.0),
        "correct_key_bits_percent": float(100.0 * correct_key_bits / 128.0),
        "known_bit_accuracy_percent": float(
            100.0 * correct_key_bits / max(1, known_key_bits)
        ),
        "all_bits_recovered": all_bits_recovered,
        "full_key_match": full_key_match,
        "recovered_k0_hex": f"{k0_int:016X}",
        "recovered_k1_hex": f"{k1_int:016X}",
        "full_key_hamming_distance_if_filled": int(
            _hamming64(k0_int ^ int(k0_int_expected))
            + _hamming64(k1_int ^ int(k1_int_expected))
        ),
        "targets_used": int(state["targets_used"]),
        "targets_skipped": int(state["targets_skipped"]),
    }


# ---------------------------------------------------------------------------
# CPA grouping for exact trace prefixes
# ---------------------------------------------------------------------------
def _select_key_group(best_group, signed_corr: float, polarity: str):
    if polarity == "both":
        members = best_group["all"]
    elif polarity == "positive":
        members = best_group["same"] if signed_corr > 0.0 else best_group["complement"]
    elif polarity == "negative":
        members = best_group["same"] if signed_corr < 0.0 else best_group["complement"]
    else:
        raise ValueError("polarity must be one of: both, positive, negative")

    return members if members else best_group["all"]


def _build_oriented_groups_from_signatures(signatures):
    """
    Build identical/complement hypothesis groups for the current trace prefix.

    The CPA accumulates all 64 raw hypotheses. At each trace-count checkpoint,
    this function groups only over the prefix used at that checkpoint, avoiding
    over-committing bits that are distinguishable only by later traces.
    """
    canonical_to_group = {}
    key_hyp_groups = []
    rep_indices = []

    for hyp in range(64):
        col_b = bytes(signatures[hyp])
        col_arr = np.frombuffer(col_b, dtype=np.uint8)
        compl_b = (1 - col_arr).astype(np.uint8, copy=False).tobytes()
        canon_b = col_b if col_b <= compl_b else compl_b

        if canon_b in canonical_to_group:
            group_idx = canonical_to_group[canon_b]
            key_hyp_groups[group_idx].append(hyp)
        else:
            group_idx = len(key_hyp_groups)
            canonical_to_group[canon_b] = group_idx
            key_hyp_groups.append([hyp])
            rep_indices.append(hyp)

    oriented_groups = []
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

        oriented_groups.append(
            {
                "same": same_members,
                "complement": complement_members,
                "all": members,
            }
        )

    return np.asarray(rep_indices, dtype=np.int64), oriented_groups


def _progressive_attack_one_target_prefix(
    trace_file: Path,
    nonces: np.ndarray,
    trace_counts,
    n_samples: int,
    iv_int: int,
    target: dict,
    sbox_type: str,
    chunk_size: int,
    cpa_backend: str,
    sample_window: int,
    polarity: str,
):
    attacked_state_reg = target["reg"]
    attacked_bit = int(target["bit"])
    trace_counts = [int(count) for count in trace_counts]
    max_count = int(max(trace_counts))

    sample_start, sample_stop = target_sample_window(target, n_samples, sample_window)
    n_cpa_samples = int(sample_stop - sample_start)
    if n_cpa_samples <= 0:
        raise ValueError(
            f"Invalid sample window [{sample_start}, {sample_stop}) for {target}"
        )

    k_idx = target_to_k_idx(attacked_state_reg, attacked_bit)
    acc = ascon_cpa_init_accumulators(
        n_samples=n_cpa_samples,
        n_hypotheses=64,
        backend=cpa_backend,
    )
    signatures = [bytearray() for _ in range(64)]

    results = []
    accumulated = 0
    checkpoint_idx = 0

    with h5py.File(trace_file, "r") as f:
        traces_ds = f["traces"]

        while accumulated < max_count:
            next_checkpoint = int(trace_counts[checkpoint_idx])
            end = min(accumulated + int(chunk_size), max_count, next_checkpoint)

            traces_chunk = traces_ds[accumulated:end, sample_start:sample_stop].astype(
                np.float32,
                copy=False,
            )
            nonces_chunk = nonces[accumulated:end]

            h64 = compute_H64_chunk(
                nonces_chunk,
                iv_int,
                attacked_state_reg,
                attacked_bit,
                sbox_type,
                backend="cpu",
            )

            ascon_cpa_update_accumulators(
                acc,
                traces_chunk,
                h64.astype(np.float32, copy=False),
            )

            for hyp in range(64):
                signatures[hyp].extend(h64[:, hyp].tobytes())

            accumulated = end
            del traces_chunk, nonces_chunk, h64

            if accumulated != next_checkpoint:
                continue

            corr_raw, argmax_samples = ascon_cpa_finalize_corrmax_accumulators(
                acc,
                return_argmax_samples=True,
            )
            corr_raw = np.nan_to_num(np.asarray(corr_raw), nan=0.0)
            argmax_samples = np.asarray(argmax_samples, dtype=np.int64)
            signed_corr = signed_corr_at_samples_from_accumulators(acc, argmax_samples)
            signed_corr = np.nan_to_num(np.asarray(signed_corr), nan=0.0)

            rep_indices, oriented_groups = _build_oriented_groups_from_signatures(signatures)
            corr_group = corr_raw[rep_indices]
            best_group_idx = int(np.argmax(corr_group))
            rep_hyp = int(rep_indices[best_group_idx])
            best_group = oriented_groups[best_group_idx]
            best_key_group = _select_key_group(
                best_group,
                float(signed_corr[rep_hyp]),
                polarity,
            )

            results.append(
                {
                    "trace_count": int(next_checkpoint),
                    "attacked_state_reg": attacked_state_reg,
                    "attacked_bit": attacked_bit,
                    "k_idx": k_idx,
                    "best_key_group": best_key_group,
                    "num_groups": int(len(rep_indices)),
                    "best_group_idx": best_group_idx,
                    "best_rep_hypothesis": rep_hyp,
                    "best_corr": float(corr_group[best_group_idx]),
                    "best_signed_corr": float(signed_corr[rep_hyp]),
                    "best_sample": int(argmax_samples[rep_hyp] + sample_start),
                    "sample_start": int(sample_start),
                    "sample_stop": int(sample_stop),
                    "n_cpa_samples": n_cpa_samples,
                }
            )

            checkpoint_idx += 1
            if checkpoint_idx >= len(trace_counts):
                break

    return results


def _run_target_loop_prefix(
    sbox_type: str,
    trace_file: Path,
    nonces: np.ndarray,
    trace_counts,
    n_samples: int,
    iv_int: int,
    targets,
    k0_bits_expected,
    k1_bits_expected,
    k0_int_expected: int,
    k1_int_expected: int,
    chunk_size: int,
    cpa_backend: str,
    sample_window: int,
    polarity: str,
    save_target_log: bool,
):
    states = [_state_template() for _ in trace_counts]
    target_log = []
    targets_processed = 0
    tic = time.perf_counter()

    for target in tqdm(targets, desc=f"{sbox_type}: prefix CPA targets"):
        k_idx = target_to_k_idx(target["reg"], int(target["bit"]))
        active_state_indices = []
        active_counts = []

        for state_idx, state in enumerate(states):
            if state["full_key_recovered"]:
                continue

            if _target_is_useful_for_state(k_idx, state):
                active_state_indices.append(state_idx)
                active_counts.append(int(trace_counts[state_idx]))
            else:
                state["targets_skipped"] += 1

        if not active_state_indices:
            if all(state["full_key_recovered"] for state in states):
                print(f"[INFO] {sbox_type}: all trace-count states recovered full key; stopping.")
                break
            continue

        target_results = _progressive_attack_one_target_prefix(
            trace_file=trace_file,
            nonces=nonces,
            trace_counts=active_counts,
            n_samples=n_samples,
            iv_int=iv_int,
            target=target,
            sbox_type=sbox_type,
            chunk_size=chunk_size,
            cpa_backend=cpa_backend,
            sample_window=sample_window,
            polarity=polarity,
        )
        targets_processed += 1

        for state_idx, result in zip(active_state_indices, target_results):
            state = states[state_idx]
            if state["full_key_recovered"]:
                continue

            propagate_group_constraints(
                result["best_key_group"],
                result["k_idx"],
                k0_bits_expected,
                k1_bits_expected,
                state["k0_rec_bits"],
                state["k0_rec"],
                state["k1_rec_bits"],
                state["k1_rec"],
                state["kx_rec_bits"],
                state["kx_rec"],
                verbose=False,
            )

            state["targets_used"] += 1
            state["full_key_recovered"] = bool(
                np.all(state["k0_rec"]) and np.all(state["k1_rec"])
            )

            if save_target_log:
                target_log.append(
                    {
                        "trace_count": int(trace_counts[state_idx]),
                        "target": f"{result['attacked_state_reg']}[{result['attacked_bit']}]",
                        "snr": float(target.get("snr", np.nan)),
                        "k_idx": [int(x) for x in result["k_idx"]],
                        "best_group_idx": int(result["best_group_idx"]),
                        "best_rep_hypothesis": int(result["best_rep_hypothesis"]),
                        "best_corr": float(result["best_corr"]),
                        "best_signed_corr": float(result["best_signed_corr"]),
                        "best_sample": int(result["best_sample"]),
                        "num_groups": int(result["num_groups"]),
                        "k0_recovered": int(np.sum(state["k0_rec"])),
                        "k1_recovered": int(np.sum(state["k1_rec"])),
                        "kx_recovered": int(np.sum(state["kx_rec"])),
                    }
                )

        if targets_processed % 10 == 0 or all(state["full_key_recovered"] for state in states):
            final_state = states[-1]
            print(
                f"[INFO] {sbox_type}: processed {targets_processed} targets; "
                f"max-count k0={np.sum(final_state['k0_rec'])}/64, "
                f"k1={np.sum(final_state['k1_rec'])}/64, "
                f"kx={np.sum(final_state['kx_rec'])}/64"
            )

        if all(state["full_key_recovered"] for state in states):
            print(f"[INFO] {sbox_type}: all trace-count states recovered full key; stopping.")
            break

    toc = time.perf_counter()
    summaries = [
        _summarize_state(
            state,
            trace_count,
            k0_bits_expected,
            k1_bits_expected,
            k0_int_expected,
            k1_int_expected,
        )
        for state, trace_count in zip(states, trace_counts)
    ]

    return summaries, target_log, int(targets_processed), float((toc - tic) / 60.0)


# ---------------------------------------------------------------------------
# Exports and plotting
# ---------------------------------------------------------------------------
def _import_matplotlib():
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.ticker as mticker

        return plt, mticker
    except Exception as exc:
        print(f"[WARN] Plotting disabled: could not import matplotlib ({exc})")
        return None, None


def _format_axes_for_traces(ax, mticker):
    formatter = mticker.ScalarFormatter(useMathText=True)
    formatter.set_powerlimits((0, 0))
    ax.xaxis.set_major_formatter(formatter)
    ax.ticklabel_format(axis="x", style="sci", scilimits=(0, 0))
    ax.xaxis.get_offset_text().set_fontsize(11)
    ax.grid(True, alpha=0.30)


def _save_figure(fig, stem: Path):
    stem.parent.mkdir(parents=True, exist_ok=True)
    png_file = stem.with_suffix(".png")
    pdf_file = stem.with_suffix(".pdf")
    fig.tight_layout()
    fig.savefig(png_file, dpi=180)
    fig.savefig(pdf_file)
    return [str(png_file), str(pdf_file)]


def _write_per_sbox_exports(result, cache_dir: Path):
    sbox_type = result["sbox_type"]
    tag = _format_trace_count_tag(result["n_traces_max"])
    csv_file = cache_dir / f"ASCON_generic_key_recovery_progression_{sbox_type}_{tag}.csv"
    npz_file = cache_dir / f"ASCON_generic_key_recovery_progression_{sbox_type}_{tag}.npz"

    fields = [
        "sbox_type",
        "trace_count",
        "k0_recovered_count",
        "k1_recovered_count",
        "kx_recovered_count",
        "known_key_bits_count",
        "k0_correct_recovered_count",
        "k1_correct_recovered_count",
        "correct_key_bits_count",
        "k0_wrong_recovered_count",
        "k1_wrong_recovered_count",
        "wrong_recovered_key_bits_count",
        "recovered_key_bits_percent",
        "correct_key_bits_percent",
        "known_bit_accuracy_percent",
        "all_bits_recovered",
        "full_key_match",
        "targets_used",
        "targets_skipped",
        "recovered_k0_hex",
        "recovered_k1_hex",
    ]

    with open(csv_file, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for summary in result["summaries"]:
            row = dict(summary)
            row["sbox_type"] = sbox_type
            row["all_bits_recovered"] = int(bool(row["all_bits_recovered"]))
            row["full_key_match"] = int(bool(row["full_key_match"]))
            writer.writerow({field: row.get(field, "") for field in fields})

    np.savez_compressed(
        npz_file,
        trace_counts=np.asarray(result["trace_counts"], dtype=np.int64),
        k0_recovered_count=np.asarray(result["k0_recovered_count"], dtype=np.float64),
        k1_recovered_count=np.asarray(result["k1_recovered_count"], dtype=np.float64),
        kx_recovered_count=np.asarray(result["kx_recovered_count"], dtype=np.float64),
        known_key_bits_count=np.asarray(result["known_key_bits_count"], dtype=np.float64),
        correct_key_bits_count=np.asarray(result["correct_key_bits_count"], dtype=np.float64),
        wrong_recovered_key_bits_count=np.asarray(
            result["wrong_recovered_key_bits_count"],
            dtype=np.float64,
        ),
    )

    return {"csv": str(csv_file), "npz": str(npz_file)}


def _write_combined_exports(combined, output_dir: Path):
    tag = _format_trace_count_tag(combined["n_traces_max"])
    csv_file = output_dir / f"ASCON_generic_key_recovery_progression_all_sboxes_{tag}.csv"
    json_file = output_dir / f"ASCON_generic_key_recovery_progression_all_sboxes_{tag}.json"

    fields = [
        "sbox_type",
        "trace_count",
        "k0_recovered_count",
        "k1_recovered_count",
        "kx_recovered_count",
        "known_key_bits_count",
        "k0_correct_recovered_count",
        "k1_correct_recovered_count",
        "correct_key_bits_count",
        "wrong_recovered_key_bits_count",
        "recovered_key_bits_percent",
        "correct_key_bits_percent",
        "known_bit_accuracy_percent",
        "all_bits_recovered",
        "full_key_match",
        "targets_used",
        "targets_skipped",
    ]

    with open(csv_file, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for sbox_type, result in combined["results"].items():
            for summary in result["summaries"]:
                row = dict(summary)
                row["sbox_type"] = sbox_type
                row["all_bits_recovered"] = int(bool(row["all_bits_recovered"]))
                row["full_key_match"] = int(bool(row["full_key_match"]))
                writer.writerow({field: row.get(field, "") for field in fields})

    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(combined, f, indent=2)

    return {"csv": str(csv_file), "json": str(json_file)}


def _plot_per_sbox_result(result, plot_dir: Path, save_plots: bool):
    if not save_plots:
        return {}

    plt, mticker = _import_matplotlib()
    if plt is None:
        return {}

    sbox_type = result["sbox_type"]
    tag = _format_trace_count_tag(result["n_traces_max"])
    x_vals = np.asarray(result["trace_counts"], dtype=np.int64)
    plot_dir = plot_dir / sbox_type
    plot_paths = {}

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(x_vals, result["k0_correct_recovered_count"], marker="o", markersize=3, linewidth=1.8, label="k0 correct")
    ax.plot(x_vals, result["k1_correct_recovered_count"], marker="s", markersize=3, linewidth=1.8, label="k1 correct")
    ax.plot(x_vals, result["correct_key_bits_count"], marker="^", markersize=3, linewidth=2.2, label="k0+k1 correct")
    ax.set_xlabel("Number of prefix traces", fontsize=13)
    ax.set_ylabel("Correct recovered key bits", fontsize=13)
    ax.set_title(f"ASCON generic CPA key-recovery progression - {sbox_type}", fontsize=14)
    ax.set_ylim(0, 132)
    ax.set_yticks(range(0, 129, 16))
    _format_axes_for_traces(ax, mticker)
    ax.legend(loc="best")
    plot_paths["correct_recovered_key_bits"] = _save_figure(
        fig,
        plot_dir / f"ASCON_generic_correct_recovered_key_bits_{sbox_type}_{tag}",
    )
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(x_vals, result["known_key_bits_count"], marker="o", markersize=3, linewidth=1.8, label="recovered k0+k1")
    ax.plot(x_vals, result["wrong_recovered_key_bits_count"], marker="s", markersize=3, linewidth=1.8, label="wrong recovered")
    ax.set_xlabel("Number of prefix traces", fontsize=13)
    ax.set_ylabel("Recovered key bits", fontsize=13)
    ax.set_title(f"ASCON generic CPA recovered/wrong bits - {sbox_type}", fontsize=14)
    ax.set_ylim(bottom=0)
    _format_axes_for_traces(ax, mticker)
    ax.legend(loc="best")
    plot_paths["recovered_and_wrong_key_bits"] = _save_figure(
        fig,
        plot_dir / f"ASCON_generic_recovered_and_wrong_key_bits_{sbox_type}_{tag}",
    )
    plt.close(fig)

    return plot_paths


def _plot_combined_results(combined, plot_dir: Path, save_plots: bool):
    if not save_plots:
        return {}

    plt, mticker = _import_matplotlib()
    if plt is None:
        return {}

    tag = _format_trace_count_tag(combined["n_traces_max"])
    plot_dir.mkdir(parents=True, exist_ok=True)
    plot_paths = {}

    fig, ax = plt.subplots(figsize=(11, 6.5))
    for sbox_type, result in combined["results"].items():
        ax.plot(
            result["trace_counts"],
            result["correct_key_bits_count"],
            marker="o",
            markersize=3,
            linewidth=1.8,
            label=sbox_type,
        )
    ax.set_xlabel("Number of prefix traces", fontsize=13)
    ax.set_ylabel("Correct recovered key bits", fontsize=13)
    ax.set_title("ASCON generic CPA key-recovery progression - all S-boxes", fontsize=14)
    ax.set_ylim(0, 132)
    ax.set_yticks(range(0, 129, 16))
    _format_axes_for_traces(ax, mticker)
    ax.legend(loc="best")
    plot_paths["correct_recovered_key_bits"] = _save_figure(
        fig,
        plot_dir / f"ASCON_generic_correct_recovered_key_bits_all_sboxes_{tag}",
    )
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(11, 6.5))
    for sbox_type, result in combined["results"].items():
        ax.plot(
            result["trace_counts"],
            result["known_key_bits_count"],
            marker="o",
            markersize=3,
            linewidth=1.8,
            label=sbox_type,
        )
    ax.set_xlabel("Number of prefix traces", fontsize=13)
    ax.set_ylabel("Recovered k0+k1 bits", fontsize=13)
    ax.set_title("ASCON generic CPA recovered key-bit coverage - all S-boxes", fontsize=14)
    ax.set_ylim(0, 132)
    ax.set_yticks(range(0, 129, 16))
    _format_axes_for_traces(ax, mticker)
    ax.legend(loc="best")
    plot_paths["recovered_key_bits"] = _save_figure(
        fig,
        plot_dir / f"ASCON_generic_recovered_key_bits_all_sboxes_{tag}",
    )
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(11, 6.5))
    for sbox_type, result in combined["results"].items():
        ax.plot(
            result["trace_counts"],
            result["wrong_recovered_key_bits_count"],
            marker="o",
            markersize=3,
            linewidth=1.8,
            label=sbox_type,
        )
    ax.set_xlabel("Number of prefix traces", fontsize=13)
    ax.set_ylabel("Wrong recovered key bits", fontsize=13)
    ax.set_title("ASCON generic CPA wrong recovered bits - all S-boxes", fontsize=14)
    ax.set_ylim(bottom=0)
    _format_axes_for_traces(ax, mticker)
    ax.legend(loc="best")
    plot_paths["wrong_recovered_key_bits"] = _save_figure(
        fig,
        plot_dir / f"ASCON_generic_wrong_recovered_key_bits_all_sboxes_{tag}",
    )
    plt.close(fig)

    fig, axes = plt.subplots(2, 1, figsize=(11, 8), sharex=True)
    for sbox_type, result in combined["results"].items():
        axes[0].plot(
            result["trace_counts"],
            result["k0_correct_recovered_count"],
            marker="o",
            markersize=3,
            linewidth=1.6,
            label=sbox_type,
        )
        axes[1].plot(
            result["trace_counts"],
            result["k1_correct_recovered_count"],
            marker="o",
            markersize=3,
            linewidth=1.6,
            label=sbox_type,
        )

    axes[0].set_ylabel("Correct k0 bits", fontsize=12)
    axes[1].set_ylabel("Correct k1 bits", fontsize=12)
    axes[1].set_xlabel("Number of prefix traces", fontsize=13)
    for ax in axes:
        ax.set_ylim(0, 67)
        ax.set_yticks(range(0, 65, 8))
        _format_axes_for_traces(ax, mticker)
    axes[0].set_title("ASCON generic CPA k0/k1 recovery - all S-boxes", fontsize=14)
    axes[0].legend(loc="best", ncol=2)
    plot_paths["k0_k1_correct_recovered_bits"] = _save_figure(
        fig,
        plot_dir / f"ASCON_generic_k0_k1_correct_recovered_bits_all_sboxes_{tag}",
    )
    plt.close(fig)

    print(f"[INFO] Wrote combined plots to {plot_dir}")
    return plot_paths


# ---------------------------------------------------------------------------
# Per-S-box runner
# ---------------------------------------------------------------------------
def _run_one_sbox(
    sbox_type: str,
    max_traces_requested: int,
    traceset_size_k: int,
    snr_trace_count: int,
    trace_counts_requested,
    chunk_size: int,
    sample_window: int,
    polarity: str,
    cpa_backend: str,
    max_targets,
    output_dir: Path,
    plot_dir: Path,
    save_plots: bool,
    save_target_log: bool,
):
    trace_file = _find_trace_file(sbox_type, traceset_size_k, max_traces_requested)
    cache_dir = BASE_CACHE_DIR / sbox_type
    snr_file = find_snr_file(cache_dir, sbox_type, snr_trace_count)
    snr_trace_file = find_snr_trace_file(cache_dir, sbox_type, snr_trace_count)

    if not trace_file.exists():
        print(f"[WARN] Missing trace file for {sbox_type}: {trace_file}")
        return None

    with h5py.File(trace_file, "r") as f:
        if "traces" not in f or "nonces" not in f:
            raise KeyError(f"{trace_file} is missing 'traces' or 'nonces'")

        traces_ds = f["traces"]
        nonces_ds = f["nonces"]
        total_traces = int(traces_ds.shape[0])
        n_samples = int(traces_ds.shape[1])
        key_hex = _attr_to_str(f.attrs.get("key_hex", ""))
        iv_hex = _attr_to_str(f.attrs.get("iv_hex", ""))
        n_used = min(int(max_traces_requested), total_traces)
        nonces = np.asarray(nonces_ds[:n_used], dtype=np.uint64)

    if not key_hex or not iv_hex:
        raise RuntimeError(f"{trace_file} is missing key_hex or iv_hex attributes")

    trace_counts = [int(c) for c in trace_counts_requested if int(c) <= n_used]
    if not trace_counts or trace_counts[-1] != n_used:
        trace_counts.append(n_used)

    iv_int = int(iv_hex, 16)
    key_b = bytes.fromhex(key_hex)
    k0_int_expected = int.from_bytes(key_b[0:8], byteorder="little")
    k1_int_expected = int.from_bytes(key_b[8:16], byteorder="little")
    k0_bits_expected = np.asarray(
        [(k0_int_expected >> bit) & 1 for bit in range(64)],
        dtype=np.uint8,
    )
    k1_bits_expected = np.asarray(
        [(k1_int_expected >> bit) & 1 for bit in range(64)],
        dtype=np.uint8,
    )

    peak_samples = load_snr_peak_samples(snr_trace_file) if sample_window > 0 else {}
    effective_sample_window = sample_window
    if sample_window > 0 and not peak_samples:
        print(
            f"[WARN] {sbox_type}: no SNR peak samples found in {snr_trace_file}; "
            "falling back to full trace samples."
        )
        effective_sample_window = 0

    targets = load_snr_ranked_targets(
        snr_file,
        max_targets=max_targets,
        peak_samples=peak_samples,
    )

    print("\n================= SBOX KEY-RECOVERY PROGRESSION =================")
    print(f"S-box                  : {sbox_type}")
    print(f"Trace file             : {trace_file}")
    print(f"SNR ranked file        : {snr_file}")
    print(f"SNR traces file        : {snr_trace_file}")
    print(f"Available traces       : {total_traces:,}")
    print(f"Used max traces        : {n_used:,}")
    print(f"Trace counts           : {len(trace_counts)} steps, {trace_counts[0]:,}..{trace_counts[-1]:,}")
    print(f"Samples per trace      : {n_samples}")
    print(f"CPA sample window      : {effective_sample_window if effective_sample_window > 0 else 'full trace'}")
    print(f"Leakage polarity       : {polarity}")
    print(f"Targets loaded         : {len(targets)}")
    print(f"CPA backend            : {cpa_backend}")
    print("==================================================================\n")

    total_tic = time.perf_counter()
    summaries, target_log, targets_processed, runtime_minutes = _run_target_loop_prefix(
        sbox_type=sbox_type,
        trace_file=trace_file,
        nonces=nonces,
        trace_counts=trace_counts,
        n_samples=n_samples,
        iv_int=iv_int,
        targets=targets,
        k0_bits_expected=k0_bits_expected,
        k1_bits_expected=k1_bits_expected,
        k0_int_expected=k0_int_expected,
        k1_int_expected=k1_int_expected,
        chunk_size=chunk_size,
        cpa_backend=cpa_backend,
        sample_window=effective_sample_window,
        polarity=polarity,
        save_target_log=save_target_log,
    )
    total_toc = time.perf_counter()

    print(f"\n[INFO] {sbox_type}: key-recovery progression table")
    print("trace_count, correct_key_bits, recovered_key_bits, wrong_recovered_bits, k0_correct, k1_correct")
    for summary in summaries:
        print(
            f"{summary['trace_count']}, "
            f"{summary['correct_key_bits_count']}, "
            f"{summary['known_key_bits_count']}, "
            f"{summary['wrong_recovered_key_bits_count']}, "
            f"{summary['k0_correct_recovered_count']}, "
            f"{summary['k1_correct_recovered_count']}"
        )

    result = {
        "sbox_type": sbox_type,
        "trace_file": str(trace_file),
        "snr_file": str(snr_file),
        "snr_trace_file": str(snr_trace_file),
        "n_traces_max": int(n_used),
        "snr_trace_count": int(snr_trace_count),
        "trace_counts": [int(c) for c in trace_counts],
        "n_samples": int(n_samples),
        "chunk_size": int(chunk_size),
        "cpa_sample_window_requested": int(sample_window),
        "cpa_sample_window_effective": int(effective_sample_window),
        "leakage_polarity": polarity,
        "cpa_backend": cpa_backend,
        "cpu_threads": int(max_cpu_workers),
        "targets_loaded": int(len(targets)),
        "targets_processed": int(targets_processed),
        "runtime_minutes": float((total_toc - total_tic) / 60.0),
        "target_loop_runtime_minutes": float(runtime_minutes),
        "prefix_traces": True,
        "random_subsets": False,
        "expected_k0_hex": f"{k0_int_expected:016X}",
        "expected_k1_hex": f"{k1_int_expected:016X}",
        "summaries": summaries,
        "target_log": target_log if save_target_log else [],
        "k0_recovered_count": [s["k0_recovered_count"] for s in summaries],
        "k1_recovered_count": [s["k1_recovered_count"] for s in summaries],
        "kx_recovered_count": [s["kx_recovered_count"] for s in summaries],
        "known_key_bits_count": [s["known_key_bits_count"] for s in summaries],
        "k0_correct_recovered_count": [s["k0_correct_recovered_count"] for s in summaries],
        "k1_correct_recovered_count": [s["k1_correct_recovered_count"] for s in summaries],
        "correct_key_bits_count": [s["correct_key_bits_count"] for s in summaries],
        "wrong_recovered_key_bits_count": [s["wrong_recovered_key_bits_count"] for s in summaries],
        "recovered_key_bits_percent": [s["recovered_key_bits_percent"] for s in summaries],
        "correct_key_bits_percent": [s["correct_key_bits_percent"] for s in summaries],
        "known_bit_accuracy_percent": [s["known_bit_accuracy_percent"] for s in summaries],
        "full_key_match": [bool(s["full_key_match"]) for s in summaries],
    }

    cache_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    tag = _format_trace_count_tag(n_used)
    json_file = cache_dir / f"ASCON_generic_key_recovery_progression_{sbox_type}_{tag}.json"
    result["exports"] = {
        "values": {
            **_write_per_sbox_exports(result, cache_dir),
            "json": str(json_file),
        },
        "plots": _plot_per_sbox_result(result, plot_dir, save_plots),
    }

    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    print(
        f"[INFO] {sbox_type}: wrote {json_file} "
        f"in {result['runtime_minutes']:.2f} minutes"
    )
    return result


def main():
    sboxes = _parse_sboxes(os.environ.get("ASCON_PROGRESS_SBOXES", "all"))
    max_traces = int(os.environ.get("ASCON_PROGRESS_N", "1000000"))
    traceset_size_k = int(os.environ.get("ASCON_TRACESET_SIZE_K", str(max_traces // 1000)))
    snr_trace_count = int(os.environ.get("ASCON_SNR_N", str(max_traces)))
    resolution = int(os.environ.get("ASCON_PROGRESS_RESOLUTION", "50000"))
    trace_counts = _build_trace_counts(max_traces, resolution)
    chunk_size = int(os.environ.get("ASCON_CHUNK_SIZE", "50000"))
    sample_window = int(os.environ.get("ASCON_CPA_SAMPLE_WINDOW", "201"))
    polarity = os.environ.get("ASCON_LEAKAGE_POLARITY", "both").strip().lower()
    cpa_backend = get_cpa_backend_name(os.environ.get("ASCON_CPA_DEVICE", "auto"))
    max_targets_env = os.environ.get("ASCON_MAX_TARGETS")
    max_targets = None if max_targets_env in (None, "") else int(max_targets_env)
    output_dir = Path(os.environ.get("ASCON_PROGRESS_OUTPUT_DIR", str(DEFAULT_OUTPUT_DIR)))
    plot_dir = Path(os.environ.get("ASCON_PROGRESS_PLOT_DIR", str(DEFAULT_PLOT_DIR)))
    save_plots = _env_flag("ASCON_SAVE_PLOTS", True)
    save_target_log = _env_flag("ASCON_PROGRESS_SAVE_TARGET_LOG", False)

    if max_traces <= 1:
        raise ValueError("ASCON_PROGRESS_N must be greater than 1")
    if chunk_size <= 0:
        raise ValueError("ASCON_CHUNK_SIZE must be positive")
    if sample_window < 0:
        raise ValueError("ASCON_CPA_SAMPLE_WINDOW must be >= 0")
    if polarity not in {"negative", "positive", "both"}:
        raise ValueError("ASCON_LEAKAGE_POLARITY must be one of: negative, positive, both")

    print("\n================= GENERIC KEY-RECOVERY PROGRESSION BATCH =================")
    print(f"S-boxes                : {sboxes}")
    print(f"Max prefix traces      : {max_traces:,}")
    print(f"Traceset size tag      : {traceset_size_k}k")
    print(f"SNR cache trace count  : {snr_trace_count:,}")
    print(f"Trace count steps      : {len(trace_counts)}")
    print(f"First/last count       : {trace_counts[0]:,} / {trace_counts[-1]:,}")
    print(f"Chunk size             : {chunk_size}")
    print(f"CPA sample window      : {sample_window if sample_window > 0 else 'full trace'}")
    print(f"Leakage polarity       : {polarity}")
    print(f"CPA backend            : {cpa_backend}")
    print(f"CPU threads            : {max_cpu_workers}")
    print(f"Max targets            : {max_targets if max_targets is not None else 'all'}")
    print(f"Output dir             : {output_dir}")
    print(f"Plot dir               : {plot_dir}")
    print(f"Save plots             : {'yes' if save_plots else 'no'}")
    print(f"Save target log        : {'yes' if save_target_log else 'no'}")
    print("============================================================================\n")

    batch_tic = time.perf_counter()
    results = {}

    for sbox_type in sboxes:
        result = _run_one_sbox(
            sbox_type=sbox_type,
            max_traces_requested=max_traces,
            traceset_size_k=traceset_size_k,
            snr_trace_count=snr_trace_count,
            trace_counts_requested=trace_counts,
            chunk_size=chunk_size,
            sample_window=sample_window,
            polarity=polarity,
            cpa_backend=cpa_backend,
            max_targets=max_targets,
            output_dir=output_dir,
            plot_dir=plot_dir,
            save_plots=save_plots,
            save_target_log=save_target_log,
        )
        if result is not None:
            results[sbox_type] = result

    batch_toc = time.perf_counter()
    output_dir.mkdir(parents=True, exist_ok=True)

    combined = {
        "sboxes": list(results.keys()),
        "n_traces_max": int(max_traces),
        "trace_counts": [int(c) for c in trace_counts],
        "runtime_minutes": float((batch_toc - batch_tic) / 60.0),
        "config": {
            "chunk_size": int(chunk_size),
            "sample_window": int(sample_window),
            "polarity": polarity,
            "cpa_backend": cpa_backend,
            "cpu_threads": int(max_cpu_workers),
            "max_targets": max_targets,
            "prefix_traces": True,
            "random_subsets": False,
            "save_target_log": bool(save_target_log),
        },
        "results": results,
    }

    combined["exports"] = {
        "values": _write_combined_exports(combined, output_dir),
        "plots": _plot_combined_results(combined, plot_dir, save_plots),
    }

    tag = _format_trace_count_tag(max_traces)
    combined_json = output_dir / f"ASCON_generic_key_recovery_progression_all_sboxes_{tag}.json"
    with open(combined_json, "w", encoding="utf-8") as f:
        json.dump(combined, f, indent=2)

    print("\n[INFO] Finished key-recovery progression batch")
    print(f"[INFO] Combined JSON : {combined_json}")
    print(f"[INFO] Combined CSV  : {combined['exports']['values']['csv']}")
    if save_plots:
        print(f"[INFO] Combined plots: {plot_dir}")


if __name__ == "__main__":
    main()
