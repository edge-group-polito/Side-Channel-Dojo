#!/usr/bin/env python3
"""
ASCON HW trace capture script (CW305 + X-HEEP + PicoScope).

- Detects the Side-Channel-Dojo project root (DOJO_ROOT).
- Programs the FPGA bitstream and X-HEEP firmware.
- Captures n_trc power traces with PicoScope.
- Updates the ASCON nonce on each iteration using ascon_first_round().
- Stores traces + nonces into an HDF5 file for later SCA analysis.
"""

import sys
import os
import time
import argparse
from pathlib import Path

import h5py
import numpy as np
from tqdm import tqdm

# External dependencies (fill in the correct module paths for your setup)
import chipwhisperer as cw

# ---------------------------------------------------------------------------
# Project root detection and path setup
# ---------------------------------------------------------------------------

def find_project_root(start: Path, markers=("fusesoc.conf", ".dojo_root")) -> Path:
    """
    Walk upwards from 'start' until a directory containing one of 'markers'
    is found. This directory is assumed to be the Side-Channel-Dojo root.
    """
    current = start
    while current != current.parent:
        if any((current / m).exists() for m in markers):
            return current
        current = current.parent

    raise RuntimeError(
        f"Could not find project root (looked for markers: {markers}). "
        "Please ensure you are inside the Side-Channel-Dojo repository."
    )


# Script directory (works both when installed and when run from source)
try:
    SCRIPT_DIR = Path(__file__).resolve().parent
except NameError:
    # Fallback for interactive runs (should not happen in script form)
    SCRIPT_DIR = Path.cwd()

DOJO_ROOT = find_project_root(SCRIPT_DIR)

# ---------------------------------------------------------------------------
# Global paths (independent of S-Box / run configuration)
# ---------------------------------------------------------------------------

XHEEP_DIR    = DOJO_ROOT / "sw" / "x-heep"
ASCON_PY_DIR = DOJO_ROOT / "sw" / "ciphers" / "ASCON_init_python"
SCA_DIR      = DOJO_ROOT / "sw" / "sca_scripts"
HW_DIR       = DOJO_ROOT / "hw"

# Traces and plots base directories for ASCON SW SCA
TRACESET_DIR  = DOJO_ROOT / "sw" / "traceset" / "ASCON" / "sw"
BASE_PLOT_DIR = DOJO_ROOT / "sw" / "sca_scripts" / "ASCON" / "sw" / "plot"

TRACESET_DIR.mkdir(parents=True, exist_ok=True)
BASE_PLOT_DIR.mkdir(parents=True, exist_ok=True)

# Make local modules importable 
sys.path.insert(0, str(ASCON_PY_DIR))
sys.path.insert(0, str(SCA_DIR))
sys.path.insert(0, str(XHEEP_DIR))

# ---------------------------------------------------------------------------
# Local imports (after sys.path setup)
# ---------------------------------------------------------------------------
from pico_api import PS5000aWrapper
import readFirmware                        
from analyzer.attack.ascon.xheep_ascon_cpa.ascon_first_round import ascon_first_round
# FPGA bitstream and Verilog defines for CW305 + X-HEEP

BITSTREAM_PATH = (
    HW_DIR
    / "fpga"
    / "bitstream"
    / "xheep"
    / "cw305_top.bit"
)

VERILOG_DEFINES = (
    HW_DIR
    / "vendor"
    / "cw305-heep"
    / "hw"
    / "fpga"
    / "cw305_aes_defines.v"
)


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _yn(flag: bool) -> str:
    """Pretty yes/no string used in configuration printout."""
    return "yes" if flag else "no"

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


