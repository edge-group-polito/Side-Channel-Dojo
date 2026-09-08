#!/usr/bin/env python3
"""
ASCON key-recovery progression for all generic S-boxes.

The trace files are streamed from row 0 to N. This keeps memory bounded for the
large HDF5 trace sets and matches the assumption that trace capture order was
already randomized.

Use --help for command-line options. Environment variables with the old
ASCON_* names are still accepted as defaults for batch compatibility.
"""

import argparse
import importlib
import os
import subprocess

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib-ascon")

# ---------------------------------------------------------------------------
# CPU configuration: set before importing NumPy.
# ---------------------------------------------------------------------------
_pre_parser = argparse.ArgumentParser(add_help=False)
_pre_parser.add_argument("--max-cpu-workers", type=int, default=None)
_pre_parser.add_argument("--implementation", choices=["sw", "hw"], default="sw")
_pre_parser.add_argument("--include-comb", action=argparse.BooleanOptionalAction, default=True)
_pre_args, _ = _pre_parser.parse_known_args()

_max_cpu_workers_env = os.environ.get("ASCON_MAX_CPU_WORKERS")
if _pre_args.max_cpu_workers is not None:
    max_cpu_workers = int(_pre_args.max_cpu_workers)
elif _max_cpu_workers_env not in (None, ""):
    max_cpu_workers = int(_max_cpu_workers_env)
else:
    max_cpu_workers = os.cpu_count() or 1

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


def _progress_bars_enabled() -> bool:
    value = os.environ.get("ASCON_PROGRESS_BARS")
    if value in (None, ""):
        return sys.stderr.isatty()
    return value.strip().lower() not in {"0", "false", "no", "off"}


TQDM_DISABLE = not _progress_bars_enabled()


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
ASCON_SCRIPT_DIR = SCA_DIR / "ASCON"

IMPLEMENTATION = _pre_args.implementation

if IMPLEMENTATION == "hw":
    TRACESET_DIR = DOJO_ROOT / "sw" / "traceset" / "ASCON" / "hw" / "ascon_init"
    BASE_CACHE_DIR = ASCON_SCRIPT_DIR / "hw" / "cache" / "ascon_init"
    DEFAULT_OUTPUT_DIR = BASE_CACHE_DIR / "key_recovery_progression_all_sboxes"
    DEFAULT_PLOT_DIR = ASCON_SCRIPT_DIR / "hw" / "plot" / "ascon_init_key_recovery_progression_all_sboxes"
    DEFAULT_SNR_SCRIPT = ASCON_SCRIPT_DIR / "hw" / "ascon_init_ASCON_snr.py"
    TRACE_FILE_PREFIX = "ascon_init"
    CPA_HELPER_DIR = ASCON_SCRIPT_DIR / "hw"
    CPA_HELPER_MODULE = "ascon_init_ASCON_cpa_generic_all_registers"
    DEFAULT_ANALYSIS_MAX_TIME_US = 1.5
else:
    TRACESET_DIR = DOJO_ROOT / "sw" / "traceset" / "ASCON" / "sw"
    BASE_CACHE_DIR = ASCON_SCRIPT_DIR / "sw" / "cache"
    DEFAULT_OUTPUT_DIR = BASE_CACHE_DIR / "key_recovery_progression_all_sboxes"
    DEFAULT_PLOT_DIR = ASCON_SCRIPT_DIR / "sw" / "plot" / "key_recovery_progression_all_sboxes"
    DEFAULT_SNR_SCRIPT = SCRIPT_DIR / "xheep_ASCON_snr.py"
    TRACE_FILE_PREFIX = "ascon_opt32"
    CPA_HELPER_DIR = SCRIPT_DIR
    CPA_HELPER_MODULE = "xheep_ASCON_cpa_generic_all_registers"
    DEFAULT_ANALYSIS_MAX_TIME_US = 0.0


def _repo_relative_path(value, default: Path) -> Path:
    if value in (None, ""):
        return Path(default)
    path = Path(value)
    if not path.is_absolute():
        path = (DOJO_ROOT / path).resolve()
    return path

sys.path.insert(0, str(CPA_HELPER_DIR))
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(ASCON_SCRIPT_DIR))
sys.path.insert(0, str(SCA_DIR))

from analyzer.attack.ascon.xheep_ascon_cpa.ascon_cpa import (  # noqa: E402
    ascon_cpa_finalize_corrmax_accumulators,
    ascon_cpa_init_accumulators,
    ascon_cpa_update_accumulators,
    get_cpa_backend_name,
)

from ascon_plot_style import (  # noqa: E402
    KEY_COLORS,
    SBOX_ORDER_HW,
    SBOX_ORDER_SW,
    apply_plot_style,
    save_figure,
    sbox_color,
)

_CPA_HELPERS = importlib.import_module(CPA_HELPER_MODULE)
bits_to_u64 = _CPA_HELPERS.bits_to_u64
compute_H64_chunk = _CPA_HELPERS.compute_H64_chunk
expand_reduced_hypotheses = _CPA_HELPERS.expand_reduced_hypotheses
filter_hypotheses_by_known_bits = _CPA_HELPERS.filter_hypotheses_by_known_bits
find_snr_file = _CPA_HELPERS.find_snr_file
find_snr_trace_file = _CPA_HELPERS.find_snr_trace_file
get_target_key_dependencies = _CPA_HELPERS.get_target_key_dependencies
load_snr_peak_samples = _CPA_HELPERS.load_snr_peak_samples
load_snr_ranked_targets = _CPA_HELPERS.load_snr_ranked_targets
load_snr_ranked_targets_from_traces = getattr(
    _CPA_HELPERS,
    "load_snr_ranked_targets_from_traces",
    None,
)
compute_analysis_sample_stop = getattr(
    _CPA_HELPERS,
    "compute_analysis_sample_stop",
    lambda n_samples, sampling_interval, max_time_us: int(n_samples),
)
propagate_group_constraints = _CPA_HELPERS.propagate_group_constraints
propagate_hypothesis_constraints = _CPA_HELPERS.propagate_hypothesis_constraints
reduce_full_hypotheses = _CPA_HELPERS.reduce_full_hypotheses
signed_corr_at_samples_from_accumulators = _CPA_HELPERS.signed_corr_at_samples_from_accumulators
target_sample_window = _CPA_HELPERS.target_sample_window
target_to_k_idx = _CPA_HELPERS.target_to_k_idx


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------
INCLUDE_COMB = bool(_pre_args.include_comb)

ALL_SBOXES = list(SBOX_ORDER_HW if IMPLEMENTATION == "hw" and INCLUDE_COMB else SBOX_ORDER_SW)


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


def _normalize_cpa_policy(value: str) -> str:
    policy = str(value).strip().lower().replace("-", "_")
    if policy in {"dependency", "dependencyaware", "equation_aware"}:
        policy = "dependency_aware"
    elif policy in {"generic", "normal"}:
        policy = "baseline"
    if policy not in {"dependency_aware", "baseline"}:
        raise ValueError("CPA policy must be one of: dependency_aware, baseline")
    return policy


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value in (None, ""):
        return int(default)
    return int(value)


def _env_optional_int(name: str):
    value = os.environ.get(name)
    if value in (None, ""):
        return None
    return int(value)


