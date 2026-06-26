#!/usr/bin/env python3
"""
Capture power traces from the standalone ASCON_init hardware implementations.

The selected CW305 bitstream performs all 12 initialization rounds. Its trigger
is high while the core is busy, and its internal 320-bit state register is
updated with all five state words after the linear layer of every round.

By default, this script captures one million random-nonce traces per selected
S-box for CPA. Use --capture-mode tvla for interleaved fixed-vs-random nonce
traces and first-order TVLA, or --sbox all for every hardware S-box.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import h5py
import numpy as np
from tqdm import tqdm


SBOX_BITSTREAMS = {
    "hw": "cw305_top_standard_comb.bit",
    "lut_ascon": "cw305_top_standard_lut.bit",
    "lut_bilgin": "cw305_top_sbox_bilgin_lut.bit",
    "lut_allouzi": "cw305_top_sbox_allouzi_lut.bit",
    "lut_lu_4": "cw305_top_sbox_lu_4_lut.bit",
    "lut_lu_5": "cw305_top_sbox_lu_5_lut.bit",
    "lut_lu_6": "cw305_top_sbox_lu_6_lut.bit",
    "lut_lu_7": "cw305_top_sbox_lu_7_lut.bit",
}


def find_project_root(start: Path, markers=("fusesoc.conf", ".dojo_root")) -> Path:
    current = start
    while current != current.parent:
        if any((current / marker).exists() for marker in markers):
            return current
        current = current.parent
    raise RuntimeError(
        f"Could not find project root (looked for markers: {markers})."
    )


SCRIPT_DIR = Path(__file__).resolve().parent
DOJO_ROOT = find_project_root(SCRIPT_DIR)
SCA_DIR = DOJO_ROOT / "sw" / "sca_scripts"
ASCON_MODEL_DIR = DOJO_ROOT / "sw" / "ciphers" / "ASCON_init_python"
BITSTREAM_DIR = DOJO_ROOT / "hw" / "fpga" / "bitstream" / "ascon" / "ascon_init"
TRACESET_DIR = DOJO_ROOT / "sw" / "traceset" / "ASCON" / "hw" / "ascon_init"
PLOT_DIR = SCRIPT_DIR / "plot" / "ascon_init"
ASCON_VARIANT = "Ascon-128"
ASCON_IV_HEX = "80400C0600000000"

sys.path.insert(0, str(SCA_DIR))
sys.path.insert(0, str(ASCON_MODEL_DIR))

from CW305_ascon_api import CW305Wrapper  # noqa: E402
from operations_init import ascon_init  # noqa: E402
from pico_api import PS5000aWrapper  # noqa: E402

class BitstreamFile:
    """Compatibility wrapper for ChipWhisperer builds that expect both a path and a context manager."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._fh = None

    def __fspath__(self):
        return str(self.path)

    def __str__(self):
        return str(self.path)

    def __enter__(self):
        self._fh = self.path.open("rb")
        return self._fh

    def __exit__(self, exc_type, exc, tb):
        if self._fh is not None:
            self._fh.close()
            self._fh = None
        return False

