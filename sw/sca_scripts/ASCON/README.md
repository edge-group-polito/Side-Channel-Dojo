# ASCON SNR Analysis

This folder contains the ASCON software and hardware SNR scripts used to rank
and compare S-box leakage.

## Scripts

SW SNR cache generation:

- `sw/xheep_ASCON_snr.py`

HW SNR cache generation:

- `hw/ascon_init_ASCON_snr.py`

SNR comparison:

- `sw/xheep_ASCON_snr_compare.py`
- `hw/ascon_init_ASCON_snr_compare.py`

Key-recovery progression:

- `sw/xheep_ASCON_key_recovery_progression_all_sboxes.py`
- `hw/ascon_init_ASCON_key_recovery_progression_all_sboxes.py`

The comparison script loads `snr_traces_*.h5` files for multiple S-boxes and
generates a compact recommended plot/table set by default. Extra diagnostic
plots are available through normal command-line arguments.

## Compute SW SNR Caches

Run one SW S-box:

```bash
python3 sw/sca_scripts/ASCON/sw/xheep_ASCON_snr.py \
  --sbox lut_ascon \
  --n-traces 1000000 \
  --traceset-size-k 1000 \
  --device cpu \
  --chunk-size 10000 \
  --save-ranked \
  --save-traces \
  --cache-dir sw/sca_scripts/ASCON/sw/cache
```

Run all SW S-boxes:

```bash
for sbox in lut_ascon lut_bilgin lut_allouzi lut_lu_4 lut_lu_5 lut_lu_6 lut_lu_7; do
  python3 sw/sca_scripts/ASCON/sw/xheep_ASCON_snr.py \
    --sbox "$sbox" \
    --n-traces 1000000 \
    --traceset-size-k 1000 \
    --device cpu \
    --chunk-size 10000 \
    --save-ranked \
    --save-traces \
    --cache-dir sw/sca_scripts/ASCON/sw/cache
done
```

## Compute HW SNR Caches

Run one HW S-box:

```bash
python3 sw/sca_scripts/ASCON/hw/ascon_init_ASCON_snr.py \
  --sbox hw \
  --n-traces 1000000 \
  --traceset-size-k 1000 \
  --analysis-max-time-us 1.5 \
  --device cpu \
  --chunk-size 10000 \
  --save-ranked \
  --save-traces
```

Run all HW trace S-boxes, including the combinational `hw` case:

```bash
for sbox in hw lut_ascon lut_bilgin lut_allouzi lut_lu_4 lut_lu_5 lut_lu_6 lut_lu_7; do
  python3 sw/sca_scripts/ASCON/hw/ascon_init_ASCON_snr.py \
    --sbox "$sbox" \
    --n-traces 1000000 \
    --traceset-size-k 1000 \
    --analysis-max-time-us 1.5 \
    --device cpu \
    --chunk-size 10000 \
    --save-ranked \
    --save-traces
done
```

Use `--n-traces` for the prefix length used in the SNR calculation. Use
`--traceset-size-k` for the trace filename tag. For example, to compute SNR on
the first `100000` traces from a `*_1000k.h5` file, set `--n-traces 100000` and
keep `--traceset-size-k 1000`.

## Compare SNR Caches

SW comparison:

```bash
python3 sw/sca_scripts/ASCON/sw/xheep_ASCON_snr_compare.py \
  --implementation sw \
  --n-traces 1000000 \
  --tag 1000k
```

HW comparison through the HW entry point:

```bash
python3 sw/sca_scripts/ASCON/hw/ascon_init_ASCON_snr_compare.py \
  --n-traces 1000000 \
  --tag 1000k
```

Useful comparison arguments:

- `--sboxes lut_ascon,lut_bilgin`: compare only selected S-boxes.
- `--out-dir <path>`: choose the output plot/table directory.
- `--plot-set main`: default compact figure set.
- `--plot-set full`: include secondary and appendix diagnostics.
- `--include-secondary`: add CDF, mean trace, and integrated CCDF.
- `--include-appendix`: add dense diagnostics such as PDF/KDE, per-register
  plots, top-bit bar plots, dashboards, and log boxplots.
- `--thresholds 0.001,0.005,0.01,0.02,0.05`: choose SNR thresholds for the
  summary table.
- `--no-include-comb`: for HW comparison, exclude the combinational `hw` S-box
  when `--sboxes all`.

## Key-Recovery Progression

