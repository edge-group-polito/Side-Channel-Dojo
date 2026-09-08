#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
PYTHON_BIN="python3"
export MPLCONFIGDIR="/tmp/matplotlib-ascon"

N_TRACES="1000000"
TRACESET_SIZE_K="1000"
TRACE_TAG="1000k"
ANALYSIS_MAX_TIME_US="1.5"
PROGRESS_COUNTS="10,100,1000,10000,100000,200000,300000,400000,500000,600000,700000,800000,900000,1000000"
PROGRESSION_POLARITY="${ASCON_PROGRESSION_POLARITY:-both}"

RUN_TAG="${ASCON_RUN_TAG:-$(date -u +%Y%m%dT%H%M%SZ)}"
ANALYSIS_OUTPUT_ROOT="${ASCON_ANALYSIS_OUTPUT_ROOT:-sw/sca_scripts/ASCON/paper_analysis/$RUN_TAG}"
PAPER_ASCON_METRICS_DIR="${ASCON_PAPER_METRICS_DIR:-sw/sca_scripts/paper/media/ASCON_attack_metrics}"

ALL_POLARITIES_DEFAULT="negative positive both"

BASELINE_POLARITIES_RAW="${ASCON_BASELINE_POLARITIES:-$ALL_POLARITIES_DEFAULT}"
BASELINE_POLARITIES_RAW="${BASELINE_POLARITIES_RAW//,/ }"
read -r -a BASELINE_POLARITIES <<< "$BASELINE_POLARITIES_RAW"

DEPENDENCY_AWARE_POLARITIES_RAW="${ASCON_DEPENDENCY_AWARE_POLARITIES:-$ALL_POLARITIES_DEFAULT}"
DEPENDENCY_AWARE_POLARITIES_RAW="${DEPENDENCY_AWARE_POLARITIES_RAW//,/ }"
read -r -a DEPENDENCY_AWARE_POLARITIES <<< "$DEPENDENCY_AWARE_POLARITIES_RAW"

CROSS_TRACE_SBOXES="${ASCON_CROSS_TRACE_SBOXES:-all}"
CROSS_MODEL_SBOXES="${ASCON_CROSS_MODEL_SBOXES:-all}"

SW_SBOXES=(lut_ascon lut_bilgin lut_allouzi lut_lu_4 lut_lu_5 lut_lu_6 lut_lu_7)
HW_SBOXES=(hw lut_ascon lut_bilgin lut_allouzi lut_lu_4 lut_lu_5 lut_lu_6 lut_lu_7)

cd "$ROOT_DIR"

run_sw_snr_if_missing() {
  local sbox="$1"
  local cache_dir="sw/sca_scripts/ASCON/sw/cache/$sbox"
  local ranked_file="$cache_dir/snr_ranked_${sbox}_${TRACE_TAG}.h5"
  local traces_file="$cache_dir/snr_traces_${sbox}_${TRACE_TAG}.h5"

  if [[ -f "$ranked_file" && -f "$traces_file" ]]; then
    echo "[INFO] Reusing SW SNR cache: $sbox"
    return
  fi

  echo "[INFO] Generating SW SNR cache: $sbox"
  "$PYTHON_BIN" sw/sca_scripts/ASCON/sw/xheep_ASCON_snr.py \
    --sbox "$sbox" \
    --n-traces "$N_TRACES" \
    --traceset-size-k "$TRACESET_SIZE_K"
}

run_hw_snr_if_missing() {
  local sbox="$1"
  local cache_dir="sw/sca_scripts/ASCON/hw/cache/ascon_init/$sbox"
  local ranked_file="$cache_dir/snr_ranked_${sbox}_${TRACE_TAG}.h5"
  local traces_file="$cache_dir/snr_traces_${sbox}_${TRACE_TAG}.h5"

  if [[ -f "$ranked_file" && -f "$traces_file" ]]; then
    echo "[INFO] Reusing HW SNR cache: $sbox"
    return
  fi

  echo "[INFO] Generating HW SNR cache: $sbox"
  "$PYTHON_BIN" sw/sca_scripts/ASCON/hw/ascon_init_ASCON_snr.py \
    --sbox "$sbox" \
    --n-traces "$N_TRACES" \
    --traceset-size-k "$TRACESET_SIZE_K" \
    --analysis-max-time-us "$ANALYSIS_MAX_TIME_US"
}

run_baseline_cross_tables() {
  local polarity="$1"
  local out_dir="$ANALYSIS_OUTPUT_ROOT/baseline/$polarity/cross_leakage_model_cpa_table"

  echo "[INFO] Baseline cross leakage-model CPA, polarity=$polarity"
  "$PYTHON_BIN" sw/sca_scripts/ASCON/run_ascon_baseline_cross_leakage_model_cpa_table.py \
    --implementation both \
    --trace-sboxes "$CROSS_TRACE_SBOXES" \
    --model-sboxes "$CROSS_MODEL_SBOXES" \
    --n-traces "$N_TRACES" \
    --traceset-size-k "$TRACESET_SIZE_K" \
    --polarity "$polarity" \
    --analysis-max-time-us "$ANALYSIS_MAX_TIME_US" \
    --output-dir "$out_dir"
}

