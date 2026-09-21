#!/usr/bin/env python3
"""Run ASCON CPA traces against cross S-box leakage models and write tables."""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from pathlib import Path


SBOXES_SW = (
    "lut_ascon",
    "lut_bilgin",
    "lut_allouzi",
    "lut_lu_4",
    "lut_lu_5",
    "lut_lu_6",
    "lut_lu_7",
)
SBOXES_HW = ("hw",) + SBOXES_SW


def find_project_root(start: Path, markers=("fusesoc.conf", ".dojo_root")) -> Path:
    current = start
    while current != current.parent:
        if any((current / marker).exists() for marker in markers):
            return current
        current = current.parent
    raise RuntimeError(f"Could not find project root from {start}")


SCRIPT_DIR = Path(__file__).resolve().parent
DOJO_ROOT = find_project_root(SCRIPT_DIR)
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "cross_leakage_model_cpa_table"


def _format_trace_count_tag(trace_count: int) -> str:
    trace_count = int(trace_count)
    if trace_count % 1000 == 0:
        return f"{trace_count // 1000}k"
    return str(trace_count)


def _analysis_name(trace_sbox: str, model_sbox: str) -> str:
    if trace_sbox == model_sbox:
        return trace_sbox
    return f"{trace_sbox}__model_{model_sbox}"


def _parse_list(value: str | None, choices) -> list[str]:
    if value in (None, "", "all"):
        return list(choices)
    selected = [part.strip() for part in value.split(",") if part.strip()]
    unknown = [name for name in selected if name not in choices]
    if unknown:
        raise ValueError(f"Unknown S-box names: {unknown}. Choices: {list(choices)}")
    return selected


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _read_result(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _snr_cache_ready(base_cache: Path, analysis_name: str, n_traces: int) -> bool:
    tag = _format_trace_count_tag(n_traces)
    cache_dir = base_cache / analysis_name
    ranked_file = cache_dir / f"snr_ranked_{analysis_name}_{tag}.h5"
    traces_file = cache_dir / f"snr_traces_{analysis_name}_{tag}.h5"
    return ranked_file.exists() and traces_file.exists()


def _row_from_result(record: dict, result: dict) -> dict:
    k0_correct = result.get("k0_correct_recovered_count")
    k1_correct = result.get("k1_correct_recovered_count")
    if k0_correct is None:
        k0_correct = 0
    if k1_correct is None:
        k1_correct = 0
    correct_total = int(k0_correct) + int(k1_correct)

    return {
        **record,
        "n_traces_used": result.get("n_traces"),
        "k0_recovered_count": result.get("k0_recovered_count"),
        "k1_recovered_count": result.get("k1_recovered_count"),
        "k0_correct_recovered_count": result.get("k0_correct_recovered_count"),
        "k1_correct_recovered_count": result.get("k1_correct_recovered_count"),
        "correct_recovered_total": correct_total,
        "full_key_match": result.get("full_key_match"),
    }


def _write_long_csv(path: Path, rows: list[dict]) -> None:
    columns = (
        "implementation",
        "trace_sbox",
        "leakage_model_sbox",
        "analysis_name",
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
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column) for column in columns})
    tmp.replace(path)


def _write_matrix_csv(path: Path, rows: list[dict], trace_sboxes: list[str], model_sboxes: list[str]) -> None:
    by_pair = {
        (row["trace_sbox"], row["leakage_model_sbox"]): row
        for row in rows
        if row.get("status") in {"success", "skipped_existing"}
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["trace_sbox \\ leakage_model_sbox", *model_sboxes])
        for trace_sbox in trace_sboxes:
            values = []
            for model_sbox in model_sboxes:
                row = by_pair.get((trace_sbox, model_sbox), {})
                value = row.get("correct_recovered_total")
                values.append("" if value is None else value)
            writer.writerow([trace_sbox, *values])
    tmp.replace(path)