The progression script measures recovered key bits over prefix trace counts.
Use `--snr-selection-mode prefix` to rank targets with an SNR cache computed on
the same prefix length as the CPA point.

SW progression:

```bash
python3 sw/sca_scripts/ASCON/sw/xheep_ASCON_key_recovery_progression_all_sboxes.py \
  --max-traces 1000000 \
  --traceset-size-k 1000 \
  --snr-traces 1000000 \
  --trace-counts 100,1000,5000,10000,50000,100000,500000,1000000 \
  --snr-selection-mode prefix \
  --polarity both \
  --plot-x-scale log \
  --cpa-device cpu \
  --sboxes all
```

HW progression:

```bash
python3 sw/sca_scripts/ASCON/hw/ascon_init_ASCON_key_recovery_progression_all_sboxes.py \
  --max-traces 1000000 \
  --traceset-size-k 1000 \
  --snr-traces 1000000 \
  --trace-counts 100,1000,5000,10000,50000,100000,500000,1000000 \
  --snr-selection-mode prefix \
  --polarity both \
  --analysis-max-time-us 1.5 \
  --plot-x-scale log \
  --cpa-device cpu \
  --sboxes all
```

The main outputs are:

- SW combined values:
  `sw/sca_scripts/ASCON/sw/cache/key_recovery_progression_all_sboxes/prefix/`
- SW plots:
  `sw/sca_scripts/ASCON/sw/plot/key_recovery_progression_all_sboxes/prefix/`
- HW combined values:
  `sw/sca_scripts/ASCON/hw/cache/ascon_init/key_recovery_progression_all_sboxes/prefix/`
- HW plots:
  `sw/sca_scripts/ASCON/hw/plot/ascon_init_key_recovery_progression_all_sboxes/prefix/`

Progression CSV/JSON fields use:

- `known_key_bits_count`: all recovered bits, whether correct or wrong.
- `correct_key_bits_count`: recovered bits that match the expected key.
- `wrong_recovered_key_bits_count`: recovered bits that are wrong.

Recommended plots include:

- `ASCON_generic_correct_recovered_key_bits_all_sboxes_*`: correct recovered
  bits on a full y-axis.
- `ASCON_generic_correct_recovered_key_bits_all_sboxes_*_zoom_96_128`:
  SW correct recovered bits zoomed to y=96..128 with headroom above 128.
- `ASCON_generic_correct_recovered_key_bits_all_sboxes_*_zoom_64_128`:
  HW correct recovered bits zoomed to y=64..128 with headroom above 128.
- `ASCON_generic_correct_vs_recovered_key_bits_all_sboxes_*`: solid lines show
  correct recovered bits, dashed lines show all recovered bits. The vertical
  gap is the number of wrong recovered bits.
- `ASCON_generic_k0_k1_correct_recovered_bits_all_sboxes_*`: separate k0/k1
  correct-bit progression.

Useful progression options:

- `--trace-counts 100,1000,...`: explicit prefix counts.
- `--plot-x-scale log`: logarithmic trace-count axis.
- `--plot-only`: load an existing combined JSON and regenerate CSV/JSON/plots
  without rerunning CPA.
- `--plot-input-json <path>`: choose the combined JSON for `--plot-only`.
- `--drop-trace-counts 10`: remove selected trace-count rows during
  `--plot-only`.
- `--replace-result-json <path>`: merge one rerun per-S-box JSON into an
  existing combined JSON during `--plot-only`.

Example SW plot-only replot:

```bash
python3 sw/sca_scripts/ASCON/sw/xheep_ASCON_key_recovery_progression_all_sboxes.py \
  --plot-only \
  --plot-input-json sw/sca_scripts/ASCON/sw/cache/key_recovery_progression_all_sboxes/prefix/ASCON_generic_key_recovery_progression_all_sboxes_1000k_prefix_snr.json \
  --snr-selection-mode prefix \
  --max-traces 1000000 \
  --plot-x-scale log
```

Example HW plot-only replot:

```bash
python3 sw/sca_scripts/ASCON/hw/ascon_init_ASCON_key_recovery_progression_all_sboxes.py \
  --plot-only \
  --plot-input-json sw/sca_scripts/ASCON/hw/cache/ascon_init/key_recovery_progression_all_sboxes/prefix/ASCON_generic_key_recovery_progression_all_sboxes_1000k_prefix_snr.json \
  --snr-selection-mode prefix \
  --max-traces 1000000 \
  --analysis-max-time-us 1.5 \
  --plot-x-scale log
```

Example rerun of one SW S-box/count and merge back into the combined result:

