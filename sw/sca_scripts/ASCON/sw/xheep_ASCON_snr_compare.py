#!/usr/bin/env python3
# =====================================================================
# Compare full ASCON SNR traces across different S-box implementations
#
# Expected input HDF5 structure:
#   /snr_traces/value          shape = (5, 64, n_samples)
#   /snr_traces/register_names
#   /snr_traces/bits
#   /snr_traces/sample_index
#
# This script compares multiple SNR files using:
#   - peak SNR distribution
#   - mean peak SNR
#   - max peak SNR
#   - integrated SNR
#   - leakage sample count above thresholds
#   - per-register leakage statistics
#   - mean SNR trace over time
#   - maximum-over-target SNR trace over time
# =====================================================================

import os
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap


# ---------------------------------------------------------------------------
# Configuration
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
BASE_CACHE_DIR = DOJO_ROOT / "sw" / "sca_scripts" / "ASCON" / "sw" / "cache"
DEFAULT_OUT_DIR = DOJO_ROOT / "sw" / "sca_scripts" / "ASCON" / "sw" / "plot" / "snr_comparison_plots"

ALL_SBOXES = [
    "lut_ascon",
    "lut_bilgin",
    "lut_allouzi",
    "lut_lu_4",
    "lut_lu_5",
    "lut_lu_6",
    "lut_lu_7",
]


def parse_sboxes(value: str):
    value = str(value).strip()
    if not value or value.lower() == "all":
        return list(ALL_SBOXES)

    sboxes = [item.strip() for item in value.split(",") if item.strip()]
    unknown = sorted(set(sboxes) - set(ALL_SBOXES))
    if unknown:
        raise ValueError(f"Unknown S-box names: {unknown}")
    return sboxes


SBOXES_TO_COMPARE = parse_sboxes(os.environ.get("SNR_COMPARE_SBOXES", "all"))
SNR_TRACE_COUNT = int(os.environ.get("SNR_COMPARE_N", "1000000"))
SNR_TRACE_TAG = os.environ.get("SNR_COMPARE_TAG", f"{SNR_TRACE_COUNT // 1000}k")

SNR_FILES = {
    sbox: BASE_CACHE_DIR / sbox / f"snr_traces_{sbox}_{SNR_TRACE_TAG}.h5"
    for sbox in SBOXES_TO_COMPARE
}

OUT_DIR = Path(os.environ.get("SNR_COMPARE_OUT_DIR", str(DEFAULT_OUT_DIR)))
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Thresholds used to count leaking samples.
# You may tune these after inspecting your SNR scale.
SNR_THRESHOLDS = [0.001, 0.005, 0.01, 0.02, 0.05]

# Histogram/PDF settings.
HIST_BINS = 80
SHOW_LOG_DISTRIBUTION_HISTOGRAM = False

# Skew-aware plot settings.
# SNR distributions are often concentrated near zero with a few large tail
# values. Log distributions expose multiplicative differences, zoomed plots
# show the dense near-zero region, and CCDFs make tail behavior visible.
EPS = 1e-12
TOP_K = 20
PEAK_SNR_ZOOM_MAX = 0.25
HEATMAP_CLIP_PERCENTILE = 99.0
MAX_VALUES_PER_SBOX = 2_000_000
SKIP_MISSING_FILES = True

# If there are too many samples, plot every Nth sample for time-domain curves.
# Use 1 to plot all samples.
TIME_PLOT_DOWNSAMPLE = 1

# Save figures with this DPI.
FIG_DPI = 300

SBOX_COLORS = {
    "lut_ascon": "#1f77b4",
    "lut_allouzi": "#ff7f0e",
    "lut_bilgin": "#2ca02c",
    "lut_lu_4": "#d62728",
    "lut_lu_5": "#9467bd",
    "lut_lu_6": "#8c564b",
    "lut_lu_7": "#e377c2",
}

NAVY_CMAP = LinearSegmentedColormap.from_list(
    "snr_navy",
    ["#f7fbff", "#deebf7", "#9ecae1", "#3182bd", "#08306b", "#001f4d"],
)

plt.rcParams.update({
    "font.family": "serif",
    "font.serif": ["Times New Roman", "Times", "DejaVu Serif"],
    "axes.labelsize": 14,
    "axes.titlesize": 16,
    "xtick.labelsize": 16,
    "ytick.labelsize": 16,
    "figure.titlesize": 16,
    "legend.fontsize": 12,
})


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def decode_h5_strings(arr):
    out = []
    for x in arr:
        if isinstance(x, bytes):
            out.append(x.decode("utf-8"))
        else:
            out.append(str(x))
    return out


def load_snr_file(path):
    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"SNR file not found: {path}")

    with h5py.File(path, "r") as f:
        snr = f["snr_traces/value"][:].astype(np.float64)

        if "snr_traces/register_names" in f:
            reg_names = decode_h5_strings(f["snr_traces/register_names"][:])
        else:
            reg_names = [f"x{i}" for i in range(snr.shape[0])]

        if "snr_traces/bits" in f:
            bits = f["snr_traces/bits"][:]
        else:
            bits = np.arange(snr.shape[1], dtype=np.uint16)

        if "snr_traces/sample_index" in f:
            sample_index = f["snr_traces/sample_index"][:]
        else:
            sample_index = np.arange(snr.shape[2], dtype=np.uint32)

        attrs = dict(f.attrs)

    return {
        "path": str(path),
        "snr": snr,
        "reg_names": reg_names,
        "bits": bits,
        "sample_index": sample_index,
        "attrs": attrs,
    }