def parse_hex_16(value: str) -> bytes:
    try:
        result = bytes.fromhex(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected a hexadecimal value") from error
    if len(result) != 16:
        raise argparse.ArgumentTypeError("expected exactly 16 bytes (32 hex digits)")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture standalone ASCON_init hardware traces for one or more S-boxes."
    )
    parser.add_argument(
        "--sbox",
        nargs="+",
        choices=[*SBOX_BITSTREAMS, "all"],
        default=["hw"],
        help="S-box bitstream(s) to capture. Use 'all' for every implementation.",
    )
    parser.add_argument("--traces", type=int, default=1_000_000, help="Traces per S-box.")
    parser.add_argument(
        "--capture-mode",
        choices=("tvla", "random"),
        default="random",
        help="'tvla' interleaves fixed/random nonces; 'random' uses only random nonces.",
    )
    parser.add_argument(
        "--key",
        type=parse_hex_16,
        default=parse_hex_16("000102030405060708090a0b0c0d0e0f"),
        help="Fixed 128-bit key as 32 hex digits.",
    )
    parser.add_argument(
        "--fixed-nonce",
        type=parse_hex_16,
        default=parse_hex_16("000102030405060708090a0b0c0d0e0f"),
        help="Fixed TVLA nonce as 32 hex digits.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed. The same nonce sequence is reused for every selected S-box.",
    )
    parser.add_argument(
        "--obs-time-us",
        type=float,
        default=3.225,
        help="PicoScope observation window in microseconds.",
    )
    parser.add_argument("--samples", type=int, default=1260, help="Requested samples per trace.")
    parser.add_argument(
        "--wait-time-us",
        type=float,
        default=5.0,
        help="Delay between arming the scope and starting ASCON.",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=1,
        help="Discarded captures before each traceset (useful with AC coupling).",
    )
    parser.add_argument(
        "--validate-every",
        type=int,
        default=1000,
        help="Validate the final 320-bit state every N traces; 0 disables periodic validation.",
    )
    parser.add_argument(
        "--plot-tvla",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Generate a first-order TVLA plot after each TVLA capture.",
    )
    parser.add_argument(
        "--plot-traces",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Generate an overlapped preview plot after each capture.",
    )
    parser.add_argument(
        "--skip-samples",
        type=int,
        default=0,
        help="Ignore this many initial samples in the TVLA report and plot.",
    )
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing HDF5 files.")
    return parser.parse_args()


def normalize_sboxes(requested: list[str]) -> list[str]:
    if "all" in requested:
        if len(requested) != 1:
            raise ValueError("'all' cannot be combined with individual S-box names")
        return list(SBOX_BITSTREAMS)
    return list(dict.fromkeys(requested))