def prepare_board(firmware: str):
    """
    Prepare the CW305 + X-HEEP board for the capture:

      1. Initialize the PicoScope.
      2. Initialize CW305 with the bitstream and Verilog defines.
      3. Configure PLL and clock settings.
      4. Load the X-HEEP firmware into the microcontroller.

    Args:
        firmware: Path to the firmware .hex file (string).

    Returns:
        (ps, cw305): PicoScope wrapper and CW305 handle.
    """
    # 1) Initialize PicoScope
    ps = PS5000aWrapper()
    ps.get_unitInfo()

    # Example scope setup: ~23 us window, 11500 requested samples (~2 ns target interval)
    ps.scope_setup(obs_time=23E-6, nSamples=11500)

    bitstream = BitstreamFile(BITSTREAM_PATH)

    # 2) Initialize CW305 with required parameters
    cw305 = cw.target(
        None,
        cw.targets.CW305,
        bsfile=bitstream,
        force=True,
        slurp=True,
        defines_files=[str(VERILOG_DEFINES)],
    )

    # Core voltage and PLL configuration
    cw305.vccint_set(1.0)
    cw305.pll.pll_enable_set(True)        # enable PLL chip
    cw305.pll.pll_outenable_set(False, 0) # disable PLL 0
    cw305.pll.pll_outenable_set(True, 1)  # enable PLL 1
    cw305.pll.pll_outenable_set(False, 2) # disable PLL 2
    cw305.pll.pll_outfreq_set(10e6, 1)    # PLL1 frequency set to 10 MHz

    # Disable USB clock (optional, reduces noise in the power traces)
    cw305.clkusbautooff = True
    # Idle time between captures
    cw305.clksleeptime = 1

    # 3) Set the clock source via FPGA register
    cw305.fpga_write(cw305.REG_CLKSETTINGS, data=bytearray([0x01]))

    # 4) Load firmware into X-HEEP
    readFirmware.readFirmware(cw305, firmware)

    return ps, cw305


def plot_overlapped_traces(traces: np.ndarray,
                           sampling_interval: float,
                           out_path: Path,
                           max_traces: int = 200, 
                           save_plot: bool = False) -> None:
    """
    Plot several overlapped traces and optionally save the figure.

    Args:
        traces: Array of shape (n_traces, n_samples).
        sampling_interval: Time between samples (seconds).
        out_path: Path to the PNG file to save.
        max_traces: Maximum number of traces to overlay.
        save_plot: Whether to save the plot to disk.
    """
    import matplotlib.pyplot as plt  # local import to keep script lightweight

    n_traces, n_samples = traces.shape
    n_plot = min(max_traces, n_traces)

    t = np.arange(n_samples) * sampling_interval

    fig, ax = plt.subplots(figsize=(10, 6))
    for i in range(n_plot):
        ax.plot(t * 1e6, traces[i], linewidth=0.5, alpha=0.4)

    ax.set_xlabel("Time (µs)")
    ax.set_ylabel("Voltage (a.u.)")
    ax.set_title(f"Overlapped ASCON traces (first {n_plot} of {n_traces})")
    ax.grid(False)

    fig.tight_layout()
    if save_plot:
        fig.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Main capture routine
# ---------------------------------------------------------------------------