def validate_datasets(data):
    shapes = {name: d["snr"].shape for name, d in data.items()}
    first_shape = next(iter(shapes.values()))

    for name, shape in shapes.items():
        if shape != first_shape:
            raise ValueError(
                f"Shape mismatch. First shape is {first_shape}, "
                f"but {name} has shape {shape}."
            )

    sample_indices = {name: tuple(d["sample_index"]) for name, d in data.items()}
    first_idx = next(iter(sample_indices.values()))

    for name, idx in sample_indices.items():
        if idx != first_idx:
            print(
                f"[WARN] sample_index differs for {name}. "
                "Time-domain plots may not be directly aligned."
            )


# ---------------------------------------------------------------------------
# Metric computation
# ---------------------------------------------------------------------------

def compute_metrics(name, d, thresholds):
    snr = d["snr"]
    reg_names = d["reg_names"]

    # Shape: (5, 64, n_samples)
    peak_per_target = np.max(snr, axis=2)          # (5, 64)
    peak_sample_idx = np.argmax(snr, axis=2)        # (5, 64), index into sample_index
    mean_trace = np.mean(snr, axis=(0, 1))         # (n_samples,)
    mean_trace_per_register = np.mean(snr, axis=1) # (5, n_samples)
    max_trace = np.max(snr, axis=(0, 1))           # (n_samples,)

    integrated_per_target = np.sum(snr, axis=2)    # (5, 64)

    rows = []

    global_row = {
        "sbox": name,
        "scope": "global",
        "register": "all",
        "mean_peak_snr": float(np.mean(peak_per_target)),
        "median_peak_snr": float(np.median(peak_per_target)),
        "max_peak_snr": float(np.max(peak_per_target)),
        "std_peak_snr": float(np.std(peak_per_target)),
        "mean_integrated_snr": float(np.mean(integrated_per_target)),
        "sum_integrated_snr": float(np.sum(snr)),
        "mean_snr_all_values": float(np.mean(snr)),
        "max_snr_all_values": float(np.max(snr)),
    }

    for th in thresholds:
        global_row[f"count_snr_gt_{th}"] = int(np.sum(snr > th))
        global_row[f"fraction_snr_gt_{th}"] = float(np.mean(snr > th))

    rows.append(global_row)

    for reg_i, reg_name in enumerate(reg_names):
        snr_reg = snr[reg_i]
        peak_reg = peak_per_target[reg_i]
        integrated_reg = integrated_per_target[reg_i]

        row = {
            "sbox": name,
            "scope": "register",
            "register": reg_name,
            "mean_peak_snr": float(np.mean(peak_reg)),
            "median_peak_snr": float(np.median(peak_reg)),
            "max_peak_snr": float(np.max(peak_reg)),
            "std_peak_snr": float(np.std(peak_reg)),
            "mean_integrated_snr": float(np.mean(integrated_reg)),
            "sum_integrated_snr": float(np.sum(snr_reg)),
            "mean_snr_all_values": float(np.mean(snr_reg)),
            "max_snr_all_values": float(np.max(snr_reg)),
        }

        for th in thresholds:
            row[f"count_snr_gt_{th}"] = int(np.sum(snr_reg > th))
            row[f"fraction_snr_gt_{th}"] = float(np.mean(snr_reg > th))

        rows.append(row)

    return {
        "peak_per_target": peak_per_target,
        "peak_flat": peak_per_target.reshape(-1),
        "peak_sample_idx": peak_sample_idx,
        "integrated_per_target": integrated_per_target,
        "integrated_flat": integrated_per_target.reshape(-1),
        "mean_trace": mean_trace,
        "mean_trace_per_register": mean_trace_per_register,
        "max_trace": max_trace,
        "rows": rows,
    }


# ---------------------------------------------------------------------------
# Plot helpers
# ---------------------------------------------------------------------------

def savefig(name):
    path = OUT_DIR / name
    plt.tight_layout()
    plt.savefig(path, dpi=FIG_DPI)
    plt.close()
    print(f"[INFO] Saved plot: {path}")


def sbox_color(name):
    return SBOX_COLORS.get(name, "#4c566a")


def finite_values(values):
    values = np.asarray(values, dtype=np.float64).reshape(-1)
    return values[np.isfinite(values)]


def get_kde():
    try:
        from scipy.stats import gaussian_kde
        return gaussian_kde
    except Exception:
        return None


def subsample_values(values, max_values, seed=12345):
    values = finite_values(values)
    if values.size <= max_values:
        return values

    rng = np.random.default_rng(seed)
    idx = rng.choice(values.size, size=max_values, replace=False)
    return values[idx]


def plot_log_distribution(values_by_name, xlabel, title, filename):
    gaussian_kde = get_kde()
    plt.figure(figsize=(9, 5))

    log_values_by_name = {}
    all_log_values = []

    for name, values in values_by_name.items():
        log_values = np.log10(np.maximum(finite_values(values), 0.0) + EPS)
        if log_values.size == 0:
            continue
        log_values_by_name[name] = log_values
        all_log_values.append(log_values)

    if not all_log_values:
        print(f"[WARN] No finite values for {filename}")
        return

    all_log_values = np.concatenate(all_log_values)
    xmin = float(np.min(all_log_values))
    xmax = float(np.max(all_log_values))

    if xmax <= xmin:
        print(f"[WARN] Cannot plot {filename}: all values are identical.")
        return

    x_grid = np.linspace(xmin, xmax, 1000)

    for name, log_values in log_values_by_name.items():
        color = sbox_color(name)
        if SHOW_LOG_DISTRIBUTION_HISTOGRAM:
            plt.hist(
                log_values,
                bins=HIST_BINS,
                density=True,
                histtype="step",
                linewidth=1.6,
                color=color,
                label=f"{name} histogram",
            )

        if gaussian_kde is not None and log_values.size > 1:
            kde = gaussian_kde(log_values)
            plt.plot(x_grid, kde(x_grid), linewidth=1.8, color=color, label=f"{name} KDE")

    plt.xlabel(xlabel)
    plt.ylabel("Density")
    plt.title(title)
    plt.legend()
    plt.grid(True, alpha=0.3)
    savefig(filename)