def _build_arg_parser():
    parser = argparse.ArgumentParser(
        description="Run ASCON generic key-recovery progression for one or more S-boxes.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--implementation",
        choices=["sw", "hw"],
        default=IMPLEMENTATION,
        help="Trace implementation family.",
    )
    parser.add_argument(
        "--include-comb",
        action=argparse.BooleanOptionalAction,
        default=INCLUDE_COMB,
        help="Include the combinational HW S-box when --implementation hw and --sboxes all.",
    )
    parser.add_argument(
        "--sboxes",
        default=os.environ.get("ASCON_PROGRESS_SBOXES", "all"),
        help='Comma-separated S-box list, or "all".',
    )
    parser.add_argument(
        "--max-traces",
        type=int,
        default=_env_int("ASCON_PROGRESS_N", 1000000),
        help="Maximum prefix traces used by CPA.",
    )
    parser.add_argument(
        "--traceset-size-k",
        type=int,
        default=_env_optional_int("ASCON_TRACESET_SIZE_K"),
        help="Trace-file size tag in thousands, e.g. 1000 for *_1000k.h5.",
    )
    parser.add_argument(
        "--snr-traces",
        type=int,
        default=_env_optional_int("ASCON_SNR_N"),
        help="Profiled SNR trace count. Defaults to --max-traces.",
    )
    parser.add_argument(
        "--snr-selection-mode",
        choices=["profiled", "prefix"],
        default=os.environ.get("ASCON_SNR_SELECTION_MODE", "prefix"),
        help="profiled uses one SNR cache; prefix uses a matching SNR cache per trace count.",
    )
    parser.add_argument(
        "--resolution",
        type=int,
        default=_env_int("ASCON_PROGRESS_RESOLUTION", 50000),
        help="Trace-count step.",
    )
    parser.add_argument(
        "--trace-counts",
        default=os.environ.get("ASCON_PROGRESS_COUNTS"),
        help="Explicit comma-separated trace counts. Overrides --resolution.",
    )
    parser.add_argument(
        "--plot-only",
        action="store_true",
        help="Load an existing combined JSON and regenerate exports/plots without CPA.",
    )
    parser.add_argument(
        "--plot-input-json",
        default=os.environ.get("ASCON_PROGRESS_PLOT_INPUT_JSON"),
        help="Existing combined JSON used by --plot-only.",
    )
    parser.add_argument(
        "--replace-result-json",
        default=os.environ.get("ASCON_PROGRESS_REPLACE_RESULT_JSON"),
        help=(
            "Comma-separated per-S-box or combined JSON result(s) to merge into "
            "--plot-input-json during --plot-only."
        ),
    )
    parser.add_argument(
        "--plot-x-scale",
        choices=["linear", "log"],
        default=os.environ.get("ASCON_PROGRESS_PLOT_X_SCALE", "log"),
        help="X-axis scale for progression plots.",
    )
    parser.add_argument(
        "--drop-trace-counts",
        default=os.environ.get("ASCON_PROGRESS_DROP_TRACE_COUNTS"),
        help="Comma-separated trace counts to remove from loaded plot-only results.",
    )
    parser.set_defaults(
        append_max=_env_flag("ASCON_PROGRESS_APPEND_MAX", True),
        save_plots=_env_flag("ASCON_SAVE_PLOTS", True),
        save_target_log=_env_flag("ASCON_PROGRESS_SAVE_TARGET_LOG", False),
        auto_snr=_env_flag("ASCON_AUTO_SNR", True),
    )
    parser.add_argument("--append-max", dest="append_max", action="store_true")
    parser.add_argument("--no-append-max", dest="append_max", action="store_false")
    parser.add_argument(
        "--max-targets",
        type=int,
        default=_env_optional_int("ASCON_MAX_TARGETS"),
        help="Optional cap on SNR-ranked targets.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=_env_int("ASCON_CHUNK_SIZE", 50000),
        help="CPA streaming chunk size.",
    )
    parser.add_argument(
        "--sample-window",
        type=int,
        default=_env_int("ASCON_CPA_SAMPLE_WINDOW", 201),
        help="CPA sample window around SNR peak. Use 0 for full trace.",
    )
    parser.add_argument(
        "--analysis-max-time-us",
        type=float,
        default=float(os.environ.get("ASCON_ANALYSIS_MAX_TIME_US", DEFAULT_ANALYSIS_MAX_TIME_US)),
        help="Only analyze samples up to this time when supported. Use 0 for the full trace.",
    )
    parser.add_argument(
        "--polarity",
        choices=["negative", "positive", "both"],
        default=os.environ.get("ASCON_LEAKAGE_POLARITY", "negative"),
        help="Leakage polarity interpretation.",
    )
    parser.add_argument(
        "--cpa-policy",
        default=os.environ.get("ASCON_CPA_POLICY", "dependency_aware"),
        help="CPA recovery policy: dependency_aware or baseline.",
    )
    parser.add_argument(
        "--mixed-top-groups",
        type=int,
        default=_env_int("ASCON_MIXED_TOP_GROUPS", 1),
        help="Dependency-aware mixed-target groups retained at each checkpoint.",
    )
    parser.add_argument(
        "--mixed-min-fact-support",
        type=int,
        default=_env_int("ASCON_MIXED_MIN_FACT_SUPPORT", 2),
        help="Mixed-target constraints required before committing a fact.",
    )
    parser.add_argument(
        "--cpa-device",
        choices=["auto", "cpu", "gpu"],
        default=os.environ.get("ASCON_CPA_DEVICE", "auto"),
        help="CPA backend.",
    )
    parser.add_argument(
        "--max-cpu-workers",
        type=int,
        default=max_cpu_workers,
        help="NumPy/BLAS thread limit. Parsed early before NumPy import.",
    )
    parser.add_argument(
        "--output-dir",
        default=os.environ.get("ASCON_PROGRESS_OUTPUT_DIR"),
        help="Output directory for JSON/CSV/NPZ files.",
    )
    parser.add_argument(
        "--plot-dir",
        default=os.environ.get("ASCON_PROGRESS_PLOT_DIR"),
        help="Output directory for plots.",
    )
    parser.add_argument(
        "--cache-dir",
        default=os.environ.get("ASCON_CACHE_DIR"),
        help="Base directory for per-S-box SNR caches and progression exports.",
    )
    parser.add_argument("--save-plots", dest="save_plots", action="store_true")
    parser.add_argument("--no-save-plots", dest="save_plots", action="store_false")
    parser.add_argument("--save-target-log", dest="save_target_log", action="store_true")
    parser.add_argument("--no-save-target-log", dest="save_target_log", action="store_false")
    parser.add_argument(
        "--auto-snr",
        dest="auto_snr",
        action="store_true",
        help="Generate missing SNR caches before continuing.",
    )
    parser.add_argument(
        "--no-auto-snr",
        dest="auto_snr",
        action="store_false",
        help="Fail instead of generating missing SNR caches.",
    )
    parser.add_argument(
        "--snr-script",
        default=os.environ.get("ASCON_SNR_SCRIPT", str(DEFAULT_SNR_SCRIPT)),
        help="SNR generator script used by --auto-snr.",
    )
    parser.add_argument(
        "--snr-chunk-size",
        type=int,
        default=_env_int("ASCON_SNR_CHUNK_SIZE", 10000),
        help="Chunk size passed to the SNR generator when --auto-snr is enabled.",
    )
    parser.add_argument(
        "--snr-device",
        choices=["cpu", "gpu", "auto"],
        default=os.environ.get("ASCON_SNR_DEVICE", "cpu"),
        help="Device passed to the SNR generator when --auto-snr is enabled.",
    )
    return parser


def _format_trace_count_tag(trace_count: int) -> str:
    trace_count = int(trace_count)
    if trace_count % 1000 == 0:
        return f"{trace_count // 1000}k"
    return str(trace_count)


def _result_tag(trace_count: int, snr_selection_mode: str) -> str:
    return f"{_format_trace_count_tag(trace_count)}_{snr_selection_mode}_snr"


def _build_trace_counts(max_traces: int, resolution: int, explicit=None, append_max=True):
    if explicit not in (None, ""):
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


def _parse_trace_count_set(value):
    if value in (None, ""):
        return set()
    return {int(x.strip()) for x in str(value).split(",") if x.strip()}


def _parse_path_list(value):
    if value in (None, ""):
        return []
    return [item.strip() for item in str(value).split(",") if item.strip()]


def _attr_to_str(value):
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


def _find_trace_file(
    sbox_type: str,
    traceset_size_k: int,
    max_traces_requested: int,
    strict_traceset_size: bool = False,
) -> Path:
    preferred = TRACESET_DIR / f"{TRACE_FILE_PREFIX}_{sbox_type}_{traceset_size_k}k.h5"
    if preferred.exists():
        return preferred

    if strict_traceset_size:
        return preferred

    candidates = sorted(TRACESET_DIR.glob(f"{TRACE_FILE_PREFIX}_{sbox_type}_*.h5"))
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


def _snr_cache_paths_for_count(cache_dir: Path, sbox_type: str, trace_count: int):
    tag = _format_trace_count_tag(trace_count)
    return (
        cache_dir / f"snr_ranked_{sbox_type}_{tag}.h5",
        cache_dir / f"snr_traces_{sbox_type}_{tag}.h5",
    )


def _snr_cache_metadata_matches(
    path: Path,
    expected_n_traces=None,
    expected_n_samples=None,
) -> bool:
    try:
        with h5py.File(path, "r") as f:
            if expected_n_traces is not None and "n_traces" in f.attrs:
                if int(f.attrs["n_traces"]) != int(expected_n_traces):
                    return False
            if expected_n_samples is not None and "n_samples" in f.attrs:
                if int(f.attrs["n_samples"]) != int(expected_n_samples):
                    return False
    except OSError:
        return False
    return True