run_dependency_aware_cross_tables() {
  local polarity="$1"
  local out_dir="$ANALYSIS_OUTPUT_ROOT/dependency_aware/$polarity/cross_leakage_model_cpa_table"

  echo "[INFO] Dependency-aware cross leakage-model CPA, polarity=$polarity"
  ASCON_CPA_POLICY=dependency_aware \
  "$PYTHON_BIN" sw/sca_scripts/ASCON/run_ascon_cross_leakage_model_cpa_table.py \
    --implementation both \
    --trace-sboxes "$CROSS_TRACE_SBOXES" \
    --model-sboxes "$CROSS_MODEL_SBOXES" \
    --n-traces "$N_TRACES" \
    --traceset-size-k "$TRACESET_SIZE_K" \
    --polarity "$polarity" \
    --analysis-max-time-us "$ANALYSIS_MAX_TIME_US" \
    --output-dir "$out_dir"
}

make_paper_progression_plot() {
  local implementation="$1"
  local input_json="$2"
  local output_stem="$3"

  "$PYTHON_BIN" - "$implementation" "$input_json" "$output_stem" <<'PY'
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

implementation = sys.argv[1].upper()
input_json = Path(sys.argv[2])
output_stem = Path(sys.argv[3])

with input_json.open("r", encoding="utf-8") as handle:
    combined = json.load(handle)

label_map = {
    "hw": "HW",
    "lut_ascon": "Ascon",
    "lut_bilgin": "Bilgin",
    "lut_allouzi": "Allouzi",
    "lut_lu_4": "Lu 4",
    "lut_lu_5": "Lu 5",
    "lut_lu_6": "Lu 6",
    "lut_lu_7": "Lu 7",
}
colors = {
    "hw": "#222222",
    "lut_ascon": "#2f6fbb",
    "lut_bilgin": "#d95f02",
    "lut_allouzi": "#1b9e77",
    "lut_lu_4": "#7570b3",
    "lut_lu_5": "#e7298a",
    "lut_lu_6": "#66a61e",
    "lut_lu_7": "#a6761d",
}

fig, axes = plt.subplots(1, 2, figsize=(12.4, 4.6), sharex=True)
for sbox, result in combined["results"].items():
    trace_counts = result["trace_counts"]
    correct_bits = result["correct_key_bits_count"]
    success_rate = [100.0 * value / 128.0 for value in correct_bits]
    residual_pge = [128 - value for value in correct_bits]
    color = colors.get(sbox)
    label = label_map.get(sbox, sbox)

    axes[0].plot(
        trace_counts,
        success_rate,
        marker="o",
        markersize=3.2,
        linewidth=1.8,
        color=color,
        label=label,
    )
    axes[1].plot(
        trace_counts,
        residual_pge,
        marker="o",
        markersize=3.2,
        linewidth=1.8,
        color=color,
        label=label,
    )

    exact_flags = result.get("full_key_match", [])
    for trace_count, exact in zip(trace_counts, exact_flags):
        if exact:
            index = trace_counts.index(trace_count)
            axes[0].scatter(
                [trace_count],
                [success_rate[index]],
                marker="*",
                s=95,
                color=color,
                edgecolor="black",
                linewidth=0.45,
                zorder=5,
            )

for ax in axes:
    ax.set_xscale("log")
    ax.xaxis.set_major_locator(mticker.LogLocator(base=10))
    ax.xaxis.set_major_formatter(
        mticker.FuncFormatter(
            lambda value, _pos: (
                f"{int(value // 1_000_000)}M"
                if value >= 1_000_000 and value % 1_000_000 == 0
                else f"{int(value // 1000)}k"
                if value >= 1000 and value % 1000 == 0
                else str(int(value))
            )
        )
    )
    ax.xaxis.set_minor_locator(mticker.LogLocator(base=10, subs=range(2, 10)))
    ax.xaxis.set_minor_formatter(mticker.NullFormatter())
    ax.grid(True, which="both", alpha=0.28)
    ax.set_xlabel("Number of traces")

axes[0].set_ylabel("Correct key-bit rate (%)")
axes[0].set_ylim(0, 103)
axes[0].set_yticks(range(0, 101, 20))
axes[0].set_title("Correct key-bit rate")

axes[1].set_ylabel("Residual PGE (bits)")
axes[1].set_ylim(-1, 128)
axes[1].set_yticks(range(0, 129, 16))
axes[1].set_title("Residual PGE")

handles, labels = axes[0].get_legend_handles_labels()
fig.legend(handles, labels, loc="lower center", ncol=4, frameon=False)
fig.suptitle(f"ASCON {implementation} key-recovery progression", y=0.98)
fig.tight_layout(rect=[0, 0.12, 1, 0.94])

output_stem.parent.mkdir(parents=True, exist_ok=True)
fig.savefig(output_stem.with_suffix(".pdf"), bbox_inches="tight")
fig.savefig(output_stem.with_suffix(".png"), dpi=300, bbox_inches="tight")
plt.close(fig)

print(f"[INFO] Wrote paper plot: {output_stem.with_suffix('.pdf')}")
print(f"[INFO] Wrote paper plot: {output_stem.with_suffix('.png')}")
PY
}