def plot_ccdf(values_by_name, xlabel, title, filename):
    plt.figure(figsize=(8, 5))

    for name, values in values_by_name.items():
        x = np.sort(finite_values(values))
        if x.size == 0:
            continue
        y = (x.size - np.arange(x.size)) / x.size
        plt.step(x, y, where="post", linewidth=1.8, color=sbox_color(name), label=name)

    plt.xlabel(xlabel)
    plt.ylabel("P(SNR > x)")
    plt.yscale("log")
    plt.title(title)
    plt.legend()
    plt.grid(True, which="both", alpha=0.3)
    savefig(filename)


def plot_peak_histograms(metrics):
    plt.figure(figsize=(8, 5))

    for name, m in metrics.items():
        plt.hist(
            m["peak_flat"],
            bins=HIST_BINS,
            density=True,
            histtype="step",
            linewidth=1.8,
            color=sbox_color(name),
            label=name,
        )

    plt.xlabel("Peak SNR per target bit")
    plt.ylabel("Density")
    plt.title("Distribution of Peak SNR Across All Register Bits")
    plt.legend()
    plt.grid(True, alpha=0.3)
    savefig("peak_snr_distribution.png")


def plot_peak_cdf(metrics):
    plt.figure(figsize=(8, 5))

    for name, m in metrics.items():
        x = np.sort(m["peak_flat"])
        y = np.arange(1, len(x) + 1) / len(x)
        plt.plot(x, y, linewidth=1.8, color=sbox_color(name), label=name)

    plt.xlabel("Peak SNR per target bit")
    plt.ylabel("CDF")
    plt.title("CDF of Peak SNR Across All Register Bits")
    plt.legend()
    plt.grid(True, alpha=0.3)
    savefig("peak_snr_cdf.png")


def plot_mean_snr_trace(data, metrics):
    plt.figure(figsize=(10, 5))

    for name, m in metrics.items():
        sample_index = data[name]["sample_index"]
        x = sample_index[::TIME_PLOT_DOWNSAMPLE]
        y = m["mean_trace"][::TIME_PLOT_DOWNSAMPLE]
        plt.plot(x, y, linewidth=1.5, color=sbox_color(name), label=name)

    plt.xlabel("Sample index")
    plt.ylabel("Mean SNR over all 5×64 targets")
    plt.title("Mean SNR Trace Over Time")
    plt.legend()
    plt.grid(True, alpha=0.3)
    savefig("mean_snr_trace.png")


def plot_max_snr_trace(data, metrics):
    plt.figure(figsize=(10, 5))

    for name, m in metrics.items():
        sample_index = data[name]["sample_index"]
        x = sample_index[::TIME_PLOT_DOWNSAMPLE]
        y = m["max_trace"][::TIME_PLOT_DOWNSAMPLE]
        plt.plot(x, y, linewidth=1.5, color=sbox_color(name), label=name)

    plt.xlabel("Sample index")
    plt.ylabel("Max SNR over all 5×64 targets")
    plt.title("Maximum Target SNR Trace Over Time")
    plt.legend()
    plt.grid(True, alpha=0.3)
    savefig("max_snr_trace.png")


def plot_per_register_mean_peak(data, metrics):
    names = list(metrics.keys())
    reg_names = data[names[0]]["reg_names"]

    x = np.arange(len(reg_names))
    width = 0.8 / len(names)

    plt.figure(figsize=(9, 5))

    for i, name in enumerate(names):
        peak_per_target = metrics[name]["peak_per_target"]
        y = np.mean(peak_per_target, axis=1)

        offset = (i - (len(names) - 1) / 2) * width
        plt.bar(x + offset, y, width=width, color=sbox_color(name), label=name)

    plt.xticks(x, reg_names)
    plt.xlabel("ASCON state register")
    plt.ylabel("Mean peak SNR")
    plt.title("Mean Peak SNR Per Register")
    plt.legend()
    plt.grid(True, axis="y", alpha=0.3)
    savefig("per_register_mean_peak_snr.png")


def plot_per_register_max_peak(data, metrics):
    names = list(metrics.keys())
    reg_names = data[names[0]]["reg_names"]

    x = np.arange(len(reg_names))
    width = 0.8 / len(names)

    plt.figure(figsize=(9, 5))

    for i, name in enumerate(names):
        peak_per_target = metrics[name]["peak_per_target"]
        y = np.max(peak_per_target, axis=1)

        offset = (i - (len(names) - 1) / 2) * width
        plt.bar(x + offset, y, width=width, color=sbox_color(name), label=name)

    plt.xticks(x, reg_names)
    plt.xlabel("ASCON state register")
    plt.ylabel("Max peak SNR")
    plt.title("Maximum Peak SNR Per Register")
    plt.legend()
    plt.grid(True, axis="y", alpha=0.3)
    savefig("per_register_max_peak_snr.png")


def plot_integrated_snr_distribution(metrics):
    plt.figure(figsize=(8, 5))

    for name, m in metrics.items():
        plt.hist(
            m["integrated_flat"],
            bins=HIST_BINS,
            density=True,
            histtype="step",
            linewidth=1.8,
            color=sbox_color(name),
            label=name,
        )

    plt.xlabel("Integrated SNR per target bit")
    plt.ylabel("Density")
    plt.title("Distribution of Integrated SNR Across Target Bits")
    plt.legend()
    plt.grid(True, alpha=0.3)
    savefig("integrated_snr_distribution.png")