def _snr_cache_is_usable(
    snr_file: Path,
    snr_trace_file: Path,
    sample_window: int,
    expected_n_traces=None,
    expected_n_samples=None,
) -> bool:
    if not snr_file.exists():
        return False
    if not _snr_cache_metadata_matches(
        snr_file,
        expected_n_traces=expected_n_traces,
        expected_n_samples=expected_n_samples,
    ):
        return False
    if int(sample_window) > 0 and not snr_trace_file.exists():
        return False
    if int(sample_window) > 0 and not _snr_cache_metadata_matches(
        snr_trace_file,
        expected_n_traces=expected_n_traces,
        expected_n_samples=expected_n_samples,
    ):
        return False
    return True


def _generate_snr_cache(
    sbox_type: str,
    trace_count: int,
    traceset_size_k: int,
    base_cache_dir: Path,
    snr_script: Path,
    snr_chunk_size: int,
    snr_device: str,
    analysis_max_time_us: float,
):
    snr_script = Path(snr_script)
    if not snr_script.is_absolute():
        snr_script = (DOJO_ROOT / snr_script).resolve()

    if not snr_script.exists():
        raise FileNotFoundError(f"SNR generator script not found: {snr_script}")

    cmd = [
        sys.executable,
        str(snr_script),
        "--sbox",
        str(sbox_type),
        "--trace-sbox",
        str(sbox_type),
        "--leakage-model-sbox",
        str(sbox_type),
        "--n-traces",
        str(int(trace_count)),
        "--traceset-size-k",
        str(int(traceset_size_k)),
        "--cache-dir",
        str(base_cache_dir),
        "--chunk-size",
        str(int(snr_chunk_size)),
        "--device",
        str(snr_device),
        "--max-cpu-workers",
        str(int(max_cpu_workers)),
    ]
    if IMPLEMENTATION == "hw":
        cmd.extend(["--analysis-max-time-us", str(float(analysis_max_time_us))])

    print("[INFO] Missing SNR cache; generating it now:")
    print("       " + " ".join(cmd))
    subprocess.run(cmd, cwd=str(DOJO_ROOT), check=True)


def _load_snr_targets_for_mode(
    cache_dir: Path,
    sbox_type: str,
    snr_selection_mode: str,
    trace_count: int,
    profiled_snr_trace_count: int,
    sample_window: int,
    max_targets,
    traceset_size_k: int,
    base_cache_dir: Path,
    auto_snr: bool,
    snr_script: Path,
    snr_chunk_size: int,
    snr_device: str,
    analysis_sample_stop,
    analysis_max_time_us: float,
):
    if snr_selection_mode == "profiled":
        snr_count = int(profiled_snr_trace_count)
    elif snr_selection_mode == "prefix":
        snr_count = int(trace_count)
    else:
        raise ValueError("snr_selection_mode must be one of: profiled, prefix")

    snr_file, snr_trace_file = _snr_cache_paths_for_count(cache_dir, sbox_type, snr_count)
    expected_n_samples = analysis_sample_stop if int(sample_window) > 0 else None
    if not _snr_cache_is_usable(
        snr_file,
        snr_trace_file,
        sample_window,
        expected_n_traces=snr_count,
        expected_n_samples=expected_n_samples,
    ):
        if auto_snr:
            _generate_snr_cache(
                sbox_type=sbox_type,
                trace_count=snr_count,
                traceset_size_k=traceset_size_k,
                base_cache_dir=base_cache_dir,
                snr_script=snr_script,
                snr_chunk_size=snr_chunk_size,
                snr_device=snr_device,
                analysis_max_time_us=analysis_max_time_us,
            )
        elif snr_selection_mode == "profiled":
            fallback_snr_file = find_snr_file(cache_dir, sbox_type, snr_count)
            fallback_snr_trace_file = find_snr_trace_file(cache_dir, sbox_type, snr_count)
            if _snr_cache_is_usable(
                fallback_snr_file,
                fallback_snr_trace_file,
                sample_window,
                expected_n_traces=snr_count,
                expected_n_samples=expected_n_samples,
            ):
                snr_file = fallback_snr_file
                snr_trace_file = fallback_snr_trace_file

    if not _snr_cache_is_usable(
        snr_file,
        snr_trace_file,
        sample_window,
        expected_n_traces=snr_count,
        expected_n_samples=expected_n_samples,
    ):
        missing = [str(snr_file)]
        if int(sample_window) > 0:
            missing.append(str(snr_trace_file))
        raise FileNotFoundError(
            "Missing required SNR cache file(s): "
            + ", ".join(missing)
            + ". Re-run with --auto-snr or generate them with xheep_ASCON_snr.py."
        )

    peak_samples = {}
    if sample_window > 0:
        try:
            peak_samples = load_snr_peak_samples(
                snr_trace_file,
                sample_stop=analysis_sample_stop,
            )
        except TypeError:
            peak_samples = load_snr_peak_samples(snr_trace_file)

    effective_sample_window = sample_window
    if sample_window > 0 and not peak_samples:
        print(
            f"[WARN] {sbox_type}: no SNR peak samples found in {snr_trace_file}; "
            "falling back to full trace samples."
        )
        effective_sample_window = 0

    if load_snr_ranked_targets_from_traces is not None and snr_trace_file.exists():
        targets = load_snr_ranked_targets_from_traces(
            snr_trace_file,
            max_targets=max_targets,
            sample_stop=analysis_sample_stop,
        )
    else:
        targets = load_snr_ranked_targets(
            snr_file,
            max_targets=max_targets,
            peak_samples=peak_samples,
        )

    return {
        "snr_file": snr_file,
        "snr_trace_file": snr_trace_file,
        "targets": targets,
        "effective_sample_window": int(effective_sample_window),
    }


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
        "equation_constraints": [],
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