make_paper_plots() {
  local sw_json="sw/sca_scripts/ASCON/sw/cache/key_recovery_progression_all_sboxes/prefix/ASCON_generic_key_recovery_progression_all_sboxes_${TRACE_TAG}_prefix_snr.json"
  local hw_json="sw/sca_scripts/ASCON/hw/cache/ascon_init/key_recovery_progression_all_sboxes/prefix/ASCON_generic_key_recovery_progression_all_sboxes_${TRACE_TAG}_prefix_snr.json"

  echo "[INFO] Generating paper-ready ASCON key-recovery plots"
  make_paper_progression_plot "sw" "$sw_json" "$PAPER_ASCON_METRICS_DIR/ASCON_SW_SR_PGE"
  make_paper_progression_plot "hw" "$hw_json" "$PAPER_ASCON_METRICS_DIR/ASCON_HW_SR_PGE"
}

echo "[INFO] ASCON SW/HW analysis, 1M traces"
echo "[INFO] Progression counts: $PROGRESS_COUNTS"
echo "[INFO] Analysis output root: $ANALYSIS_OUTPUT_ROOT"
echo "[INFO] Baseline polarities: ${BASELINE_POLARITIES[*]}"
echo "[INFO] Dependency-aware polarities: ${DEPENDENCY_AWARE_POLARITIES[*]}"
echo "[INFO] Progression polarity: $PROGRESSION_POLARITY"

echo "[INFO] Step 1/7: SW SNR cache + comparison plots"
for sbox in "${SW_SBOXES[@]}"; do
  run_sw_snr_if_missing "$sbox"
done
"$PYTHON_BIN" sw/sca_scripts/ASCON/sw/xheep_ASCON_snr_compare.py \
  --implementation sw \
  --n-traces "$N_TRACES" \
  --tag "$TRACE_TAG"

echo "[INFO] Step 2/7: HW SNR cache + comparison plots"
for sbox in "${HW_SBOXES[@]}"; do
  run_hw_snr_if_missing "$sbox"
done
"$PYTHON_BIN" sw/sca_scripts/ASCON/hw/ascon_init_ASCON_snr_compare.py \
  --n-traces "$N_TRACES" \
  --tag "$TRACE_TAG" \
  --include-comb

echo "[INFO] Step 3/7: Baseline cross leakage-model CPA tables"
for polarity in "${BASELINE_POLARITIES[@]}"; do
  run_baseline_cross_tables "$polarity"
done

echo "[INFO] Step 4/7: Dependency-aware cross leakage-model CPA tables"
for polarity in "${DEPENDENCY_AWARE_POLARITIES[@]}"; do
  run_dependency_aware_cross_tables "$polarity"
done

echo "[INFO] Step 5/7: HW key-recovery progression with per-prefix SNR"
"$PYTHON_BIN" sw/sca_scripts/ASCON/hw/ascon_init_ASCON_key_recovery_progression_all_sboxes.py \
  --max-traces "$N_TRACES" \
  --traceset-size-k "$TRACESET_SIZE_K" \
  --snr-traces "$N_TRACES" \
  --trace-counts "$PROGRESS_COUNTS" \
  --snr-selection-mode prefix \
  --analysis-max-time-us "$ANALYSIS_MAX_TIME_US" \
  --polarity "$PROGRESSION_POLARITY" \
  --cpa-policy dependency_aware \
  --mixed-top-groups 1 \
  --mixed-min-fact-support 2 \
  --plot-x-scale log \
  --cpa-device cpu \
  --sboxes all \
  --save-plots

echo "[INFO] Step 6/7: SW key-recovery progression with per-prefix SNR"
"$PYTHON_BIN" sw/sca_scripts/ASCON/sw/xheep_ASCON_key_recovery_progression_all_sboxes.py \
  --max-traces "$N_TRACES" \
  --traceset-size-k "$TRACESET_SIZE_K" \
  --snr-traces "$N_TRACES" \
  --trace-counts "$PROGRESS_COUNTS" \
  --snr-selection-mode prefix \
  --polarity "$PROGRESSION_POLARITY" \
  --cpa-policy dependency_aware \
  --mixed-top-groups 1 \
  --mixed-min-fact-support 2 \
  --plot-x-scale log \
  --cpa-device cpu \
  --sboxes all \
  --save-plots

echo "[INFO] Step 7/7: Paper-ready ASCON plots"
make_paper_plots

echo "[INFO] Finished. Analysis output root: $ANALYSIS_OUTPUT_ROOT"
echo "[INFO] Paper plots: $PAPER_ASCON_METRICS_DIR"