def plot_skew_aware_distributions(data, metrics):
    plot_log_distribution(
        {name: m["peak_flat"] for name, m in metrics.items()},
        f"log10(peak SNR + {EPS:g})",
        "Log Distribution of Peak SNR Across Target Bits",
        "peak_snr_log_distribution.png",
    )
    plot_log_distribution(
        {name: m["integrated_flat"] for name, m in metrics.items()},
        f"log10(integrated SNR + {EPS:g})",
        "Log Distribution of Integrated SNR Across Target Bits",
        "integrated_snr_log_distribution.png",
    )
    plot_log_distribution(
        {
            name: subsample_values(d["snr"], MAX_VALUES_PER_SBOX)
            for name, d in data.items()
        },
        f"log10(SNR value + {EPS:g})",
        "Log Distribution of All SNR Values",
        "all_snr_log_distribution.png",
    )

    plt.figure(figsize=(8, 5))
    for name, m in metrics.items():
        plt.hist(
            m["peak_flat"],
            bins=HIST_BINS,
            range=(0.0, PEAK_SNR_ZOOM_MAX),
            density=True,
            histtype="step",
            linewidth=1.8,
            color=sbox_color(name),
            label=name,
        )
    plt.xlim(0.0, PEAK_SNR_ZOOM_MAX)
    plt.xlabel("Peak SNR per target bit")
    plt.ylabel("Density")
    plt.title(f"Zoomed Peak SNR Distribution (0 to {PEAK_SNR_ZOOM_MAX:g})")
    plt.legend()
    plt.grid(True, alpha=0.3)
    savefig("peak_snr_zoomed_distribution.png")

    plt.figure(figsize=(8, 5))
    for name, m in metrics.items():
        x = np.sort(m["peak_flat"])
        y = np.arange(1, len(x) + 1) / len(x)
        plt.plot(x, y, linewidth=1.8, color=sbox_color(name), label=name)
    plt.xlim(0.0, PEAK_SNR_ZOOM_MAX)
    plt.xlabel("Peak SNR per target bit")
    plt.ylabel("CDF")
    plt.title(f"Zoomed CDF of Peak SNR (0 to {PEAK_SNR_ZOOM_MAX:g})")
    plt.legend()
    plt.grid(True, alpha=0.3)
    savefig("peak_snr_zoomed_cdf.png")

    all_integrated = np.concatenate([m["integrated_flat"] for m in metrics.values()])
    xmax = float(np.percentile(all_integrated, HEATMAP_CLIP_PERCENTILE))
    plt.figure(figsize=(8, 5))
    for name, m in metrics.items():
        plt.hist(
            m["integrated_flat"],
            bins=HIST_BINS,
            range=(0.0, xmax),
            density=True,
            histtype="step",
            linewidth=1.8,
            color=sbox_color(name),
            label=name,
        )
    plt.xlim(0.0, xmax)
    plt.xlabel("Integrated SNR per target bit")
    plt.ylabel("Density")
    plt.title(f"Integrated SNR Distribution Clipped at P{HEATMAP_CLIP_PERCENTILE:g}")
    plt.legend()
    plt.grid(True, alpha=0.3)
    savefig("integrated_snr_zoomed_distribution.png")

    plot_ccdf(
        {name: m["peak_flat"] for name, m in metrics.items()},
        "Peak SNR per target bit",
        "CCDF of Peak SNR Across Target Bits",
        "peak_snr_ccdf.png",
    )
    plot_ccdf(
        {name: m["integrated_flat"] for name, m in metrics.items()},
        "Integrated SNR per target bit",
        "CCDF of Integrated SNR Across Target Bits",
        "integrated_snr_ccdf.png",
    )


def plot_log_boxplots(metrics):
    names = list(metrics.keys())

    for key, ylabel, title, filename in [
        ("peak_flat", "Peak SNR per target bit", "Peak SNR Per S-box", "peak_snr_boxplot_log.png"),
        (
            "integrated_flat",
            "Integrated SNR per target bit",
            "Integrated SNR Per S-box",
            "integrated_snr_boxplot_log.png",
        ),
    ]:
        values = [np.maximum(finite_values(metrics[name][key]), 0.0) + EPS for name in names]
        plt.figure(figsize=(9, 5))
        box = plt.boxplot(values, labels=names, showfliers=True, patch_artist=True)
        for patch, name in zip(box["boxes"], names):
            patch.set_facecolor(sbox_color(name))
            patch.set_alpha(0.35)
            patch.set_edgecolor(sbox_color(name))
        plt.yscale("log")
        plt.xticks(rotation=30, ha="right")
        plt.ylabel(ylabel)
        plt.title(f"{title} (log y-axis)")
        plt.grid(True, axis="y", which="both", alpha=0.3)
        savefig(filename)


def plot_threshold_counts(summary_df):
    global_df = summary_df[summary_df["scope"] == "global"].copy()

    count_cols = [c for c in global_df.columns if c.startswith("count_snr_gt_")]
    thresholds = [float(c.replace("count_snr_gt_", "")) for c in count_cols]

    plt.figure(figsize=(8, 5))

    for _, row in global_df.iterrows():
        y = [row[c] for c in count_cols]
        plt.plot(
            thresholds,
            y,
            marker="o",
            linewidth=1.8,
            color=sbox_color(row["sbox"]),
            label=row["sbox"],
        )

    plt.xlabel("SNR threshold")
    plt.ylabel("Number of samples above threshold")
    plt.title("Leakage Sample Count Above SNR Thresholds")
    plt.legend()
    plt.grid(True, alpha=0.3)
    savefig("threshold_leakage_counts.png")