```bash
python3 sw/sca_scripts/ASCON/sw/xheep_ASCON_snr.py \
  --sbox lut_ascon \
  --trace-sbox lut_ascon \
  --leakage-model-sbox lut_ascon \
  --n-traces 10000 \
  --traceset-size-k 1000 \
  --cache-dir sw/sca_scripts/ASCON/sw/cache \
  --chunk-size 10000 \
  --device cpu

python3 sw/sca_scripts/ASCON/sw/xheep_ASCON_key_recovery_progression_all_sboxes.py \
  --max-traces 10000 \
  --traceset-size-k 1000 \
  --snr-traces 10000 \
  --trace-counts 10000 \
  --snr-selection-mode prefix \
  --polarity both \
  --plot-x-scale log \
  --cpa-device cpu \
  --sboxes lut_ascon \
  --no-save-plots

python3 sw/sca_scripts/ASCON/sw/xheep_ASCON_key_recovery_progression_all_sboxes.py \
  --plot-only \
  --plot-input-json sw/sca_scripts/ASCON/sw/cache/key_recovery_progression_all_sboxes/prefix/ASCON_generic_key_recovery_progression_all_sboxes_1000k_prefix_snr.json \
  --replace-result-json sw/sca_scripts/ASCON/sw/cache/lut_ascon/ASCON_generic_key_recovery_progression_lut_ascon_10k_prefix_snr.json \
  --snr-selection-mode prefix \
  --max-traces 1000000 \
  --plot-x-scale log
```

## Main Outputs

`snr_main_summary_metrics.csv` is the compact table for reports. For each S-box
it reports:

- `max_peak_snr`: the strongest single leakage point.
- `mean_peak_snr`: broad average leakage across all 320 state bits.
- `median_peak_snr`: robust typical leakage.
- `mean_top5_peak_snr`: average leakage of the five most dangerous bits.
- `mean_top10_peak_snr`: average leakage of the ten most dangerous bits.
- `max_integrated_snr`: strongest accumulated leakage over time.
- `count_peak_snr_gt_<theta>`: number of target bits whose peak SNR exceeds
  threshold `theta`.

`snr_summary_metrics.csv` keeps the wider global and per-register diagnostic
metrics. `snr_target_level_metrics.csv` lists every target bit with its peak
SNR, peak sample index, and integrated SNR.

## Plot Interpretation

`figure1_peak_snr_heatmap.png` shows `PeakSNR[register, bit] = max_t SNR`.
Bright cells are dangerous bits. This is the clearest figure for showing which
ASCON state bits leak.

`main_peak_snr_summary_bars.png` summarizes worst-case, typical, top-k, and
integrated leakage. Use it to compare implementations without relying on only
one outlier.

`figure2_peak_snr_ccdf.png` shows `P(PeakSNR > x)`. Lower curves are better.
A long tail means a few bits leak strongly even if most bits are quiet.

`figure3_max_snr_trace.png` shows `max_{register,bit} SNR[register,bit,t]`.
It tells when the strongest leakage appears in the trace.

`figure4_integrated_snr_clipped_p99.png` shows the distribution of
`sum_t SNR[register,bit,t]`, clipped at P99. Peak SNR shows the strongest
instant; integrated SNR shows whether leakage is spread across time. The P99
clip prevents a few outliers from compressing the useful part of the plot.

Secondary plots:

- `peak_snr_cdf.png`: fraction of target bits below each peak-SNR value.
- `mean_snr_trace.png`: average leakage timing over all 320 target bits.
- `integrated_snr_ccdf.png`: tail behavior of integrated leakage.

Appendix plots:

- PDF/KDE plots are useful as diagnostics, but they are not recommended as core
  figures because all `(register, bit, time)` SNR samples are dominated by
  near-zero values.
- Per-register and top-bit plots are useful when explaining one implementation
  in detail.

## References

- Mangard, Oswald, and Popp, *Power Analysis Attacks: Revealing the Secrets of
  Smart Cards*, Springer, 2007. DOI:
  https://doi.org/10.1007/978-0-387-38162-6
- Kocher, Jaffe, and Jun, "Differential Power Analysis", CRYPTO 1999. DOI:
  https://doi.org/10.1007/3-540-48405-1_25
- Kiaei et al., "Gate-Level Side-Channel Leakage Assessment with Architecture
  Correlation Analysis", arXiv:2204.11972, 2022. DOI:
  https://doi.org/10.48550/arXiv.2204.11972