def run_capture(
    sbox_type: str,
    n_trc: int,
    save_traces: bool,
    traces_overlapped_plot: bool,
    save_plot: bool,
) -> None:
    """
    Run the ASCON HW capture:

      - Configure key / nonce / IV.
      - Program firmware and prepare board.
      - Capture 'n_trc' traces.
      - Save to HDF5 and optionally create an overlapped trace plot.
    """

    # Per-run paths
    firmware_file = (
        DOJO_ROOT
        / "sw"
        / "x-heep"
        / "ASCON_firmware"
        #/ f"ascon_opt32_{sbox_type}_{n_trc // 1000}k.hex"
        / f"ascon_opt32_{sbox_type}_5000k.hex"
    )
    traceset_file = TRACESET_DIR / f"ascon_opt32_{sbox_type}_{n_trc // 1000}k.h5"
    plot_dir = BASE_PLOT_DIR / sbox_type
    plot_dir.mkdir(parents=True, exist_ok=True)

    # -------------------------------------------------------------------
    # Configuration printout
    # -------------------------------------------------------------------
    print("\n================= CONFIGURATION USED FOR CAPTURE OF POWER TRACES OF ASCON SW IMPLEMENTATION =================")
    print(f"DOJO_ROOT           : {DOJO_ROOT}")
    print()
    print("Target")
    print(f"  S-box type        : {sbox_type}")
    print()
    print("Paths")
    print(f"  Bitstream         : {BITSTREAM_PATH}")
    print(f"  Verilog defines   : {VERILOG_DEFINES}")
    print(f"  Firmware          : {firmware_file}")
    print(f"  HW traces file    : {traceset_file}")
    print(f"  SCA traces dir    : {TRACESET_DIR}")
    print(f"  Plot dir          : {plot_dir}")
    print("Online phase")
    print(f"  Number of traces  : {n_trc}")
    print(f"  Save traces       : {_yn(save_traces)}")
    print(f"  Overlapped plot   : {_yn(traces_overlapped_plot)}")
    print(f"  Save plot         : {_yn(save_plot)}")
    print("===============================================================================================================\n")

    # -------------------------------------------------------------------
    # ASCON key, nonce and IV (strings, big-endian hex)
    # -------------------------------------------------------------------
    key_hex   = "000102030405060708090A0B0C0D0E0F"
    nonce_hex = "000102030405060708090A0B0C0D0E0F"
    iv_hex    = "00001000808C0001"  # From ASCON-128a parameters

    # Reverse key by bytes (2 hex chars per byte) to match C endianness
    key_bytes = [key_hex[i:i+2] for i in range(0, len(key_hex), 2)]
    key_reversed_hex = "".join(key_bytes[::-1])
    key_int = int(key_reversed_hex, 16)

    # Pretty print key as byte list
    formatted_key = [key_reversed_hex[i:i+2] for i in range(0, len(key_reversed_hex), 2)]
    print(f"[ONLINE] Fixed key used for acquisition (hex, LSB first): {formatted_key}")

    # Reverse nonce by bytes (2 hex chars per byte)
    nonce_bytes = [nonce_hex[i:i+2] for i in range(0, len(nonce_hex), 2)]
    nonce_reversed_hex = "".join(nonce_bytes[::-1])
    nonce_int = int(nonce_reversed_hex, 16)

    print(f"[ONLINE] Trace acquisition enabled. Target traces: {n_trc}")
    print(f"[ONLINE] Using bitstream      : {BITSTREAM_PATH}")
    print(f"[ONLINE] Firmware             : {firmware_file}")
    print(f"[ONLINE] HDF5 traceset target : {traceset_file}")

    # -------------------------------------------------------------------
    # Prepare board (PicoScope + CW305)
    # -------------------------------------------------------------------
    try:
        ps, cw305 = prepare_board(str(firmware_file))
        print("\n[ONLINE] Board initialized successfully.")
        print("[ONLINE] Picoscope settings:")
        print(ps.get_scopeSettings())
        sampling_interval = ps.get_samplingInterval()
        print(f"[ONLINE] Sampling Interval   : {sampling_interval} s\n")
    except Exception as e:
        print(f"[ERROR] Failed to prepare board (PicoScope + CW305): {e}")
        raise

    # -------------------------------------------------------------------
    # Trace acquisition
    # -------------------------------------------------------------------
    preview_traces = None

    try:
        n_samples = ps.get_nSamples()
        preview_count = min(100, n_trc) if traces_overlapped_plot else 0
        if preview_count:
            preview_traces = np.empty((preview_count, n_samples), dtype=np.float32)

        trace_dtype = np.float32
        trace_chunk_rows = 256
        trace_chunk_shape = (min(trace_chunk_rows, n_trc), n_samples)

        # Create the HDF5 datasets up front so traces can be streamed directly
        # to disk instead of buffering the full capture in RAM.
        f_write_traces = None
        d_traces = None
        d_nonces = None
        if save_traces:
            print("[ONLINE] Creating HDF5 datasets for streamed capture...")
            print(f"[ONLINE] Writing capture data to file: {traceset_file}")
            f_write_traces = h5py.File(traceset_file, "w")
            d_nonces = f_write_traces.create_dataset(
                "nonces",
                shape=(n_trc, 2),
                dtype=np.uint64,
                chunks=(min(4096, n_trc), 2),
            )
            d_traces = f_write_traces.create_dataset(
                "traces",
                shape=(n_trc, n_samples),
                dtype=trace_dtype,
                chunks=trace_chunk_shape,
            )

            # ---- Dataset-level metadata ----
            d_traces.attrs["description"] = (
                "Power traces: each row is one trace, stored as float32 "
                "dynamic voltage samples during ASCON execution."
            )
            d_traces.attrs["dtype"] = "float32"
            d_traces.attrs["units"] = "AC Power"

            d_nonces.attrs["description"] = (
                "ASCON nonces stored as 2×64-bit integers per trace: "
                "nonces[i,0] = least significant 64 bits (LSB half), "
                "nonces[i,1] = most significant 64 bits (MSB half). "
                "Nonce is first reversed by bytes (little-endian) before splitting."
            )
            d_nonces.attrs["layout"] = "nonce[i,0]=LSB64, nonce[i,1]=MSB64"
            d_nonces.attrs["dtype"] = "uint64"

            # ---- File-level metadata ----
            f_write_traces.attrs["sampling_interval"] = sampling_interval
            f_write_traces.attrs["n_traces"] = n_trc
            f_write_traces.attrs["n_samples"] = n_samples
            f_write_traces.attrs["completed_traces"] = 0
            f_write_traces.attrs["key_hex"] = key_hex
            f_write_traces.attrs["iv_hex"] = iv_hex
            f_write_traces.attrs["description"] = (
                "ASCON SCA traceset. Datasets: /traces (float32, n_traces×n_samples), "
                "/nonces (uint64, n_traces×2, little-endian 128-bit nonce split)."
            )

        print("[ONLINE] Starting trace capture...")
        nonce = nonce_int

        for i in tqdm(range(n_trc), desc="Capturing traces"):
            # Start acquisition on PicoScope
            ps.runBlock()
            time.sleep(0.05)

            # Trigger program execution and acquisition via status register
            cw305.fpga_write(cw305.REG_BRIDGE_STATUS, data=bytearray([0x08]))
            ps.waitReady()

            # Retrieve captured power trace
            data = ps.getDataV()
            trace = np.asarray(data, dtype=trace_dtype)

            if save_traces:
                d_traces[i] = trace

            # Store nonce halves (little-endian 2×64-bit representation)
            nonce_lsb = (nonce >> 64) & 0xFFFFFFFFFFFFFFFF
            nonce_msb = nonce & 0xFFFFFFFFFFFFFFFF
            if save_traces:
                d_nonces[i, 0] = nonce_lsb
                d_nonces[i, 1] = nonce_msb

            if preview_count and i < preview_count:
                preview_traces[i] = trace

            # Update nonce for next iteration using 2 state registers
            S = ascon_first_round(key_int, nonce, sbox_type)
            nonce = (S[3] << 64) | S[4]

            if save_traces and ((i + 1) % 1000 == 0 or i + 1 == n_trc):
                f_write_traces.attrs["completed_traces"] = i + 1
                f_write_traces.flush()
                print(
                    f"[ONLINE] File progress: {i + 1}/{n_trc} traces flushed to {traceset_file}"
                )

            time.sleep(1e-3)  # 1 ms

            # Reset the status register to reload the program execution
            cw305.fpga_write(cw305.REG_BRIDGE_STATUS, data=bytearray([0x00]))

        # -------------------------------------------------------------------
        # Save traces to HDF5
        # -------------------------------------------------------------------
        if save_traces:
            f_write_traces.attrs["completed_traces"] = n_trc
            f_write_traces.close()
            print(f"[ONLINE] Capture completed. Traces saved to: {traceset_file}")
        else:
            print("[ONLINE] Capture completed. Traces were not saved (save_traces = False).")

        # -------------------------------------------------------------------
        # Optional overlapped traces plot
        # -------------------------------------------------------------------
        if traces_overlapped_plot:
            plot_path = plot_dir / f"ascon_traces_overlapped_{sbox_type}_{n_trc // 1000}k.png"
            print(f"[ONLINE] Generating overlapped trace plot: {plot_path}")
            plot_overlapped_traces(
                traces=preview_traces,
                sampling_interval=sampling_interval,
                out_path=plot_path,
                max_traces=100,
                save_plot=save_plot,
            )
            preview_traces = None
            print("[ONLINE] Overlapped trace plot generated.")

    except Exception as e:
        print(f"[ERROR] Capture aborted due to error: {e}")
        raise
    finally:
        try:
            if 'f_write_traces' in locals() and f_write_traces is not None:
                if f_write_traces.id.valid:
                    f_write_traces.close()
        except Exception:
            pass
        # Disconnect CW305 and PicoScope (online phase done)
        print("[ONLINE] Shutting down instruments...")
        try:
            cw305.dis()
        except Exception:
            pass
        try:
            ps.dis()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """
    Script entry point. Adjust the configuration here or add argparse if needed.
    """
    # Available S-box implementations (for reference)
    AVAILABLE_SBOXES = [
        "lut_ascon",
        "lut_bilgin",
        "lut_allouzi",
        "lut_lu_4",
        "lut_lu_5",
        "lut_lu_6",
        "lut_lu_7",
    ]

    # --- User configuration ------------------------------------------------
    parser = argparse.ArgumentParser(description="Capture ASCON power traces.")
    parser.add_argument("--sbox", choices=AVAILABLE_SBOXES, default="lut_lu_5", help="S-box implementation to use.")
    parser.add_argument("--traces", type=int, default=1000000, help="Number of traces to capture.")
    args = parser.parse_args()

    sbox_type = args.sbox
    n_trc = args.traces

    save_traces = True          # store traces into an HDF5 file
    traces_overlapped_plot = True  # generate overlapped trace plot
    save_plot = True            # kept for symmetry; plot is always saved when generated
    # -----------------------------------------------------------------------

    run_capture(
        sbox_type=sbox_type,
        n_trc=n_trc,
        save_traces=save_traces,
        traces_overlapped_plot=traces_overlapped_plot,
        save_plot=save_plot,
    )


if __name__ == "__main__":
    main()