def plot_top_bits(metrics, top_k=20):
    names = list(metrics.keys())

    for name in names:
        peak = metrics[name]["peak_per_target"]  # (5,64)
        flat = peak.reshape(-1)

        order = np.argsort(flat)[::-1][:top_k]

        labels = []
        values = []

        for target in order:
            reg_i = target // 64
            bit_i = target % 64
            labels.append(f"x{reg_i}[{bit_i}]")
            values.append(flat[target])

        plt.figure(figsize=(10, 5))
        plt.bar(np.arange(top_k), values, color=sbox_color(name))
        plt.xticks(np.arange(top_k), labels, rotation=60, ha="right")
        plt.xlabel("Target bit")
        plt.ylabel("Peak SNR")
        plt.title(f"Top {top_k} Leaking Bits - {name}")
        plt.grid(True, axis="y", alpha=0.3)
        savefig(f"top_{top_k}_bits_{name}.png")


def plot_heatmaps(data, metrics):
    names = list(metrics.keys())
    all_peak = np.concatenate([m["peak_flat"] for m in metrics.values()])
    peak_vmax = float(np.max(all_peak))
    clipped_vmax = float(np.percentile(all_peak, HEATMAP_CLIP_PERCENTILE))

    all_log_peak = np.log10(np.maximum(all_peak, 0.0) + EPS)
    log_vmin = float(np.min(all_log_peak))
    log_vmax = float(np.max(all_log_peak))

    def save_combined_heatmap(value_fn, filename, title, colorbar_label, vmin, vmax):
        fig, axes = plt.subplots(
            len(names),
            1,
            figsize=(13, max(3.0 * len(names), 5.0)),
            sharex=True,
            squeeze=False,
        )
        axes = axes[:, 0]
        im = None

        for ax, name in zip(axes, names):
            reg_names = data[name]["reg_names"]
            bits = data[name]["bits"]
            values = value_fn(name)
            im = ax.imshow(
                values,
                aspect="auto",
                interpolation="nearest",
                vmin=vmin,
                vmax=vmax,
                cmap=NAVY_CMAP,
            )
            ax.set_yticks(np.arange(len(reg_names)))
            ax.set_yticklabels(reg_names)
            ax.set_ylabel(name)

        axes[-1].set_xticks(np.arange(len(data[names[0]]["bits"]))[::4])
        axes[-1].set_xticklabels(data[names[0]]["bits"][::4])
        axes[-1].set_xlabel("Bit")
        fig.suptitle(title)
        fig.colorbar(im, ax=axes, label=colorbar_label, fraction=0.025, pad=0.015)
        fig.tight_layout(rect=[0, 0, 0.96, 0.98])

        out_path = OUT_DIR / filename
        fig.savefig(out_path, dpi=FIG_DPI)
        plt.close(fig)
        print(f"[INFO] Saved plot: {out_path}")

    save_combined_heatmap(
        lambda name: metrics[name]["peak_per_target"],
        "heatmap_peak_snr_all_sboxes.png",
        "Peak SNR Heatmaps Across S-boxes",
        "SNR",
        0.0,
        peak_vmax,
    )
    save_combined_heatmap(
        lambda name: np.log10(np.maximum(metrics[name]["peak_per_target"], 0.0) + EPS),
        "heatmap_log_peak_snr_all_sboxes.png",
        f"log10(Peak SNR + {EPS:g}) Heatmaps Across S-boxes",
        f"log10(SNR + {EPS:g})",
        log_vmin,
        log_vmax,
    )
    save_combined_heatmap(
        lambda name: np.clip(metrics[name]["peak_per_target"], 0.0, clipped_vmax),
        "heatmap_peak_snr_clipped_all_sboxes.png",
        f"Peak SNR Heatmaps Clipped at P{HEATMAP_CLIP_PERCENTILE:g} Across S-boxes",
        "SNR",
        0.0,
        clipped_vmax,
    )


def plot_mean_snr_trace_per_register(data, metrics):
    names = list(metrics.keys())
    reg_names = data[names[0]]["reg_names"]

    for name, m in metrics.items():
        sample_index = data[name]["sample_index"]
        x = sample_index[::TIME_PLOT_DOWNSAMPLE]

        plt.figure(figsize=(10, 5))
        for reg_i, reg_name in enumerate(data[name]["reg_names"]):
            y = m["mean_trace_per_register"][reg_i, ::TIME_PLOT_DOWNSAMPLE]
            plt.plot(x, y, linewidth=1.5, label=reg_name)
        plt.xlabel("Sample index")
        plt.ylabel("Mean SNR over 64 bits")
        plt.title(f"Mean SNR Trace Per Register - {name}")
        plt.legend()
        plt.grid(True, alpha=0.3)
        savefig(f"mean_snr_trace_per_register_{name}.png")

    for reg_i, reg_name in enumerate(reg_names):
        plt.figure(figsize=(10, 5))
        for name, m in metrics.items():
            sample_index = data[name]["sample_index"]
            x = sample_index[::TIME_PLOT_DOWNSAMPLE]
            y = m["mean_trace_per_register"][reg_i, ::TIME_PLOT_DOWNSAMPLE]
            plt.plot(x, y, linewidth=1.4, color=sbox_color(name), label=name)
        plt.xlabel("Sample index")
        plt.ylabel(f"Mean SNR over bits of {reg_name}")
        plt.title(f"Mean SNR Trace for {reg_name} Across S-boxes")
        plt.legend()
        plt.grid(True, alpha=0.3)
        savefig(f"mean_snr_trace_register_{reg_name}_comparison.png")


def save_top_target_tables(data, metrics, top_k=TOP_K):
    print(f"[INFO] Top-{top_k} target CSV export disabled")