def make_labels(n_traces: int, capture_mode: str, seed: int) -> np.ndarray | None:
    if capture_mode != "tvla":
        return None
    labels = np.ones(n_traces, dtype=np.uint8)
    labels[: n_traces // 2] = 0
    np.random.default_rng(seed).shuffle(labels)
    return labels


def random_nonce(rng: np.random.Generator) -> bytes:
    return rng.integers(0, 256, size=16, dtype=np.uint8).tobytes()


def nonce_analysis_words(nonce: bytes) -> tuple[int, int]:
    """Return [x4, x3], matching the existing generic CPA traceset layout."""
    x3 = int.from_bytes(nonce[:8], byteorder="big")
    x4 = int.from_bytes(nonce[8:], byteorder="big")
    return x4, x3


def analysis_key_hex(key: bytes) -> str:
    """Encode logical x1/x2 so the existing CPA's little-endian loader matches."""
    return (key[:8][::-1] + key[8:][::-1]).hex()


def traceset_path_for(sbox: str, n_traces: int, capture_mode: str) -> Path:
    count = f"{n_traces // 1000}k" if n_traces % 1000 == 0 else str(n_traces)
    suffix = "" if capture_mode == "random" else "_tvla"
    return TRACESET_DIR / f"ascon_init_{sbox}_{count}{suffix}.h5"


def validate_state(cw305: CW305Wrapper, key: bytes, nonce: bytes, sbox: str) -> None:
    measured = bytes(cw305.read_fpga(cw305.REG_CRYPT_STATEOUT, 40))
    expected = ascon_init(key, nonce, ASCON_VARIANT, sbox)
    if measured != expected:
        raise RuntimeError(
            "ASCON state validation failed\n"
            f"  S-box    : {sbox}\n"
            f"  Nonce    : {nonce.hex()}\n"
            f"  Measured : {measured.hex()}\n"
            f"  Expected : {expected.hex()}"
        )


def plot_trace_preview(
    traces: np.ndarray,
    sampling_interval: float,
    sbox: str,
    output_path: Path,
) -> None:
    import matplotlib.pyplot as plt

    time_us = np.arange(traces.shape[1]) * sampling_interval * 1e6
    fig, ax = plt.subplots(figsize=(12, 5))
    for trace in traces:
        ax.plot(time_us, trace, linewidth=0.5, alpha=0.35)
    ax.set_title(f"ASCON_init hardware traces: {sbox}")
    ax.set_xlabel("Time (us)")
    ax.set_ylabel("Voltage (V)")
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(output_path, dpi=300)
    plt.close(fig)


def group_stats(
    traces: h5py.Dataset,
    labels: h5py.Dataset,
    wanted_label: int,
    chunk_rows: int = 4096,
) -> tuple[int, np.ndarray, np.ndarray]:
    count = 0
    total = np.zeros(traces.shape[1], dtype=np.float64)
    total_sq = np.zeros(traces.shape[1], dtype=np.float64)

    for start in range(0, traces.shape[0], chunk_rows):
        end = min(start + chunk_rows, traces.shape[0])
        chunk_labels = np.asarray(labels[start:end])
        selected = np.asarray(traces[start:end], dtype=np.float64)[
            chunk_labels == wanted_label
        ]
        if selected.size == 0:
            continue
        count += selected.shape[0]
        total += selected.sum(axis=0)
        total_sq += np.square(selected).sum(axis=0)

    mean = total / count
    variance = (total_sq - count * np.square(mean)) / (count - 1)
    return count, mean, np.maximum(variance, 0.0)


def plot_first_order_tvla(
    traceset_path: Path,
    output_path: Path,
    skip_samples: int,
) -> None:
    import matplotlib.pyplot as plt

    with h5py.File(traceset_path, "r") as traceset:
        traces = traceset["traces"]
        labels = traceset["labels"]
        sampling_interval = float(traceset.attrs["sampling_interval"])
        sbox = str(traceset.attrs["sbox"])
        n_fixed, mean_fixed, var_fixed = group_stats(traces, labels, 0)
        n_random, mean_random, var_random = group_stats(traces, labels, 1)

    denominator = np.sqrt(var_fixed / n_fixed + var_random / n_random)
    t_score = np.divide(
        mean_fixed - mean_random,
        denominator,
        out=np.zeros_like(denominator),
        where=denominator != 0,
    )

    if skip_samples >= t_score.size:
        raise ValueError("--skip-samples must be smaller than the trace length")

    t_score = t_score[skip_samples:]
    time_us = (
        np.arange(skip_samples, skip_samples + t_score.size)
        * sampling_interval
        * 1e6
    )
    failures = int(np.count_nonzero(np.abs(t_score) > 4.5))
    max_abs_t = float(np.max(np.abs(t_score)))

    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(time_us, t_score, linewidth=0.8)
    ax.axhline(4.5, color="red", linestyle="--", linewidth=0.8)
    ax.axhline(-4.5, color="red", linestyle="--", linewidth=0.8)
    ax.set_title(f"First-order TVLA: ASCON_init {sbox}")
    ax.set_xlabel("Time (us)")
    ax.set_ylabel("Welch t-score")
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(output_path, dpi=300)
    plt.close(fig)

    print(
        f"[TVLA] {sbox}: max |t|={max_abs_t:.3f}, "
        f"{failures} samples exceed |t| > 4.5"
    )
    print(f"[TVLA] Plot saved to {output_path}")


def capture_sbox(
    ps: PS5000aWrapper,
    sbox: str,
    args: argparse.Namespace,
    seed: int,
    labels: np.ndarray | None,
) -> None:
    bitstream_path = BITSTREAM_DIR / SBOX_BITSTREAMS[sbox]
    bitstream = BitstreamFile(bitstream_path)
    traceset_path = traceset_path_for(sbox, args.traces, args.capture_mode)
    sbox_plot_dir = PLOT_DIR / sbox
    sbox_plot_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n================ ASCON_INIT HW CAPTURE: {sbox} ================")
    print(f"  Bitstream          : {bitstream_path}")
    print(f"  Capture mode       : {args.capture_mode}")
    print(f"  Traces             : {args.traces}")
    if labels is not None:
        print(f"  Fixed/random       : {np.count_nonzero(labels == 0)}/{np.count_nonzero(labels == 1)}")
    print(f"  Random seed        : {seed}")
    print(f"  Traceset           : {traceset_path}")
    print("  Trigger interval   : full 12-round initialization")
    print("  Internal state     : all x0..x4 words after each round's linear layer")
    print("================================================================\n")

    cw305 = None
    traceset = None
    completed = 0
    preview = np.empty((min(100, args.traces), ps.get_nSamples()), dtype=np.float32)
    rng = np.random.default_rng(seed)

    try:
        cw305 = CW305Wrapper(ps, bitstream, True, standalone=True)
        if cw305.CW305.bytecount_size != 7:
            raise RuntimeError("Standalone ASCON requires CW305 bytecount_size=7")
        cw305.set_key(args.key)

        # Discard initial captures to let the AC-coupled measurement settle.
        for _ in range(args.warmup):
            cw305.set_nonce(args.fixed_nonce)
            cw305.capture_ascon_trace(wait_time=args.wait_time_us * 1e-6)
            validate_state(cw305, args.key, args.fixed_nonce, sbox)

        n_samples = ps.get_nSamples()
        sampling_interval = ps.get_samplingInterval()
        traceset = h5py.File(traceset_path, "w")
        d_traces = traceset.create_dataset(
            "traces",
            shape=(args.traces, n_samples),
            dtype=np.float32,
            chunks=(min(256, args.traces), n_samples),
        )
        d_nonces = traceset.create_dataset(
            "nonces",
            shape=(args.traces, 2),
            dtype=np.uint64,
            chunks=(min(4096, args.traces), 2),
        )
        d_nonce_bytes = traceset.create_dataset(
            "nonces_bytes",
            shape=(args.traces, 16),
            dtype=np.uint8,
            chunks=(min(4096, args.traces), 16),
        )
        if labels is not None:
            d_labels = traceset.create_dataset(
                "labels",
                data=labels,
                chunks=(min(4096, args.traces),),
            )
            d_labels.attrs["layout"] = "0=fixed nonce, 1=random nonce"

        d_nonces.attrs["layout"] = (
            "nonces[i,0]=x4 and nonces[i,1]=x3; compatible with the existing "
            "generic ASCON CPA scripts"
        )
        d_nonce_bytes.attrs["layout"] = "exact 16 bytes written to REG_CRYPT_NONCEIN"

        traceset.attrs["sbox"] = sbox
        traceset.attrs["bitstream"] = str(bitstream_path)
        traceset.attrs["capture_mode"] = args.capture_mode
        traceset.attrs["implementation"] = "standalone hardware ASCON_init"
        traceset.attrs["variant"] = ASCON_VARIANT
        traceset.attrs["schema"] = "ASCON generic CPA compatible: traces + nonces[x4,x3]"
        traceset.attrs["key_hex"] = analysis_key_hex(args.key)
        traceset.attrs["key_input_hex"] = args.key.hex()
        traceset.attrs["iv_hex"] = ASCON_IV_HEX
        traceset.attrs["fixed_nonce_hex"] = args.fixed_nonce.hex()
        traceset.attrs["cw305_bytecount_size"] = cw305.CW305.bytecount_size
        traceset.attrs["sampling_interval"] = sampling_interval
        traceset.attrs["n_samples"] = n_samples
        traceset.attrs["n_traces"] = args.traces
        traceset.attrs["completed_traces"] = 0
        traceset.attrs["random_seed"] = seed
        traceset.attrs["trigger_interval"] = "full 12-round ASCON initialization"
        traceset.attrs["state_update"] = "all five 64-bit words after the linear layer"

        for index in tqdm(range(args.traces), desc=f"Capturing {sbox}"):
            is_fixed = labels is not None and labels[index] == 0
            nonce = args.fixed_nonce if is_fixed else random_nonce(rng)

            cw305.set_nonce(nonce)
            trace = np.asarray(
                cw305.capture_ascon_trace(wait_time=args.wait_time_us * 1e-6),
                dtype=np.float32,
            )
            if trace.shape != (n_samples,):
                raise RuntimeError(
                    f"Unexpected trace shape {trace.shape}; expected ({n_samples},)"
                )

            d_traces[index] = trace
            d_nonces[index] = nonce_analysis_words(nonce)
            d_nonce_bytes[index] = np.frombuffer(nonce, dtype=np.uint8)
            if index < preview.shape[0]:
                preview[index] = trace

            validate_period = args.validate_every
            if validate_period > 0 and (
                index == 0 or (index + 1) % validate_period == 0
            ):
                validate_state(cw305, args.key, nonce, sbox)

            completed = index + 1
            if completed % 1000 == 0 or completed == args.traces:
                traceset.attrs["completed_traces"] = completed
                traceset.flush()

        traceset.close()
        traceset = None
        print(f"[CAPTURE] Saved {completed} traces to {traceset_path}")

        if args.plot_traces:
            preview_path = sbox_plot_dir / f"ascon_init_{sbox}_{args.traces}_traces.png"
            plot_trace_preview(preview, sampling_interval, sbox, preview_path)
            print(f"[PLOT] Trace preview saved to {preview_path}")

        if args.plot_tvla and labels is not None:
            tvla_path = sbox_plot_dir / f"ascon_init_{sbox}_{args.traces}_tvla.png"
            plot_first_order_tvla(traceset_path, tvla_path, args.skip_samples)
    finally:
        if traceset is not None:
            traceset.attrs["completed_traces"] = completed
            traceset.close()
        if cw305 is not None:
            cw305.dis()


def main() -> None:
    args = parse_args()
    if args.traces < 2:
        raise ValueError("--traces must be at least 2")
    if args.capture_mode == "tvla" and args.traces < 4:
        raise ValueError("TVLA capture requires at least 4 traces")
    if args.samples < 1:
        raise ValueError("--samples must be positive")
    if args.obs_time_us <= 0:
        raise ValueError("--obs-time-us must be positive")
    if args.wait_time_us < 0:
        raise ValueError("--wait-time-us cannot be negative")
    if args.warmup < 0 or args.validate_every < 0 or args.skip_samples < 0:
        raise ValueError("warmup, validate-every, and skip-samples cannot be negative")
    if args.seed is not None and args.seed < 0:
        raise ValueError("--seed cannot be negative")

    sboxes = normalize_sboxes(args.sbox)
    seed = args.seed if args.seed is not None else int(time.time_ns() & 0xFFFFFFFF)
    labels = make_labels(args.traces, args.capture_mode, seed)

    TRACESET_DIR.mkdir(parents=True, exist_ok=True)
    PLOT_DIR.mkdir(parents=True, exist_ok=True)

    for sbox in sboxes:
        bitstream_path = BITSTREAM_DIR / SBOX_BITSTREAMS[sbox]
        traceset_path = traceset_path_for(sbox, args.traces, args.capture_mode)
        if not bitstream_path.exists():
            raise FileNotFoundError(f"Missing bitstream: {bitstream_path}")
        if traceset_path.exists() and not args.overwrite:
            raise FileExistsError(
                f"Traceset already exists: {traceset_path}. "
                "Use --overwrite to replace it."
            )

    ps = PS5000aWrapper()
    try:
        ps.get_unitInfo()
        ps.scope_setup(obs_time=args.obs_time_us * 1e-6, nSamples=args.samples)
        ps.get_scopeSettings()
        for sbox in sboxes:
            capture_sbox(ps, sbox, args, seed, labels)
    finally:
        ps.dis()


if __name__ == "__main__":
    main()