def _write_markdown(path: Path, rows: list[dict], trace_sboxes: list[str], model_sboxes: list[str]) -> None:
    by_pair = {
        (row["trace_sbox"], row["leakage_model_sbox"]): row
        for row in rows
        if row.get("status") in {"success", "skipped_existing"}
    }
    lines = [
        "# ASCON Cross Leakage-Model CPA Table",
        "",
        "Entries are `k0_correct + k1_correct` recovered bits out of 128.",
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


def _implementation_config(implementation: str):
    if implementation == "sw":
        return {
            "sboxes": SBOXES_SW,
            "snr_script": DOJO_ROOT / "sw/sca_scripts/ASCON/sw/xheep_ASCON_snr.py",
            "cpa_script": DOJO_ROOT / "sw/sca_scripts/ASCON/sw/xheep_ASCON_cpa_generic_all_registers.py",
            "base_cache": DOJO_ROOT / "sw/sca_scripts/ASCON/sw/cache/cross_leakage_model_cpa",
        }
    if implementation == "hw":
        return {
            "sboxes": SBOXES_HW,
            "snr_script": DOJO_ROOT / "sw/sca_scripts/ASCON/hw/ascon_init_ASCON_snr.py",
            "cpa_script": DOJO_ROOT / "sw/sca_scripts/ASCON/hw/ascon_init_ASCON_cpa_generic_all_registers.py",
            "base_cache": DOJO_ROOT / "sw/sca_scripts/ASCON/hw/cache/ascon_init/cross_leakage_model_cpa",
        }
    raise ValueError(f"Unsupported implementation: {implementation}")


def _run_one(
    *,
    implementation: str,
    trace_sbox: str,
    model_sbox: str,
    n_traces: int,
    traceset_size_k: int,
    polarity: str,
    output_dir: Path,
    python_bin: str,
    dry_run: bool,
    skip_existing: bool,
    analysis_max_time_us: float,
) -> dict:
    config = _implementation_config(implementation)
    analysis_name = _analysis_name(trace_sbox, model_sbox)
    run_dir = output_dir / implementation / analysis_name / polarity
    run_dir.mkdir(parents=True, exist_ok=True)
    snr_log_file = run_dir / "snr.log"
    cpa_log_file = run_dir / "cpa.log"
    result_file = run_dir / "result.json"

    record = {
        "implementation": implementation,
        "trace_sbox": trace_sbox,
        "leakage_model_sbox": model_sbox,
        "analysis_name": analysis_name,
        "snr_log_file": str(snr_log_file),
        "cpa_log_file": str(cpa_log_file),
        "result_file": str(result_file),
    }

    if skip_existing and result_file.exists():
        result = _read_result(result_file)
        return _row_from_result({**record, "status": "skipped_existing", "exit_code": 0, "elapsed_seconds": 0.0}, result)

    if dry_run:
        return {
            **record,
            "status": "dry_run",
            "exit_code": None,
            "elapsed_seconds": 0.0,
            "n_traces_used": n_traces,
        }

    env = os.environ.copy()
    env.update(
        {
            "ASCON_SBOX_TYPE": trace_sbox,
            "ASCON_TRACE_SBOX_TYPE": trace_sbox,
            "ASCON_LEAKAGE_MODEL_SBOX": model_sbox,
            "ASCON_CACHE_DIR": str(config["base_cache"]),
            "ASCON_N_TRC": str(n_traces),
            "ASCON_TRACESET_SIZE_K": str(traceset_size_k),
            "ASCON_CPA_DEVICE": "cpu",
            "ASCON_LEAKAGE_POLARITY": polarity,
            "ASCON_SINGLE_RUN": "1",
            "ASCON_RUN_RESULT_FILE": str(result_file),
            "ASCON_PROGRESS_BARS": "0",
            "MPLCONFIGDIR": env.get("MPLCONFIGDIR", "/tmp/matplotlib-ascon"),
            "PYTHONUNBUFFERED": "1",
        }
    )
    if implementation == "hw":
        env["ASCON_ANALYSIS_MAX_TIME_US"] = str(float(analysis_max_time_us))

    snr_cmd = [
        python_bin,
        str(config["snr_script"]),
        "--sbox",
        trace_sbox,
        "--trace-sbox",
        trace_sbox,
        "--leakage-model-sbox",
        model_sbox,
        "--n-traces",
        str(n_traces),
        "--traceset-size-k",
        str(traceset_size_k),
        "--cache-dir",
        str(config["base_cache"]),
    ]
    if implementation == "hw":
        snr_cmd.extend(["--analysis-max-time-us", str(float(analysis_max_time_us))])

    cpa_cmd = [python_bin, str(config["cpa_script"])]

    started = time.monotonic()
    if _snr_cache_ready(config["base_cache"], analysis_name, n_traces):
        snr_log_file.write_text(
            f"Reusing existing SNR cache for {analysis_name}\n",
            encoding="utf-8",
        )
    else:
        with snr_log_file.open("w", encoding="utf-8") as log_handle:
            snr_completed = subprocess.run(
                snr_cmd,
                cwd=DOJO_ROOT,
                env=env,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                check=False,
            )
        if snr_completed.returncode != 0:
            elapsed = time.monotonic() - started
            return {
                **record,
                "status": "snr_failed",
                "exit_code": int(snr_completed.returncode),
                "elapsed_seconds": elapsed,
            }

    with cpa_log_file.open("w", encoding="utf-8") as log_handle:
        cpa_completed = subprocess.run(
            cpa_cmd,
            cwd=DOJO_ROOT,
            env=env,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            check=False,
        )

    elapsed = time.monotonic() - started
    if cpa_completed.returncode != 0:
        return {
            **record,
            "status": "cpa_failed",
            "exit_code": int(cpa_completed.returncode),
            "elapsed_seconds": elapsed,
        }
    if not result_file.exists():
        return {
            **record,
            "status": "missing_result",
            "exit_code": 0,
            "elapsed_seconds": elapsed,
        }

    result = _read_result(result_file)
    return _row_from_result(
        {**record, "status": "success", "exit_code": 0, "elapsed_seconds": elapsed},
        result,
    )


def _build_arg_parser():
    parser = argparse.ArgumentParser(
        description="Run full ASCON CPA with each trace S-box against each leakage-model S-box.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--implementation",
        choices=["sw", "hw", "both"],
        default=os.environ.get("ASCON_CROSS_IMPLEMENTATION", "both"),
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
        default=os.environ.get("ASCON_LEAKAGE_POLARITY", "negative"),
        help="Leakage polarity for CPA.",
    )
    parser.add_argument(
        "--analysis-max-time-us",
        type=float,
        default=float(os.environ.get("ASCON_ANALYSIS_MAX_TIME_US", "1.5")),
        help="HW trace sample cutoff. Use 0 for full trace.",
    )
    parser.add_argument("--python-bin", default=os.environ.get("PYTHON_BIN", sys.executable))
    parser.add_argument("--output-dir", default=os.environ.get("ASCON_CROSS_OUTPUT_DIR"))
    parser.add_argument("--dry-run", action="store_true", help="Write intended matrix without running jobs.")
    parser.add_argument("--no-skip-existing", action="store_true", help="Re-run even when result.json exists.")
    return parser


def main() -> int:
    args = _build_arg_parser().parse_args()
    implementations = ["sw", "hw"] if args.implementation == "both" else [args.implementation]
    output_dir = Path(args.output_dir) if args.output_dir else DEFAULT_OUTPUT_DIR
    if not output_dir.is_absolute():
        output_dir = (DOJO_ROOT / output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    all_rows = []
    manifest = {
        "n_traces": int(args.n_traces),
        "traceset_size_k": int(args.traceset_size_k),
        "polarity": args.polarity,
        "trace_selection": "prefix-from-start",
        "dry_run": bool(args.dry_run),
        "implementations": implementations,
        "matrices": {},
    }

    for implementation in implementations:
        choices = _implementation_config(implementation)["sboxes"]
        trace_sboxes = _parse_list(args.trace_sboxes, choices)
        model_sboxes = _parse_list(args.model_sboxes, choices)
        rows = []
        total = len(trace_sboxes) * len(model_sboxes)

        print(f"[INFO] {implementation}: {len(trace_sboxes)} trace S-boxes x {len(model_sboxes)} models")
        for index, (trace_sbox, model_sbox) in enumerate(
            ((t, m) for t in trace_sboxes for m in model_sboxes),
            start=1,
        ):
            print(
                f"[INFO] {implementation} [{index}/{total}] "
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
            rows.append(row)
            all_rows.append(row)
            _write_long_csv(output_dir / "cross_leakage_model_cpa_long.csv", all_rows)

        matrix_csv = output_dir / f"cross_leakage_model_cpa_matrix_{implementation}.csv"
        matrix_md = output_dir / f"cross_leakage_model_cpa_matrix_{implementation}.md"
        _write_matrix_csv(matrix_csv, rows, trace_sboxes, model_sboxes)
        _write_markdown(matrix_md, rows, trace_sboxes, model_sboxes)
        manifest["matrices"][implementation] = {
            "trace_sboxes": trace_sboxes,
            "model_sboxes": model_sboxes,
            "matrix_csv": str(matrix_csv),
            "matrix_markdown": str(matrix_md),
        }

    _write_json(output_dir / "manifest.json", manifest)
    print(f"[INFO] Wrote cross-model CPA tables to: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