def plot_comparison_dashboard(data, metrics, summary_df):
    """
    One dashboard figure containing:
      1. mean_peak_snr
      2. max_peak_snr
      3. sum_integrated_snr
      4. fraction_snr_gt_threshold
      5. peak_snr_distribution
      6. mean_snr_trace
    """

    names = list(metrics.keys())
    global_df = summary_df[summary_df["scope"] == "global"].copy()

    # Keep same ordering as SNR_FILES / metrics
    global_df["sbox"] = pd.Categorical(global_df["sbox"], categories=names, ordered=True)
    global_df = global_df.sort_values("sbox")

    fig, axes = plt.subplots(2, 3, figsize=(18, 10))

    ax_mean_peak = axes[0, 0]
    ax_max_peak = axes[0, 1]
    ax_integrated = axes[0, 2]
    ax_fraction = axes[1, 0]
    ax_distribution = axes[1, 1]
    ax_trace = axes[1, 2]

    x = np.arange(len(names))
    bar_colors = [sbox_color(name) for name in names]

    # ------------------------------------------------------------
    # 1. Mean peak SNR
    # ------------------------------------------------------------
    ax_mean_peak.bar(x, global_df["mean_peak_snr"].values, color=bar_colors)
    ax_mean_peak.set_xticks(x)
    ax_mean_peak.set_xticklabels(names, rotation=30, ha="right")
    ax_mean_peak.set_ylabel("Mean peak SNR")
    ax_mean_peak.set_title("Mean Peak SNR")
    ax_mean_peak.grid(True, axis="y", alpha=0.3)

    # ------------------------------------------------------------
    # 2. Max peak SNR
    # ------------------------------------------------------------
    ax_max_peak.bar(x, global_df["max_peak_snr"].values, color=bar_colors)
    ax_max_peak.set_xticks(x)
    ax_max_peak.set_xticklabels(names, rotation=30, ha="right")
    ax_max_peak.set_ylabel("Max peak SNR")
    ax_max_peak.set_title("Maximum Peak SNR")
    ax_max_peak.grid(True, axis="y", alpha=0.3)

    # ------------------------------------------------------------
    # 3. Sum integrated SNR
    # ------------------------------------------------------------
    ax_integrated.bar(x, global_df["sum_integrated_snr"].values, color=bar_colors)
    ax_integrated.set_xticks(x)
    ax_integrated.set_xticklabels(names, rotation=30, ha="right")
    ax_integrated.set_ylabel("Sum integrated SNR")
    ax_integrated.set_title("Total Integrated SNR")
    ax_integrated.grid(True, axis="y", alpha=0.3)

    # ------------------------------------------------------------
    # 4. Fraction of samples above SNR thresholds
    # ------------------------------------------------------------
    fraction_cols = [
        c for c in global_df.columns
        if c.startswith("fraction_snr_gt_")
    ]

    thresholds = [
        float(c.replace("fraction_snr_gt_", ""))
        for c in fraction_cols
    ]

    # Sort thresholds numerically
    sorted_pairs = sorted(zip(thresholds, fraction_cols), key=lambda p: p[0])
    thresholds = [p[0] for p in sorted_pairs]
    fraction_cols = [p[1] for p in sorted_pairs]

    for _, row in global_df.iterrows():
        y = [row[c] for c in fraction_cols]
        ax_fraction.plot(
            thresholds,
            y,
            marker="o",
            linewidth=1.8,
            color=sbox_color(row["sbox"]),
            label=row["sbox"],
        )

    ax_fraction.set_xlabel("SNR threshold")
    ax_fraction.set_ylabel("Fraction above threshold")
    ax_fraction.set_title("Fraction of SNR Samples Above Threshold")
    ax_fraction.grid(True, alpha=0.3)
    ax_fraction.legend()

    # ------------------------------------------------------------
    # 5. Peak SNR distribution
    # ------------------------------------------------------------
    for name, m in metrics.items():
        ax_distribution.hist(
            m["peak_flat"],
            bins=HIST_BINS,
            density=True,
            histtype="step",
            linewidth=1.8,
            color=sbox_color(name),
            label=name,
        )

    ax_distribution.set_xlabel("Peak SNR per target bit")
    ax_distribution.set_ylabel("Density")
    ax_distribution.set_title("Peak SNR Distribution")
    ax_distribution.grid(True, alpha=0.3)
    ax_distribution.legend()

    # ------------------------------------------------------------
    # 6. Mean SNR trace
    # ------------------------------------------------------------
    for name, m in metrics.items():
        sample_index = data[name]["sample_index"]
        x_trace = sample_index[::TIME_PLOT_DOWNSAMPLE]
        y_trace = m["mean_trace"][::TIME_PLOT_DOWNSAMPLE]
        ax_trace.plot(x_trace, y_trace, linewidth=1.3, color=sbox_color(name), label=name)

    ax_trace.set_xlabel("Sample index")
    ax_trace.set_ylabel("Mean SNR")
    ax_trace.set_title("Mean SNR Trace Over Time")
    ax_trace.grid(True, alpha=0.3)
    ax_trace.legend()

    fig.suptitle("SNR Comparison Dashboard Across S-box Implementations", fontsize=16)

    plt.tight_layout(rect=[0, 0, 1, 0.95])

    out_path = OUT_DIR / "snr_comparison_dashboard.png"
    plt.savefig(out_path, dpi=FIG_DPI)
    plt.close()

    print(f"[INFO] Saved plot: {out_path}")


