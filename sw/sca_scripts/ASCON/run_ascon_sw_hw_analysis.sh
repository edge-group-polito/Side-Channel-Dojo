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

echo "[INFO] ASCON SW/HW analysis, 1M traces"
echo "[INFO] Progression counts: $PROGRESS_COUNTS"

echo "[INFO] Step 1/6: SW SNR cache + comparison plots"
for sbox in "${SW_SBOXES[@]}"; do
  run_sw_snr_if_missing "$sbox"
done
"$PYTHON_BIN" sw/sca_scripts/ASCON/sw/xheep_ASCON_snr_compare.py \
  --implementation sw \
  --n-traces "$N_TRACES" \
  --tag "$TRACE_TAG"

echo "[INFO] Step 2/6: HW SNR cache + comparison plots"
for sbox in "${HW_SBOXES[@]}"; do
  run_hw_snr_if_missing "$sbox"
done
"$PYTHON_BIN" sw/sca_scripts/ASCON/hw/ascon_init_ASCON_snr_compare.py \
  --n-traces "$N_TRACES" \
  --tag "$TRACE_TAG" \
  --include-comb

echo "[INFO] Step 3/6: Cross leakage-model CPA table for SW and HW"
"$PYTHON_BIN" sw/sca_scripts/ASCON/run_ascon_cross_leakage_model_cpa_table.py \
  --implementation both \
  --n-traces "$N_TRACES" \
  --traceset-size-k "$TRACESET_SIZE_K" \
  --polarity negative \
  --analysis-max-time-us "$ANALYSIS_MAX_TIME_US"

echo "[INFO] Step 4/6: HW key-recovery progression with per-prefix SNR"
"$PYTHON_BIN" sw/sca_scripts/ASCON/hw/ascon_init_ASCON_key_recovery_progression_all_sboxes.py \
  --max-traces "$N_TRACES" \
  --traceset-size-k "$TRACESET_SIZE_K" \
  --snr-traces "$N_TRACES" \
  --trace-counts "$PROGRESS_COUNTS" \
  --snr-selection-mode prefix \
  --analysis-max-time-us "$ANALYSIS_MAX_TIME_US" \
  --polarity both \
  --cpa-device cpu \
  --sboxes all

echo "[INFO] Step 5/6: SW key-recovery progression with per-prefix SNR"
"$PYTHON_BIN" sw/sca_scripts/ASCON/sw/xheep_ASCON_key_recovery_progression_all_sboxes.py \
  --max-traces "$N_TRACES" \
  --traceset-size-k "$TRACESET_SIZE_K" \
  --snr-traces "$N_TRACES" \
  --trace-counts "$PROGRESS_COUNTS" \
  --snr-selection-mode prefix \
  --polarity both \
  --cpa-device cpu \
  --sboxes all

echo "[INFO] Step 6/6: finished"
