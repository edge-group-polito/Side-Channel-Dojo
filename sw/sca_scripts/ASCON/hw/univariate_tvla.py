import os
import sys
from pathlib import Path
import h5py
import numpy as np
from scipy.stats import ttest_ind
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch

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

def _yn(flag: bool) -> str:
    """Return 'yes' or 'no' for a boolean flag."""
    return "yes" if flag else "no"

def main():
    # ---------------------------------------------------------------------------
    # Setup and Path Resolution
    # ---------------------------------------------------------------------------
    try:
        SCRIPT_DIR = Path(__file__).resolve().parent
    except NameError:
        SCRIPT_DIR = Path.cwd()

    DOJO_ROOT = find_project_root(SCRIPT_DIR)

    # Configuration
    n_trc_captured = 2_000 
    n_load = 1_000          # Set to 10_00 to use all available traces per class
    skip = 70                # Samples to skip at the beginning
    
    # Flags
    save_plot = True

    # Paths
    TRACESET_DIR = DOJO_ROOT / "sw" / "traceset" / "ASCON" / "hw"
    TRACESET_FILE = TRACESET_DIR / f"ascon_masked_{n_trc_captured // 1000}k_tvla.h5"
    
    PLOT_DIR = DOJO_ROOT / "sw" / "sca_scripts" / "ASCON" / "hw" / "plot" / "ascon_masked"
    PLOT_DIR.mkdir(parents=True, exist_ok=True)
    PLOT_FILE = PLOT_DIR / "ascon_tvla_higher_order.png"

    # ---------------------------------------------------------------------------
    # Configuration Printout
    # ---------------------------------------------------------------------------
    print("\n================= TVLA ANALYSIS CONFIGURATION =================")
    print(f"DOJO_ROOT           : {DOJO_ROOT}")
    print()
    print("Target")
    print(f"  Cipher            : ASCON-128")
    print(f"  Analysis scope    : 1st, 2nd, and 3rd-Order TVLA")
    print()
    print("Dataset")
    print(f"  Traces file       : {TRACESET_FILE.name}")
    print(f"  Total captured    : {n_trc_captured}")
    print(f"  Traces loaded/cls : {n_load} fixed / {n_load} random")
    print(f"  Save plot         : {_yn(save_plot)}")
    print("===============================================================\n")

    # ---------------------------------------------------------------------------
    # Load Data
    # ---------------------------------------------------------------------------
    print(f"Loading traces from: {TRACESET_FILE}")
    with h5py.File(TRACESET_FILE, 'r') as f:
        all_traces = np.array(f['traces'])
        labels = np.array(f['labels'])

    mask_fixed = (labels == 0)
    mask_random = (labels == 1)
    
    print(f"Total traces found: {np.sum(mask_fixed)} fixed, {np.sum(mask_random)} random.")

    # ---------------------------------------------------------------------------
    # Higher-Order Preprocessing
    # ---------------------------------------------------------------------------
    print("Preprocessing traces for higher-order analysis...")
    # To compute 2nd and 3rd order, we mean-center the traces first.
    # $T'_i = (T_i - \mu_{global})$
    global_mean = np.mean(all_traces, axis=0)
    traces_centered = all_traces - global_mean
    
    traces_2nd = traces_centered ** 2
    traces_3rd = traces_centered ** 3

    # ---------------------------------------------------------------------------
    # Calculate Welch's T-Test
    # ---------------------------------------------------------------------------
    print("Calculating Welch's t-tests...")
    
    # 1st Order (Mean)
    t1, _ = ttest_ind(all_traces[mask_fixed][:n_load], all_traces[mask_random][:n_load], equal_var=False)
    # 2nd Order (Variance)
    t2, _ = ttest_ind(traces_2nd[mask_fixed][:n_load], traces_2nd[mask_random][:n_load], equal_var=False)
    # 3rd Order (Skewness)
    t3, _ = ttest_ind(traces_3rd[mask_fixed][:n_load], traces_3rd[mask_random][:n_load], equal_var=False)

    # Apply sample skipping
    mask_skip = np.arange(len(t1)) >= skip
    x_axis = np.arange(len(t1))[mask_skip] - skip

    t1_use = t1[mask_skip]
    t2_use = t2[mask_skip]
    t3_use = t3[mask_skip]

    fails_t1 = np.count_nonzero(np.abs(t1_use) > 4.5)
    fails_t2 = np.count_nonzero(np.abs(t2_use) > 4.5)
    fails_t3 = np.count_nonzero(np.abs(t3_use) > 4.5)

    print(f"\n--- Leakage Report (excluding first {skip} samples) ---")
    print(f"1st-Order leaky points: {fails_t1}")
    print(f"2nd-Order leaky points: {fails_t2}")
    print(f"3rd-Order leaky points: {fails_t3}")
    print("-------------------------------------------------------\n")

    # ---------------------------------------------------------------------------
    # Plotting
    # ---------------------------------------------------------------------------
    print("Generating plot...")
    fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=True)

    def plot_tvla(ax, curve, order_name, color):
        ax.plot(x_axis, curve, color=color, linewidth=0.8)
        ax.axhline(y=4.5, color='r', linestyle='--', alpha=0.7)
        ax.axhline(y=-4.5, color='r', linestyle='--', alpha=0.7)
        ax.set_title(f"{order_name} TVLA", fontsize=14)
        ax.set_ylabel("t-score", fontsize=12)
        ax.grid(True, alpha=0.3)
        
        # Add Vlines
        vlines = np.array([850, 1350, 1850])
        ymin, ymax = ax.get_ylim()
        ax.vlines(vlines, ymin, ymax, linestyles='--', linewidth=0.7, alpha=0.9, color='black', zorder=0)
        return ymin, ymax

    # Plot each order
    ymin1, ymax1 = plot_tvla(axes[0], t1_use, "1st-Order (Mean)", 'blue')
    plot_tvla(axes[1], t2_use, "2nd-Order (Variance)", 'green')
    plot_tvla(axes[2], t3_use, "3rd-Order (Skewness)", 'purple')

    # ----- Add Braces to the TOP subplot (1st Order) -----
    def add_brace(ax, x0, x1, y, label, lw=1.6, fs=12):
        brace = FancyArrowPatch((x0, y), (x1, y),
                                arrowstyle='|-|', mutation_scale=18,
                                lw=lw, color='black', clip_on=True, zorder=3)
        ax.add_patch(brace)
        ax.text((x0 + x1) / 2.0, y, label, ha='center', va='bottom', fontsize=fs, zorder=3)

    yr = ymax1 - ymin1
    y_brace = ymin1 + 0.06 * yr

    xmax = x_axis[-1]
    spans = [
        (0,    850,  "Initialization"),
        (850,  1350, "Process AAD"),
        (1350, 1850, "Process MSG"),
        (1850, xmax, "Finalization"),
    ]
    
    for x0, x1, lab in spans:
        if x1 > x0:
            add_brace(axes[0], x0, x1, y_brace, lab)

    # Polish axes
    axes[2].set_xlabel("Sample Index", fontsize=14)
    plt.tight_layout()

    # ---------------------------------------------------------------------------
    # Save Output
    # ---------------------------------------------------------------------------
    if save_plot:
        fig.savefig(PLOT_FILE, dpi=300)
        print(f"Plot successfully saved to: {PLOT_FILE}")
        
    # Explicitly close the figure to free memory without showing it
    plt.close(fig)

if __name__ == "__main__":
    main()