def plot_comparison_dashboard_improved(data, metrics, summary_df):
    names = list(metrics.keys())
    global_df = summary_df[summary_df["scope"] == "global"].copy()
    global_df["sbox"] = pd.Categorical(global_df["sbox"], categories=names, ordered=True)
    global_df = global_df.sort_values("sbox")

    fig, axes = plt.subplots(2, 3, figsize=(18, 10))
    ax_mean_peak, ax_max_peak, ax_box, ax_ccdf, ax_trace, ax_counts = axes.reshape(-1)
    x = np.arange(len(names))
    bar_colors = [sbox_color(name) for name in names]

    ax_mean_peak.bar(x, global_df["mean_peak_snr"].values, color=bar_colors)
    ax_mean_peak.set_xticks(x)
    ax_mean_peak.set_xticklabels(names, rotation=30, ha="right")
    ax_mean_peak.set_ylabel("Mean peak SNR")
    ax_mean_peak.set_title("Mean Peak SNR")
    ax_mean_peak.grid(True, axis="y", alpha=0.3)

    ax_max_peak.bar(x, global_df["max_peak_snr"].values, color=bar_colors)
    ax_max_peak.set_xticks(x)
    ax_max_peak.set_xticklabels(names, rotation=30, ha="right")
    ax_max_peak.set_ylabel("Max peak SNR")
    ax_max_peak.set_title("Maximum Peak SNR")
    ax_max_peak.grid(True, axis="y", alpha=0.3)

    box = ax_box.boxplot(
        [np.maximum(metrics[name]["peak_flat"], 0.0) + EPS for name in names],
        labels=names,
        showfliers=True,
        patch_artist=True,
    )
    for patch, name in zip(box["boxes"], names):
        patch.set_facecolor(sbox_color(name))
        patch.set_alpha(0.35)
        patch.set_edgecolor(sbox_color(name))
    ax_box.set_yscale("log")
    ax_box.set_xticklabels(names, rotation=30, ha="right")
    ax_box.set_ylabel("Peak SNR per target bit")
    ax_box.set_title("Peak SNR Boxplot (log y)")
    ax_box.grid(True, axis="y", which="both", alpha=0.3)

    for name, m in metrics.items():
        ccdf_x = np.sort(m["peak_flat"])
        ccdf_y = (ccdf_x.size - np.arange(ccdf_x.size)) / ccdf_x.size
        ax_ccdf.step(
            ccdf_x,
            ccdf_y,
            where="post",
            linewidth=1.5,
            color=sbox_color(name),
            label=name,
        )
    ax_ccdf.set_yscale("log")
    ax_ccdf.set_xlabel("Peak SNR per target bit")
    ax_ccdf.set_ylabel("P(peak SNR > x)")
    ax_ccdf.set_title("Peak SNR CCDF")
    ax_ccdf.grid(True, which="both", alpha=0.3)
    ax_ccdf.legend()

    for name, m in metrics.items():
        sample_index = data[name]["sample_index"]
        x_trace = sample_index[::TIME_PLOT_DOWNSAMPLE]
        y_trace = m["mean_trace"][::TIME_PLOT_DOWNSAMPLE]
        ax_trace.plot(x_trace, y_trace, linewidth=1.3, color=sbox_color(name), label=name)
    ax_trace.set_xlabel("Sample index")
    ax_trace.set_ylabel("Mean SNR")
    ax_trace.set_title("Mean SNR Trace")
    ax_trace.grid(True, alpha=0.3)
    ax_trace.legend()

    count_cols = [c for c in global_df.columns if c.startswith("count_snr_gt_")]
    sorted_pairs = sorted(
        [(float(c.replace("count_snr_gt_", "")), c) for c in count_cols],
        key=lambda p: p[0],
    )
    thresholds = [p[0] for p in sorted_pairs]
    count_cols = [p[1] for p in sorted_pairs]

    for _, row in global_df.iterrows():
        y = [row[c] for c in count_cols]
        ax_counts.plot(
            thresholds,
            y,
            marker="o",
            linewidth=1.6,
            color=sbox_color(row["sbox"]),
            label=row["sbox"],
        )
    ax_counts.set_xlabel("SNR threshold")
    ax_counts.set_ylabel("Sample count above threshold")
    ax_counts.set_title("Leakage Sample Counts")
    ax_counts.grid(True, alpha=0.3)
    ax_counts.legend()

    fig.suptitle("Improved SNR Comparison Dashboard", fontsize=16)
    plt.tight_layout(rect=[0, 0, 1, 0.95])

    out_path = OUT_DIR / "snr_comparison_dashboard_improved.png"
    plt.savefig(out_path, dpi=FIG_DPI)
    plt.close()
    print(f"[INFO] Saved plot: {out_path}")


def plot_snr_pdf_kde(metrics, mode="peak", num_points=1000):
    """
    Plot estimated PDF of SNR values using both normalized histogram and KDE.

    mode:
      "peak" -> PDF of peak SNR per target bit, 320 values per S-box
      "all"  -> PDF of all SNR values over registers, bits, and time
    """

    try:
        from scipy.stats import gaussian_kde
        SCIPY_AVAILABLE = True
    except Exception:
        gaussian_kde = None
        SCIPY_AVAILABLE = False

    plt.figure(figsize=(9, 5))

    all_values_for_range = []

    values_dict = {}

    for name, m in metrics.items():
        if mode == "peak":
            values = m["peak_flat"]
        elif mode == "all":
            # This requires access to all SNR values.
            # If you stored only metrics, use m["snr_flat"] if added.
            raise ValueError(
                "mode='all' needs direct access to full SNR arrays. "
                "Use plot_full_snr_pdf_kde(data, ...) instead."
            )
        else:
            raise ValueError("mode must be 'peak' or 'all'")

        values = np.asarray(values, dtype=np.float64)
        values = values[np.isfinite(values)]
        values_dict[name] = values
        all_values_for_range.append(values)

    all_values = np.concatenate(all_values_for_range)

    xmin = float(np.min(all_values))
    xmax = float(np.max(all_values))

    if xmax <= xmin:
        print("[WARN] Cannot plot PDF: all values are identical.")
        return

    x_grid = np.linspace(xmin, xmax, num_points)

    for name, values in values_dict.items():
        # Histogram-based empirical PDF
        plt.hist(
            values,
            bins=HIST_BINS,
            density=True,
            alpha=0.20,
            color=sbox_color(name),
            label=f"{name} histogram",
        )

        # Smooth KDE curve
        if SCIPY_AVAILABLE and len(values) > 1:
            kde = gaussian_kde(values)
            y_grid = kde(x_grid)
            plt.plot(
                x_grid,
                y_grid,
                linewidth=2.0,
                color=sbox_color(name),
                label=f"{name} KDE",
            )

    plt.xlabel("Peak SNR" if mode == "peak" else "SNR")
    plt.ylabel("Estimated probability density")
    plt.title("Estimated PDF of Peak SNR Across Target Bits")
    plt.grid(True, alpha=0.3)
    plt.legend()

    out_path = OUT_DIR / f"pdf_kde_{mode}_snr.png"
    plt.tight_layout()
    plt.savefig(out_path, dpi=FIG_DPI)
    plt.close()

    print(f"[INFO] Saved plot: {out_path}")

