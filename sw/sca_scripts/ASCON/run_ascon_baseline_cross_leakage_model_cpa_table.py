#!/usr/bin/env python3
"""Run cross leakage-model CPA with the normal baseline recovery policy."""

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

from run_ascon_cross_leakage_model_cpa_table import (
    DOJO_ROOT,
    SCRIPT_DIR,
    _implementation_config,
    _parse_list,
    _run_one,
    _write_json,
    _write_matrix_csv,
)


DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "baseline_cross_leakage_model_cpa_table"


def _write_markdown(path: Path, rows: list[dict], trace_sboxes: list[str], model_sboxes: list[str]) -> None:
    by_pair = {
        (row["trace_sbox"], row["leakage_model_sbox"]): row
        for row in rows
        if row.get("status") in {"success", "skipped_existing"}
    }
    lines = [
        "# ASCON Baseline Cross Leakage-Model CPA Table",
        "",
        "Entries are `k0_correct + k1_correct` recovered bits out of 128.",
        "",
        "CPA policy: raw SNR order, generic complement-equivalence recovery, no equivalent-dependency filtering.",
        "",
        "| Trace S-box \\ Leakage model | " + " | ".join(model_sboxes) + " |",
        "|---|" + "|".join("---" for _ in model_sboxes) + "|",
    ]
    for trace_sbox in trace_sboxes:
        values = []
        for model_sbox in model_sboxes:
            row = by_pair.get((trace_sbox, model_sbox), {})
            value = row.get("correct_recovered_total")
            values.append("" if value is None else str(value))
        lines.append(f"| {trace_sbox} | " + " | ".join(values) + " |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_long_csv_with_policy(path: Path, rows: list[dict]) -> None:
    columns = (
        "implementation",
        "trace_sbox",
        "leakage_model_sbox",
        "analysis_name",
        "cpa_recovery_policy",
        "polarity",
        "status",
        "exit_code",
        "elapsed_seconds",
        "n_traces_used",
        "k0_recovered_count",
        "k1_recovered_count",
        "k0_correct_recovered_count",
        "k1_correct_recovered_count",
        "correct_recovered_total",
        "full_key_match",
        "snr_log_file",
        "cpa_log_file",
        "result_file",
    )
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column) for column in columns})
    temporary.replace(path)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run ASCON cross leakage-model CPA while keeping the normal "
            "baseline CPA recovery policy fixed."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--implementation",
        choices=["sw", "hw", "both"],
        default=os.environ.get("ASCON_BASELINE_CROSS_IMPLEMENTATION", "both"),
        help="Which implementation matrix to run.",
    )
    parser.add_argument("--trace-sboxes", default=os.environ.get("ASCON_CROSS_TRACE_SBOXES", "all"))
    parser.add_argument("--model-sboxes", default=os.environ.get("ASCON_CROSS_MODEL_SBOXES", "all"))
    parser.add_argument("--n-traces", type=int, default=int(os.environ.get("ASCON_N_TRC", "1000000")))
    parser.add_argument(
        "--traceset-size-k",
        type=int,
        default=int(os.environ.get("ASCON_TRACESET_SIZE_K", "1000")),
    )
    parser.add_argument(
        "--polarity",
        choices=["negative", "positive", "both"],
        default=os.environ.get("ASCON_LEAKAGE_POLARITY", "both"),
        help="Leakage polarity for CPA. Baseline cross mode defaults to both.",
    )
    parser.add_argument(
        "--analysis-max-time-us",
        type=float,
        default=float(os.environ.get("ASCON_ANALYSIS_MAX_TIME_US", "1.5")),
        help="HW trace sample cutoff. Use 0 for full trace.",
    )
    parser.add_argument("--python-bin", default=os.environ.get("PYTHON_BIN", sys.executable))
    parser.add_argument("--output-dir", default=os.environ.get("ASCON_BASELINE_CROSS_OUTPUT_DIR"))
    parser.add_argument("--dry-run", action="store_true", help="Write intended matrix without running jobs.")
    parser.add_argument("--no-skip-existing", action="store_true", help="Re-run even when result.json exists.")
    return parser


def main() -> int:
    args = _build_arg_parser().parse_args()
    output_dir = Path(args.output_dir) if args.output_dir else DEFAULT_OUTPUT_DIR
    if not output_dir.is_absolute():
        output_dir = (DOJO_ROOT / output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    implementations = ["sw", "hw"] if args.implementation == "both" else [args.implementation]
    all_rows = []
    manifest = {
        "implementations": implementations,
        "n_traces": int(args.n_traces),
        "traceset_size_k": int(args.traceset_size_k),
        "polarity": args.polarity,
        "cpa_recovery_policy": "baseline",
        "trace_selection": "prefix-from-start",
        "dry_run": bool(args.dry_run),
        "matrices": {},
    }

    previous_policy = os.environ.get("ASCON_CPA_POLICY")
    os.environ["ASCON_CPA_POLICY"] = "baseline"
    try:
        for implementation in implementations:
            choices = _implementation_config(implementation)["sboxes"]
            trace_sboxes = _parse_list(args.trace_sboxes, choices)
            model_sboxes = _parse_list(args.model_sboxes, choices)
            total = len(trace_sboxes) * len(model_sboxes)
            rows = []
            print(
                f"[INFO] {implementation} baseline: {len(trace_sboxes)} "
                f"trace S-boxes x {len(model_sboxes)} models"
            )
            for index, (trace_sbox, model_sbox) in enumerate(
                ((t, m) for t in trace_sboxes for m in model_sboxes),
                start=1,
            ):
                print(
                    f"[INFO] {implementation} baseline [{index}/{total}] "
                    f"trace={trace_sbox} model={model_sbox}",
                    flush=True,
                )
                row = _run_one(
                    implementation=implementation,
                    trace_sbox=trace_sbox,
                    model_sbox=model_sbox,
                    n_traces=int(args.n_traces),
                    traceset_size_k=int(args.traceset_size_k),
                    polarity=args.polarity,
                    output_dir=output_dir,
                    python_bin=args.python_bin,
                    dry_run=bool(args.dry_run),
                    skip_existing=not bool(args.no_skip_existing),
                    analysis_max_time_us=float(args.analysis_max_time_us),
                )
                row["cpa_recovery_policy"] = "baseline"
                row["polarity"] = args.polarity
                rows.append(row)
                all_rows.append(row)
                _write_long_csv_with_policy(
                    output_dir / "baseline_cross_leakage_model_cpa_long.csv",
                    all_rows,
                )

            matrix_csv = output_dir / f"baseline_cross_leakage_model_cpa_matrix_{implementation}.csv"
            matrix_md = output_dir / f"baseline_cross_leakage_model_cpa_matrix_{implementation}.md"
            _write_matrix_csv(matrix_csv, rows, trace_sboxes, model_sboxes)
            _write_markdown(matrix_md, rows, trace_sboxes, model_sboxes)
            manifest["matrices"][implementation] = {
                "trace_sboxes": trace_sboxes,
                "model_sboxes": model_sboxes,
                "matrix_csv": str(matrix_csv),
                "matrix_markdown": str(matrix_md),
            }
    finally:
        if previous_policy is None:
            os.environ.pop("ASCON_CPA_POLICY", None)
        else:
            os.environ["ASCON_CPA_POLICY"] = previous_policy

    _write_json(output_dir / "manifest.json", manifest)
    print(f"[INFO] Wrote baseline cross-model CPA table to: {output_dir}")

    return 1 if any(row.get("status") not in {"success", "skipped_existing", "dry_run"} for row in all_rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