def _target_is_useful_for_policy(k_idx, state, cpa_policy: str, dependencies=()) -> bool:
    if cpa_policy == "baseline":
        return _target_is_useful_for_state(k_idx, state)

    indices = np.asarray(k_idx, dtype=int)
    dependencies = tuple(dependencies)
    if dependencies == ("k0",):
        return not np.all(state["k0_rec"][indices])
    if dependencies == ("k1",):
        return not np.all(state["k1_rec"][indices])
    if dependencies == ("k0", "k1"):
        return _target_is_useful_for_state(indices, state)
    return False


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

    The CPA accumulates every raw hypothesis. At each trace-count checkpoint,
    this function groups only over the prefix used at that checkpoint, avoiding
    over-committing bits that are distinguishable only by later traces.
    """
    canonical_to_group = {}
    key_hyp_groups = []
    rep_indices = []

    for hyp in range(len(signatures)):
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
    cpa_policy: str,
    compatible_hypotheses_by_count,
    mixed_top_groups: int,
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
    target_info = get_target_key_dependencies(
        iv_int,
        attacked_state_reg,
        attacked_bit,
        sbox_type,
    )
    hypothesis_mode = "full" if cpa_policy == "baseline" else "reduced"
    dependency_kind = (
        "mixed" if hypothesis_mode == "full" else target_info["dependency_kind"]
    )
    dependencies = (
        () if cpa_policy == "baseline" else tuple(target_info["key_dependencies"])
    )
    n_hypotheses = 64 if hypothesis_mode == "full" else int(target_info["n_hypotheses"])
    if n_hypotheses <= 0:
        return []

    acc = ascon_cpa_init_accumulators(
        n_samples=n_cpa_samples,
        n_hypotheses=n_hypotheses,
        backend=cpa_backend,
    )
    signatures = [bytearray() for _ in range(n_hypotheses)]

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
                hypothesis_mode=hypothesis_mode,
            )

            if h64 is False:
                raise RuntimeError(
                    f"No leakage hypotheses for {attacked_state_reg}[{attacked_bit}]"
                )

            ascon_cpa_update_accumulators(
                acc,
                traces_chunk,
                h64.astype(np.float32, copy=False),
            )

            for hyp in range(n_hypotheses):
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
            compatible_full = set(
                map(int, compatible_hypotheses_by_count[checkpoint_idx])
            )
            compatible = (
                compatible_full
                if hypothesis_mode == "full"
                else set(reduce_full_hypotheses(compatible_full, dependency_kind))
            )
            ranked_groups = []
            for group_idx, group in enumerate(oriented_groups):
                rep = int(rep_indices[group_idx])
                oriented = _select_key_group(
                    group,
                    float(signed_corr[rep]),
                    polarity,
                )
                members = [int(hyp) for hyp in oriented if int(hyp) in compatible]
                polarity_overridden = False
                if not members:
                    members = [
                        int(hyp) for hyp in group["all"] if int(hyp) in compatible
                    ]
                    polarity_overridden = bool(members)
                if members:
                    ranked_groups.append(
                        {
                            "group_idx": int(group_idx),
                            "members": members,
                            "corr": float(corr_group[group_idx]),
                            "polarity_overridden": polarity_overridden,
                        }
                    )

            ranked_groups.sort(key=lambda item: item["corr"], reverse=True)
            retain = mixed_top_groups if len(dependencies) == 2 else 1
            retained_groups = ranked_groups[:retain]
            if retained_groups:
                best_group_idx = int(retained_groups[0]["group_idx"])
                best_key_group_reduced = sorted(
                    {
                        hypothesis
                        for retained in retained_groups
                        for hypothesis in retained["members"]
                    }
                )
            else:
                best_group_idx = int(np.argmax(corr_group))
                best_key_group_reduced = []

            rep_hyp = int(rep_indices[best_group_idx])
            best_key_group = (
                best_key_group_reduced
                if hypothesis_mode == "full"
                else expand_reduced_hypotheses(
                    best_key_group_reduced,
                    dependency_kind,
                )
            )

            results.append(
                {
                    "trace_count": int(next_checkpoint),
                    "attacked_state_reg": attacked_state_reg,
                    "attacked_bit": attacked_bit,
                    "k_idx": k_idx,
                    "best_key_group": best_key_group,
                    "best_key_group_reduced": best_key_group_reduced,
                    "dependencies": list(dependencies),
                    "dependency_kind": target_info["dependency_kind"],
                    "hypothesis_mode": hypothesis_mode,
                    "n_hypotheses": n_hypotheses,
                    "num_groups": int(len(rep_indices)),
                    "best_group_idx": best_group_idx,
                    "best_rep_hypothesis": rep_hyp,
                    "best_corr": float(corr_group[best_group_idx]),
                    "best_signed_corr": float(signed_corr[rep_hyp]),
                    "best_sample": int(argmax_samples[rep_hyp] + sample_start),
                    "retained_group_indices": [
                        item["group_idx"] for item in retained_groups
                    ],
                    "polarity_overridden": any(
                        item["polarity_overridden"] for item in retained_groups
                    ),
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
    cpa_policy: str,
    mixed_top_groups: int,
    mixed_min_fact_support: int,
    save_target_log: bool,
):
    states = [_state_template() for _ in trace_counts]
    target_log = []
    targets_processed = 0
    tic = time.perf_counter()

    if cpa_policy == "dependency_aware":
        def equation_priority(target):
            target_info = get_target_key_dependencies(
                iv_int,
                target["reg"],
                int(target["bit"]),
                sbox_type,
            )
            n_hypotheses = int(target_info["n_hypotheses"])
            if n_hypotheses == 8:
                return 0
            if n_hypotheses == 64:
                return 1
            return 2

        # Stable sort preserves SNR order inside each dependency class.
        targets = sorted(targets, key=equation_priority)

    for target in tqdm(
        targets,
        desc=f"{sbox_type}: prefix CPA targets",
        disable=TQDM_DISABLE,
    ):
        k_idx = target_to_k_idx(target["reg"], int(target["bit"]))
        dependencies = ()
        if cpa_policy == "dependency_aware":
            target_info = get_target_key_dependencies(
                iv_int,
                target["reg"],
                int(target["bit"]),
                sbox_type,
            )
            dependencies = tuple(target_info["key_dependencies"])
            if not dependencies:
                for state in states:
                    if not state["full_key_recovered"]:
                        state["targets_skipped"] += 1
                continue

        active_state_indices = []
        active_counts = []
        compatible_hypotheses_by_count = []

        for state_idx, state in enumerate(states):
            if state["full_key_recovered"]:
                continue

            if _target_is_useful_for_policy(k_idx, state, cpa_policy, dependencies):
                active_state_indices.append(state_idx)
                active_counts.append(int(trace_counts[state_idx]))
                if cpa_policy == "dependency_aware":
                    compatible_hypotheses_by_count.append(
                        filter_hypotheses_by_known_bits(
                            range(64),
                            k_idx,
                            state["k0_rec_bits"],
                            state["k0_rec"],
                            state["k1_rec_bits"],
                            state["k1_rec"],
                            state["kx_rec_bits"],
                            state["kx_rec"],
                        )
                    )
                else:
                    compatible_hypotheses_by_count.append(list(range(64)))
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
            cpa_policy=cpa_policy,
            compatible_hypotheses_by_count=compatible_hypotheses_by_count,
            mixed_top_groups=mixed_top_groups,
        )
        targets_processed += 1

        for state_idx, result in zip(active_state_indices, target_results):
            state = states[state_idx]
            if state["full_key_recovered"]:
                continue

            if cpa_policy == "baseline" or len(result["dependencies"]) == 1:
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

            if cpa_policy == "dependency_aware" and result["best_key_group"]:
                state["equation_constraints"].append(
                    {
                        "target": (
                            result["attacked_state_reg"],
                            int(result["attacked_bit"]),
                        ),
                        "dependencies": tuple(result["dependencies"]),
                        "key_indices": result["k_idx"].copy(),
                        "hypotheses": list(map(int, result["best_key_group"])),
                    }
                )
                propagate_hypothesis_constraints(
                    state["equation_constraints"],
                    state["k0_rec_bits"],
                    state["k0_rec"],
                    state["k1_rec_bits"],
                    state["k1_rec"],
                    state["kx_rec_bits"],
                    state["kx_rec"],
                    verbose=False,
                    minimum_fact_support=mixed_min_fact_support,
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
                        "dependencies": list(result["dependencies"]),
                        "dependency_kind": result.get("dependency_kind"),
                        "hypothesis_mode": result.get("hypothesis_mode"),
                        "n_hypotheses": result.get("n_hypotheses"),
                        "retained_group_indices": result.get("retained_group_indices"),
                        "polarity_overridden": result.get("polarity_overridden"),
                        "equation_constraints": int(
                            len(state["equation_constraints"])
                        ),
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


def _run_trace_counts_with_prefix_snr(
    sbox_type: str,
    trace_file: Path,
    nonces: np.ndarray,
    trace_counts,
    n_samples: int,
    iv_int: int,
    cache_dir: Path,
    snr_trace_count: int,
    k0_bits_expected,
    k1_bits_expected,
    k0_int_expected: int,
    k1_int_expected: int,
    chunk_size: int,
    cpa_backend: str,
    sample_window: int,
    polarity: str,
    cpa_policy: str,
    mixed_top_groups: int,
    mixed_min_fact_support: int,
    max_targets,
    traceset_size_k: int,
    base_cache_dir: Path,
    auto_snr: bool,
    snr_script: Path,
    snr_chunk_size: int,
    snr_device: str,
    save_target_log: bool,
    analysis_sample_stop,
    analysis_max_time_us: float,
):
    summaries = []
    target_log = []
    targets_processed_total = 0
    snr_runs = []
    tic = time.perf_counter()

    for trace_count in trace_counts:
        snr_info = _load_snr_targets_for_mode(
            cache_dir=cache_dir,
            sbox_type=sbox_type,
            snr_selection_mode="prefix",
            trace_count=int(trace_count),
            profiled_snr_trace_count=snr_trace_count,
            sample_window=sample_window,
            max_targets=max_targets,
            traceset_size_k=traceset_size_k,
            base_cache_dir=base_cache_dir,
            auto_snr=auto_snr,
            snr_script=snr_script,
            snr_chunk_size=snr_chunk_size,
            snr_device=snr_device,
            analysis_sample_stop=analysis_sample_stop,
            analysis_max_time_us=analysis_max_time_us,
        )
        targets = snr_info["targets"]
        effective_sample_window = int(snr_info["effective_sample_window"])

        print(
            f"\n[INFO] {sbox_type}: trace_count={int(trace_count):,}, "
            f"SNR ranked={snr_info['snr_file']}, targets={len(targets)}, "
            f"CPA sample window="
            f"{effective_sample_window if effective_sample_window > 0 else 'full trace'}"
        )

        one_summaries, one_target_log, one_targets_processed, _ = _run_target_loop_prefix(
            sbox_type=sbox_type,
            trace_file=trace_file,
            nonces=nonces,
            trace_counts=[int(trace_count)],
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
            cpa_policy=cpa_policy,
            mixed_top_groups=mixed_top_groups,
            mixed_min_fact_support=mixed_min_fact_support,
            save_target_log=save_target_log,
        )

        summary = one_summaries[0]
        summaries.append(summary)
        targets_processed_total += int(one_targets_processed)
        if save_target_log:
            for item in one_target_log:
                item["snr_file"] = str(snr_info["snr_file"])
                item["snr_trace_file"] = str(snr_info["snr_trace_file"])
            target_log.extend(one_target_log)

        snr_runs.append(
            {
                "trace_count": int(trace_count),
                "snr_file": str(snr_info["snr_file"]),
                "snr_trace_file": str(snr_info["snr_trace_file"]),
                "targets_loaded": int(len(targets)),
                "targets_processed": int(one_targets_processed),
                "cpa_sample_window_effective": int(effective_sample_window),
            }
        )

    toc = time.perf_counter()
    return (
        summaries,
        target_log,
        int(targets_processed_total),
        float((toc - tic) / 60.0),
        snr_runs,
    )


# ---------------------------------------------------------------------------
# Exports and plotting
# ---------------------------------------------------------------------------
def _import_matplotlib():
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.ticker as mticker

        apply_plot_style(plt)
        return plt, mticker
    except Exception as exc:
        print(f"[WARN] Plotting disabled: could not import matplotlib ({exc})")
        return None, None


def _format_trace_tick(value, _position):
    value = int(round(float(value)))
    if value >= 1_000_000 and value % 1_000_000 == 0:
        return f"{value // 1_000_000}M"
    if value >= 1_000 and value % 1_000 == 0:
        return f"{value // 1_000}k"
    return str(value)


def _format_axes_for_traces(ax, mticker, x_scale: str):
    if x_scale == "log":
        ax.set_xscale("log")
        ax.xaxis.set_major_locator(mticker.LogLocator(base=10))
        ax.xaxis.set_major_formatter(mticker.FuncFormatter(_format_trace_tick))
        ax.xaxis.set_minor_locator(mticker.LogLocator(base=10, subs=range(2, 10)))
        ax.xaxis.set_minor_formatter(mticker.NullFormatter())
        ax.grid(True, alpha=0.30, which="both")
        return

    formatter = mticker.ScalarFormatter(useMathText=True)
    formatter.set_powerlimits((0, 0))
    ax.xaxis.set_major_formatter(formatter)
    ax.ticklabel_format(axis="x", style="sci", scilimits=(0, 0))
    ax.xaxis.get_offset_text().set_fontsize(11)
    ax.grid(True, alpha=0.30)


def _save_figure(fig, stem: Path):
    stem.parent.mkdir(parents=True, exist_ok=True)
    png_file = stem.with_suffix(".png")
    save_figure(fig, png_file, dpi=300)
    return [str(png_file)]


def _write_per_sbox_exports(result, cache_dir: Path):
    sbox_type = result["sbox_type"]
    tag = _result_tag(result["n_traces_max"], result["snr_selection_mode"])
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
    tag = _result_tag(combined["n_traces_max"], combined["snr_selection_mode"])
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


_SUMMARY_SERIES_FIELDS = (
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
    "full_key_match",
)


def _refresh_result_series(result: dict) -> None:
    summaries = result.get("summaries", [])
    result["trace_counts"] = [int(summary["trace_count"]) for summary in summaries]
    for field in _SUMMARY_SERIES_FIELDS:
        result[field] = [summary.get(field) for summary in summaries]


def _filter_result_trace_counts(result: dict, drop_trace_counts: set[int]) -> None:
    if not drop_trace_counts:
        _refresh_result_series(result)
        return

    result["summaries"] = [
        summary
        for summary in result.get("summaries", [])
        if int(summary.get("trace_count", -1)) not in drop_trace_counts
    ]
    result["snr_runs"] = [
        item
        for item in result.get("snr_runs", [])
        if int(item.get("trace_count", -1)) not in drop_trace_counts
    ]
    result["target_log"] = [
        item
        for item in result.get("target_log", [])
        if int(item.get("trace_count", -1)) not in drop_trace_counts
    ]
    _refresh_result_series(result)


def _filter_combined_trace_counts(combined: dict, drop_trace_counts: set[int]) -> None:
    combined["trace_counts"] = [
        int(count)
        for count in combined.get("trace_counts", [])
        if int(count) not in drop_trace_counts
    ]
    for result in combined.get("results", {}).values():
        _filter_result_trace_counts(result, drop_trace_counts)


def _merge_result_by_trace_count(existing: dict, replacement: dict) -> None:
    existing_by_count = {
        int(summary["trace_count"]): summary
        for summary in existing.get("summaries", [])
    }
    for summary in replacement.get("summaries", []):
        existing_by_count[int(summary["trace_count"])] = summary
    existing["summaries"] = [
        existing_by_count[count]
        for count in sorted(existing_by_count)
    ]

    existing_snr_by_count = {
        int(item["trace_count"]): item
        for item in existing.get("snr_runs", [])
        if "trace_count" in item
    }
    for item in replacement.get("snr_runs", []):
        if "trace_count" in item:
            existing_snr_by_count[int(item["trace_count"])] = item
    existing["snr_runs"] = [
        existing_snr_by_count[count]
        for count in sorted(existing_snr_by_count)
    ]

    if replacement.get("target_log"):
        replacement_counts = {
            int(item["trace_count"])
            for item in replacement.get("target_log", [])
            if "trace_count" in item
        }
        existing["target_log"] = [
            item
            for item in existing.get("target_log", [])
            if int(item.get("trace_count", -1)) not in replacement_counts
        ] + replacement.get("target_log", [])

    _refresh_result_series(existing)


def _replacement_results_from_json(path: Path) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if "results" in data:
        return list(data.get("results", {}).values())
    return [data]


def _merge_replacement_results(combined: dict, replacement_jsons, base_cache_dir: Path) -> None:
    for replacement_json in replacement_jsons:
        path = _repo_relative_path(replacement_json, Path(replacement_json))
        if not path.exists():
            raise FileNotFoundError(f"--replace-result-json file not found: {path}")
        for replacement in _replacement_results_from_json(path):
            _refresh_result_series(replacement)
            sbox_type = replacement["sbox_type"]
            results = combined.setdefault("results", {})
            if sbox_type not in results:
                results[sbox_type] = replacement
                continue
            _merge_result_by_trace_count(results[sbox_type], replacement)

    combined["sboxes"] = list(combined.get("results", {}).keys())
    combined["trace_counts"] = sorted(
        {
            int(count)
            for result in combined.get("results", {}).values()
            for count in result.get("trace_counts", [])
        }
    )


def _per_sbox_cache_dir_from_result(result: dict, base_cache_dir: Path) -> Path:
    json_path = (
        result.get("exports", {})
        .get("values", {})
        .get("json")
    )
    if json_path:
        return Path(json_path).parent
    return base_cache_dir / result["sbox_type"]


def _write_per_sbox_result_files(result: dict, base_cache_dir: Path, plot_dir: Path, save_plots: bool, plot_x_scale: str) -> None:
    cache_dir = _per_sbox_cache_dir_from_result(result, base_cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    tag = _result_tag(result["n_traces_max"], result["snr_selection_mode"])
    json_file = cache_dir / f"ASCON_generic_key_recovery_progression_{result['sbox_type']}_{tag}.json"
    result["exports"] = {
        "values": {
            **_write_per_sbox_exports(result, cache_dir),
            "json": str(json_file),
        },
        "plots": _plot_per_sbox_result(result, plot_dir, save_plots, plot_x_scale),
    }
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)


def _run_plot_only(args, base_cache_dir: Path, output_dir: Path, plot_dir: Path) -> None:
    input_json = args.plot_input_json
    if input_json in (None, ""):
        tag = _result_tag(int(args.max_traces), args.snr_selection_mode.strip().lower())
        input_json = output_dir / f"ASCON_generic_key_recovery_progression_all_sboxes_{tag}.json"
    input_json = _repo_relative_path(input_json, Path(input_json))
    if not input_json.exists():
        raise FileNotFoundError(f"--plot-only input JSON not found: {input_json}")

    with open(input_json, "r", encoding="utf-8") as f:
        combined = json.load(f)

    drop_trace_counts = _parse_trace_count_set(args.drop_trace_counts)
    _filter_combined_trace_counts(combined, drop_trace_counts)
    replacement_jsons = _parse_path_list(args.replace_result_json)
    _merge_replacement_results(combined, replacement_jsons, base_cache_dir)

    save_plots = bool(args.save_plots)
    plot_x_scale = args.plot_x_scale.strip().lower()
    combined.setdefault("config", {})["plot_x_scale"] = plot_x_scale
    combined.setdefault("config", {})["plot_only_drop_trace_counts"] = sorted(drop_trace_counts)
    combined.setdefault("config", {})["plot_only_replacement_jsons"] = replacement_jsons
    for result in combined.get("results", {}).values():
        _write_per_sbox_result_files(
            result,
            base_cache_dir=base_cache_dir,
            plot_dir=plot_dir,
            save_plots=save_plots,
            plot_x_scale=plot_x_scale,
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    combined["exports"] = {
        "values": _write_combined_exports(combined, output_dir),
        "plots": _plot_combined_results(combined, plot_dir, save_plots, plot_x_scale),
    }
    combined_json = Path(combined["exports"]["values"]["json"])
    with open(combined_json, "w", encoding="utf-8") as f:
        json.dump(combined, f, indent=2)

    print("\n[INFO] Plot-only key-recovery progression export finished")
    print(f"[INFO] Input JSON    : {input_json}")
    if drop_trace_counts:
        print(f"[INFO] Dropped traces: {sorted(drop_trace_counts)}")
    if replacement_jsons:
        print("[INFO] Replacement JSONs:")
        for path in replacement_jsons:
            print(f"       {path}")
    print(f"[INFO] X-axis scale  : {plot_x_scale}")
    print(f"[INFO] Combined JSON : {combined_json}")
    print(f"[INFO] Combined CSV  : {combined['exports']['values']['csv']}")
    if save_plots:
        print(f"[INFO] Combined plots: {plot_dir}")


def _plot_per_sbox_result(result, plot_dir: Path, save_plots: bool, x_scale: str):
    if not save_plots:
        return {}

    plt, mticker = _import_matplotlib()
    if plt is None:
        return {}

    sbox_type = result["sbox_type"]
    tag = _result_tag(result["n_traces_max"], result["snr_selection_mode"])
    x_vals = np.asarray(result["trace_counts"], dtype=np.int64)
    plot_dir = plot_dir / sbox_type
    plot_paths = {}

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(
        x_vals,
        result["k0_correct_recovered_count"],
        marker="o",
        markersize=3,
        linewidth=1.8,
        color=KEY_COLORS["k0"],
        label="k0 correct",
    )
    ax.plot(
        x_vals,
        result["k1_correct_recovered_count"],
        marker="s",
        markersize=3,
        linewidth=1.8,
        color=KEY_COLORS["k1"],
        label="k1 correct",
    )
    ax.plot(
        x_vals,
        result["correct_key_bits_count"],
        marker="^",
        markersize=3,
        linewidth=2.2,
        color=KEY_COLORS["combined"],
        label="k0+k1 correct",
    )
    ax.set_xlabel("Number of prefix traces", fontsize=13)
    ax.set_ylabel("Correct recovered key bits", fontsize=13)
    ax.set_title(f"ASCON generic CPA key-recovery progression - {sbox_type}", fontsize=14)
    ax.set_ylim(0, 132)
    ax.set_yticks(range(0, 129, 16))
    _format_axes_for_traces(ax, mticker, x_scale)
    ax.legend(loc="best")
    plot_paths["correct_recovered_key_bits"] = _save_figure(
        fig,
        plot_dir / f"ASCON_generic_correct_recovered_key_bits_{sbox_type}_{tag}",
    )
    plt.close(fig)

    return plot_paths


def _plot_combined_results(combined, plot_dir: Path, save_plots: bool, x_scale: str):
    if not save_plots:
        return {}

    plt, mticker = _import_matplotlib()
    if plt is None:
        return {}

    tag = _result_tag(combined["n_traces_max"], combined["snr_selection_mode"])
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
            color=sbox_color(sbox_type),
            label=sbox_type,
        )
    ax.set_xlabel("Number of prefix traces", fontsize=13)
    ax.set_ylabel("Correct recovered key bits", fontsize=13)
    ax.set_title("ASCON generic CPA key-recovery progression - all S-boxes", fontsize=14)
    ax.set_ylim(0, 132)
    ax.set_yticks(range(0, 129, 16))
    _format_axes_for_traces(ax, mticker, x_scale)
    ax.legend(loc="best")
    plot_paths["correct_recovered_key_bits"] = _save_figure(
        fig,
        plot_dir / f"ASCON_generic_correct_recovered_key_bits_all_sboxes_{tag}",
    )
    plt.close(fig)

    # Paper layout uses the same shared style for the HW and SW entry points.
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.5), sharey=True)
    labels = {"hw": "Reference HW", "lut_ascon": "Ascon", "lut_bilgin": "Bilgin",
              "lut_allouzi": "Allouzi", **{f"lut_lu_{i}": f"Lu {i}" for i in range(4, 8)}}
    for sbox_type, result in combined["results"].items():
        for ax, field in zip(axes, ("correct_key_bits_count", "known_key_bits_count")):
            ax.plot(result["trace_counts"], result[field], "o-", markersize=3,
                    linewidth=1.8, color=sbox_color(sbox_type),
                    label=labels.get(sbox_type, sbox_type))
        exact = [r["trace_count"] for r in result["summaries"] if r["full_key_match"]]
        axes[0].scatter(exact, [128] * len(exact), marker="*", s=65,
                        color=sbox_color(sbox_type), edgecolors="white", linewidths=0.5, zorder=5)
    for ax in axes:
        ax.set(xlabel="Number of traces", ylim=(0, 132))
        _format_axes_for_traces(ax, mticker, x_scale)
    axes[0].set_ylabel("Correctly recovered bits (out of 128)")
    axes[1].set_ylabel("Committed bits, including errors")
    axes[1].legend(loc="lower right", ncol=2)
    implementation = combined.get("implementation", IMPLEMENTATION)
    fig.tight_layout()
    stem = plot_dir / f"ASCON_generic_key_recovery_side_by_side_{implementation}_{tag}"
    plot_paths["paper_side_by_side"] = []
    for extension in ("png", "pdf"):
        path = stem.with_suffix(f".{extension}")
        save_figure(fig, path, tight=False)
        plot_paths["paper_side_by_side"].append(str(path))
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(11.5, 6.8))
    all_values = []
    for sbox_type, result in combined["results"].items():
        trace_counts = result["trace_counts"]
        correct_counts = result["correct_key_bits_count"]
        known_counts = result["known_key_bits_count"]
        all_values.extend(correct_counts)
        all_values.extend(known_counts)
        color = sbox_color(sbox_type)
        ax.plot(
            trace_counts,
            correct_counts,
            marker="o",
            markersize=3,
            linewidth=1.9,
            color=color,
            label=sbox_type,
        )
        ax.plot(
            trace_counts,
            known_counts,
            marker="s",
            markersize=2.8,
            linewidth=1.5,
            linestyle="--",
            alpha=0.75,
            color=color,
        )

    y_min = 0
    if all_values:
        y_min = max(0, int(np.floor((min(all_values) - 8) / 8.0) * 8))
    ax.set_ylim(y_min, 132)
    ax.set_yticks(range(y_min, 129, 8))
    ax.set_xlabel("Number of prefix traces", fontsize=13)
    ax.set_ylabel("Recovered key bits", fontsize=13)
    ax.set_title(
        "ASCON generic CPA recovered vs correct recovered key bits - all S-boxes",
        fontsize=14,
    )
    _format_axes_for_traces(ax, mticker, x_scale)

    from matplotlib.lines import Line2D

    style_legend = [
        Line2D(
            [0],
            [0],
            color=KEY_COLORS["text"],
            linewidth=1.9,
            label="correct recovered bits",
        ),
        Line2D(
            [0],
            [0],
            color=KEY_COLORS["text"],
            linewidth=1.5,
            linestyle="--",
            label="recovered bits",
        ),
    ]
    sbox_legend = ax.legend(loc="lower right", ncol=2, title="S-box")
    ax.add_artist(sbox_legend)
    ax.legend(handles=style_legend, loc="lower left", title="Line meaning")
    plot_paths["correct_vs_recovered_key_bits"] = _save_figure(
        fig,
        plot_dir / f"ASCON_generic_correct_vs_recovered_key_bits_all_sboxes_{tag}",
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
            color=sbox_color(sbox_type),
            label=sbox_type,
        )
        axes[1].plot(
            result["trace_counts"],
            result["k1_correct_recovered_count"],
            marker="o",
            markersize=3,
            linewidth=1.6,
            color=sbox_color(sbox_type),
            label=sbox_type,
        )

    axes[0].set_ylabel("Correct k0 bits", fontsize=12)
    axes[1].set_ylabel("Correct k1 bits", fontsize=12)
    axes[1].set_xlabel("Number of prefix traces", fontsize=13)
    for ax in axes:
        ax.set_ylim(0, 67)
        ax.set_yticks(range(0, 65, 8))
        _format_axes_for_traces(ax, mticker, x_scale)
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
    strict_traceset_size: bool,
    snr_trace_count: int,
    snr_selection_mode: str,
    trace_counts_requested,
    chunk_size: int,
    sample_window: int,
    polarity: str,
    cpa_policy: str,
    mixed_top_groups: int,
    mixed_min_fact_support: int,
    cpa_backend: str,
    max_targets,
    base_cache_dir: Path,
    output_dir: Path,
    plot_dir: Path,
    save_plots: bool,
    save_target_log: bool,
    auto_snr: bool,
    snr_script: Path,
    snr_chunk_size: int,
    snr_device: str,
    analysis_max_time_us: float,
    plot_x_scale: str,
):
    trace_file = _find_trace_file(
        sbox_type,
        traceset_size_k,
        max_traces_requested,
        strict_traceset_size=strict_traceset_size,
    )
    cache_dir = base_cache_dir / sbox_type

    if not trace_file.exists():
        print(f"[WARN] Missing trace file for {sbox_type}: {trace_file}")
        return None

    with h5py.File(trace_file, "r") as f:
        if "traces" not in f or "nonces" not in f:
            raise KeyError(f"{trace_file} is missing 'traces' or 'nonces'")

        traces_ds = f["traces"]
        nonces_ds = f["nonces"]
        total_traces = int(traces_ds.shape[0])
        total_samples = int(traces_ds.shape[1])
        sampling_interval = f.attrs.get("sampling_interval", None)
        n_samples = int(
            compute_analysis_sample_stop(
                total_samples,
                sampling_interval,
                analysis_max_time_us,
            )
        )
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

    profiled_snr_info = None
    if snr_selection_mode == "profiled":
        profiled_snr_info = _load_snr_targets_for_mode(
            cache_dir=cache_dir,
            sbox_type=sbox_type,
            snr_selection_mode=snr_selection_mode,
            trace_count=n_used,
            profiled_snr_trace_count=snr_trace_count,
            sample_window=sample_window,
            max_targets=max_targets,
            traceset_size_k=traceset_size_k,
            base_cache_dir=base_cache_dir,
            auto_snr=auto_snr,
            snr_script=snr_script,
            snr_chunk_size=snr_chunk_size,
            snr_device=snr_device,
            analysis_sample_stop=n_samples,
            analysis_max_time_us=analysis_max_time_us,
        )

    print("\n================= SBOX KEY-RECOVERY PROGRESSION =================")
    print(f"S-box                  : {sbox_type}")
    print(f"Trace file             : {trace_file}")
    print(f"SNR selection mode     : {snr_selection_mode}")
    if snr_selection_mode == "profiled":
        print(f"SNR ranked file        : {profiled_snr_info['snr_file']}")
        print(f"SNR traces file        : {profiled_snr_info['snr_trace_file']}")
    else:
        print("SNR ranked file        : one file per trace-count prefix")
        print("SNR traces file        : one file per trace-count prefix")
    print(f"Available traces       : {total_traces:,}")
    print(f"Used max traces        : {n_used:,}")
    print(f"Trace counts           : {len(trace_counts)} steps, {trace_counts[0]:,}..{trace_counts[-1]:,}")
    print(f"Samples per trace      : {total_samples}")
    print(f"Samples analyzed       : {n_samples}")
    if float(analysis_max_time_us) > 0:
        print(f"Analysis time limit    : {analysis_max_time_us:g} us")
    if snr_selection_mode == "profiled":
        effective_sample_window = int(profiled_snr_info["effective_sample_window"])
        print(f"CPA sample window      : {effective_sample_window if effective_sample_window > 0 else 'full trace'}")
        print(f"Targets loaded         : {len(profiled_snr_info['targets'])}")
    else:
        print(f"CPA sample window      : {sample_window if sample_window > 0 else 'full trace'}")
        print("Targets loaded         : per trace-count prefix")
    print(f"Leakage polarity       : {polarity}")
    print(f"CPA policy             : {cpa_policy}")
    if cpa_policy == "dependency_aware":
        print(f"Mixed top groups       : {mixed_top_groups}")
        print(f"Mixed fact support     : {mixed_min_fact_support}")
    print(f"CPA backend            : {cpa_backend}")
    print("==================================================================\n")

    total_tic = time.perf_counter()
    if snr_selection_mode == "profiled":
        effective_sample_window = int(profiled_snr_info["effective_sample_window"])
        targets = profiled_snr_info["targets"]
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
            cpa_policy=cpa_policy,
            mixed_top_groups=mixed_top_groups,
            mixed_min_fact_support=mixed_min_fact_support,
            save_target_log=save_target_log,
        )
        snr_runs = [
            {
                "trace_count": int(c),
                "snr_file": str(profiled_snr_info["snr_file"]),
                "snr_trace_file": str(profiled_snr_info["snr_trace_file"]),
                "targets_loaded": int(len(targets)),
                "targets_processed": int(targets_processed),
                "cpa_sample_window_effective": int(effective_sample_window),
            }
            for c in trace_counts
        ]
    else:
        (
            summaries,
            target_log,
            targets_processed,
            runtime_minutes,
            snr_runs,
        ) = _run_trace_counts_with_prefix_snr(
            sbox_type=sbox_type,
            trace_file=trace_file,
            nonces=nonces,
            trace_counts=trace_counts,
            n_samples=n_samples,
            iv_int=iv_int,
            cache_dir=cache_dir,
            snr_trace_count=snr_trace_count,
            k0_bits_expected=k0_bits_expected,
            k1_bits_expected=k1_bits_expected,
            k0_int_expected=k0_int_expected,
            k1_int_expected=k1_int_expected,
            chunk_size=chunk_size,
            cpa_backend=cpa_backend,
            sample_window=sample_window,
            polarity=polarity,
            cpa_policy=cpa_policy,
            mixed_top_groups=mixed_top_groups,
            mixed_min_fact_support=mixed_min_fact_support,
            max_targets=max_targets,
            traceset_size_k=traceset_size_k,
            base_cache_dir=base_cache_dir,
            auto_snr=auto_snr,
            snr_script=snr_script,
            snr_chunk_size=snr_chunk_size,
            snr_device=snr_device,
            save_target_log=save_target_log,
            analysis_sample_stop=n_samples,
            analysis_max_time_us=analysis_max_time_us,
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

    if snr_selection_mode == "profiled":
        result_snr_file = str(profiled_snr_info["snr_file"])
        result_snr_trace_file = str(profiled_snr_info["snr_trace_file"])
        targets_loaded = int(len(profiled_snr_info["targets"]))
        effective_window_summary = int(profiled_snr_info["effective_sample_window"])
    else:
        result_snr_file = "per-prefix"
        result_snr_trace_file = "per-prefix"
        targets_loaded = int(sum(item["targets_loaded"] for item in snr_runs))
        effective_window_summary = int(
            max((item["cpa_sample_window_effective"] for item in snr_runs), default=0)
        )

    result = {
        "sbox_type": sbox_type,
        "trace_file": str(trace_file),
        "snr_selection_mode": snr_selection_mode,
        "snr_file": result_snr_file,
        "snr_trace_file": result_snr_trace_file,
        "snr_runs": snr_runs,
        "n_traces_max": int(n_used),
        "snr_trace_count": int(snr_trace_count),
        "trace_counts": [int(c) for c in trace_counts],
        "n_samples_total": int(total_samples),
        "n_samples": int(n_samples),
        "analysis_max_time_us": float(analysis_max_time_us),
        "chunk_size": int(chunk_size),
        "cpa_sample_window_requested": int(sample_window),
        "cpa_sample_window_effective": int(effective_window_summary),
        "leakage_polarity": polarity,
        "cpa_policy": cpa_policy,
        "mixed_top_groups": int(mixed_top_groups),
        "mixed_min_fact_support": int(mixed_min_fact_support),
        "cpa_backend": cpa_backend,
        "cpu_threads": int(max_cpu_workers),
        "targets_loaded": int(targets_loaded),
        "targets_processed": int(targets_processed),
        "runtime_minutes": float((total_toc - total_tic) / 60.0),
        "target_loop_runtime_minutes": float(runtime_minutes),
        "prefix_traces": True,
        "random_subsets": False,
        "auto_snr": bool(auto_snr),
        "snr_script": str(snr_script),
        "snr_chunk_size": int(snr_chunk_size),
        "snr_device": str(snr_device),
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

    tag = _result_tag(n_used, snr_selection_mode)
    json_file = cache_dir / f"ASCON_generic_key_recovery_progression_{sbox_type}_{tag}.json"
    result["exports"] = {
        "values": {
            **_write_per_sbox_exports(result, cache_dir),
            "json": str(json_file),
        },
        "plots": _plot_per_sbox_result(result, plot_dir, save_plots, plot_x_scale),
    }

    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    print(
        f"[INFO] {sbox_type}: wrote {json_file} "
        f"in {result['runtime_minutes']:.2f} minutes"
    )
    return result


def main():
    args = _build_arg_parser().parse_args()

    sboxes = _parse_sboxes(args.sboxes)
    max_traces = int(args.max_traces)
    strict_traceset_size = args.traceset_size_k is not None
    traceset_size_k = int(args.traceset_size_k or (max_traces // 1000))
    snr_trace_count = int(args.snr_traces or max_traces)
    snr_selection_mode = args.snr_selection_mode.strip().lower()
    resolution = int(args.resolution)
    trace_counts = _build_trace_counts(
        max_traces,
        resolution,
        explicit=args.trace_counts,
        append_max=bool(args.append_max),
    )
    chunk_size = int(args.chunk_size)
    sample_window = int(args.sample_window)
    polarity = args.polarity.strip().lower()
    cpa_policy = _normalize_cpa_policy(args.cpa_policy)
    mixed_top_groups = int(args.mixed_top_groups)
    mixed_min_fact_support = int(args.mixed_min_fact_support)
    cpa_backend = get_cpa_backend_name(args.cpa_device)
    max_targets = args.max_targets
    output_dir_env = args.output_dir
    plot_dir_env = args.plot_dir
    cache_dir_env = args.cache_dir
    base_cache_dir = _repo_relative_path(cache_dir_env, BASE_CACHE_DIR)
    output_dir = (
        Path(output_dir_env)
        if output_dir_env not in (None, "")
        else base_cache_dir / "key_recovery_progression_all_sboxes" / snr_selection_mode
    )
    plot_dir = (
        Path(plot_dir_env)
        if plot_dir_env not in (None, "")
        else DEFAULT_PLOT_DIR / snr_selection_mode
    )
    save_plots = bool(args.save_plots)
    save_target_log = bool(args.save_target_log)
    auto_snr = bool(args.auto_snr)
    snr_script = Path(args.snr_script)
    snr_chunk_size = int(args.snr_chunk_size)
    snr_device = args.snr_device
    analysis_max_time_us = float(args.analysis_max_time_us)
    plot_x_scale = args.plot_x_scale.strip().lower()

    if plot_x_scale not in {"linear", "log"}:
        raise ValueError("--plot-x-scale must be one of: linear, log")

    if args.plot_only:
        _run_plot_only(
            args,
            base_cache_dir=base_cache_dir,
            output_dir=output_dir,
            plot_dir=plot_dir,
        )
        return

    if max_traces <= 1:
        raise ValueError("ASCON_PROGRESS_N must be greater than 1")
    if chunk_size <= 0:
        raise ValueError("ASCON_CHUNK_SIZE must be positive")
    if sample_window < 0:
        raise ValueError("ASCON_CPA_SAMPLE_WINDOW must be >= 0")
    if polarity not in {"negative", "positive", "both"}:
        raise ValueError("ASCON_LEAKAGE_POLARITY must be one of: negative, positive, both")
    if mixed_top_groups < 1:
        raise ValueError("--mixed-top-groups must be positive")
    if mixed_min_fact_support < 1:
        raise ValueError("--mixed-min-fact-support must be positive")
    if snr_selection_mode not in {"profiled", "prefix"}:
        raise ValueError("ASCON_SNR_SELECTION_MODE must be one of: profiled, prefix")
    if snr_chunk_size <= 0:
        raise ValueError("--snr-chunk-size must be positive")
    if analysis_max_time_us < 0:
        raise ValueError("--analysis-max-time-us must be >= 0")

    print("\n================= GENERIC KEY-RECOVERY PROGRESSION BATCH =================")
    print(f"Implementation         : {IMPLEMENTATION}")
    print(f"S-boxes                : {sboxes}")
    print(f"Max prefix traces      : {max_traces:,}")
    print(f"Traceset size tag      : {traceset_size_k}k")
    print(f"SNR selection mode     : {snr_selection_mode}")
    print(f"SNR cache trace count  : {snr_trace_count:,}")
    print(f"Trace count steps      : {len(trace_counts)}")
    print(f"First/last count       : {trace_counts[0]:,} / {trace_counts[-1]:,}")
    print(f"Chunk size             : {chunk_size}")
    print(f"CPA sample window      : {sample_window if sample_window > 0 else 'full trace'}")
    print(f"Analysis time limit    : {analysis_max_time_us:g} us" if analysis_max_time_us > 0 else "Analysis time limit    : full trace")
    print(f"Leakage polarity       : {polarity}")
    print(f"CPA policy             : {cpa_policy}")
    if cpa_policy == "dependency_aware":
        print(f"Mixed top groups       : {mixed_top_groups}")
        print(f"Mixed fact support     : {mixed_min_fact_support}")
    print(f"CPA backend            : {cpa_backend}")
    print(f"CPU threads            : {max_cpu_workers}")
    print(f"Max targets            : {max_targets if max_targets is not None else 'all'}")
    print(f"Auto-generate SNR      : {'yes' if auto_snr else 'no'}")
    print(f"SNR generator chunk    : {snr_chunk_size}")
    print(f"SNR generator device   : {snr_device}")
    print(f"Base cache dir         : {base_cache_dir}")
    print(f"Output dir             : {output_dir}")
    print(f"Plot dir               : {plot_dir}")
    print(f"Plot x-axis scale      : {plot_x_scale}")
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
            strict_traceset_size=strict_traceset_size,
            snr_trace_count=snr_trace_count,
            snr_selection_mode=snr_selection_mode,
            trace_counts_requested=trace_counts,
            chunk_size=chunk_size,
            sample_window=sample_window,
            polarity=polarity,
            cpa_policy=cpa_policy,
            mixed_top_groups=mixed_top_groups,
            mixed_min_fact_support=mixed_min_fact_support,
            cpa_backend=cpa_backend,
            max_targets=max_targets,
            base_cache_dir=base_cache_dir,
            output_dir=output_dir,
            plot_dir=plot_dir,
            save_plots=save_plots,
            save_target_log=save_target_log,
            auto_snr=auto_snr,
            snr_script=snr_script,
            snr_chunk_size=snr_chunk_size,
            snr_device=snr_device,
            analysis_max_time_us=analysis_max_time_us,
            plot_x_scale=plot_x_scale,
        )
        if result is not None:
            results[sbox_type] = result

    batch_toc = time.perf_counter()
    output_dir.mkdir(parents=True, exist_ok=True)

    combined = {
        "sboxes": list(results.keys()),
        "implementation": IMPLEMENTATION,
        "n_traces_max": int(max_traces),
        "snr_selection_mode": snr_selection_mode,
        "trace_counts": [int(c) for c in trace_counts],
        "runtime_minutes": float((batch_toc - batch_tic) / 60.0),
        "config": {
            "chunk_size": int(chunk_size),
            "sample_window": int(sample_window),
            "analysis_max_time_us": float(analysis_max_time_us),
            "snr_selection_mode": snr_selection_mode,
            "snr_trace_count": int(snr_trace_count),
            "polarity": polarity,
            "cpa_backend": cpa_backend,
            "cpu_threads": int(max_cpu_workers),
            "max_targets": max_targets,
            "prefix_traces": True,
            "random_subsets": False,
            "save_target_log": bool(save_target_log),
            "auto_snr": bool(auto_snr),
            "snr_script": str(snr_script),
            "snr_chunk_size": int(snr_chunk_size),
            "snr_device": str(snr_device),
            "plot_x_scale": plot_x_scale,
        },
        "results": results,
    }

    combined["exports"] = {
        "values": _write_combined_exports(combined, output_dir),
        "plots": _plot_combined_results(combined, plot_dir, save_plots, plot_x_scale),
    }

    tag = _result_tag(max_traces, snr_selection_mode)
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