def plot_full_snr_pdf_kde(data, num_points=1000, max_values_per_sbox=2_000_000):
    """
    Plot estimated PDF of all SNR values:
        SNR[register, bit, sample]

    To avoid huge memory/slow KDE, the function optionally subsamples values.
    """

    try:
        from scipy.stats import gaussian_kde
        SCIPY_AVAILABLE = True
    except Exception:
        gaussian_kde = None
        SCIPY_AVAILABLE = False

    plt.figure(figsize=(9, 5))

    values_dict = {}
    all_values_for_range = []

    rng = np.random.default_rng(12345)

    for name, d in data.items():
        values = d["snr"].reshape(-1).astype(np.float64)
        values = values[np.isfinite(values)]

        if values.size > max_values_per_sbox:
            idx = rng.choice(values.size, size=max_values_per_sbox, replace=False)
            values = values[idx]

        values_dict[name] = values
        all_values_for_range.append(values)

    all_values = np.concatenate(all_values_for_range)

    xmin = float(np.min(all_values))
    xmax = float(np.max(all_values))

    if xmax <= xmin:
        print("[WARN] Cannot plot full SNR PDF: all values are identical.")
        return

    x_grid = np.linspace(xmin, xmax, num_points)

    for name, values in values_dict.items():
        plt.hist(
            values,
            bins=HIST_BINS,
            density=True,
            histtype="stepfilled",
            alpha=0.18,
            color=sbox_color(name),
            label=f"{name} histogram",
        )

        if SCIPY_AVAILABLE and len(values) > 1:
            kde = gaussian_kde(values)
            y_grid = kde(x_grid)
            plt.plot(
                x_grid,
                y_grid,
                linewidth=2.0,
                color=sbox_color(name),
                label=f"{name} KDE",
            )

    plt.xlabel("SNR value")
    plt.ylabel("Estimated probability density")
    plt.title("Estimated PDF of All SNR Values")
    plt.grid(True, alpha=0.3)
    plt.legend()

    out_path = OUT_DIR / "pdf_kde_all_snr_values.png"
    plt.tight_layout()
    plt.savefig(out_path, dpi=FIG_DPI)
    plt.close()

    print(f"[INFO] Saved plot: {out_path}")

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("[INFO] Loading SNR files")

    data = {}
    for name, path in SNR_FILES.items():
        print(f"[INFO] Loading {name}: {path}")
        if SKIP_MISSING_FILES and not Path(path).exists():
            print(f"[WARN] Skipping {name}: SNR file not found: {path}")
            continue
        data[name] = load_snr_file(path)
        print(f"       shape = {data[name]['snr'].shape}")

    if not data:
        raise RuntimeError("No SNR files were loaded. Check SNR_FILES.")

    validate_datasets(data)

    print("[INFO] Computing comparison metrics")
    metrics = {}
    all_rows = []

    for name, d in data.items():
        metrics[name] = compute_metrics(name, d, SNR_THRESHOLDS)
        all_rows.extend(metrics[name]["rows"])

    summary_df = pd.DataFrame(all_rows)

    summary_csv = OUT_DIR / "snr_summary_metrics.csv"
    summary_df.to_csv(summary_csv, index=False)
    print(f"[INFO] Saved summary CSV: {summary_csv}")

    # Also save target-level peak SNR table.
    target_rows = []

    for name, m in metrics.items():
        peak = m["peak_per_target"]
        integrated = m["integrated_per_target"]

        for reg_i in range(peak.shape[0]):
            for bit_i in range(peak.shape[1]):
                target_rows.append({
                    "sbox": name,
                    "register": f"x{reg_i}",
                    "bit": bit_i,
                    "peak_snr": float(peak[reg_i, bit_i]),
                    "integrated_snr": float(integrated[reg_i, bit_i]),
                })

    target_df = pd.DataFrame(target_rows)
    target_df = target_df.sort_values(["sbox", "peak_snr"], ascending=[True, False])

    target_csv = OUT_DIR / "snr_target_level_metrics.csv"
    target_df.to_csv(target_csv, index=False)
    print(f"[INFO] Saved target-level CSV: {target_csv}")

    print("[INFO] Generating plots")

    plot_peak_histograms(metrics)
    plot_peak_cdf(metrics)
    plot_mean_snr_trace(data, metrics)
    plot_max_snr_trace(data, metrics)
    plot_per_register_mean_peak(data, metrics)
    plot_per_register_max_peak(data, metrics)
    plot_integrated_snr_distribution(metrics)
    plot_threshold_counts(summary_df)
    plot_top_bits(metrics, top_k=TOP_K)
    plot_comparison_dashboard(data, metrics, summary_df)
    plot_skew_aware_distributions(data, metrics)
    plot_log_boxplots(metrics)
    plot_heatmaps(data, metrics)
    plot_mean_snr_trace_per_register(data, metrics)
    save_top_target_tables(data, metrics, top_k=TOP_K)
    plot_comparison_dashboard_improved(data, metrics, summary_df)
    plot_snr_pdf_kde(metrics, mode="peak")
    plot_full_snr_pdf_kde(data, max_values_per_sbox=MAX_VALUES_PER_SBOX)

    print("[INFO] Done")


if __name__ == "__main__":
    main()
