#!/usr/bin/env python3
"""
Capture AES power traces on X-HEEP + CW305 and (optionally) plot overlapped traces.

This script:
  - Detects the Side-Channel-Dojo project root (DOJO_ROOT).
  - Programs the FPGA bitstream and loads the X-HEEP firmware.
  - Captures N power traces using the PicoScope + CW305 setup.
  - Stores traces into a ChipWhisperer project (.cwp), if enabled.
  - Optionally generates a quick overlapped-traces plot for alignment checks.
"""

import sys
import os
import time
from pathlib import Path

import numpy as np
from tqdm import tqdm

# ---------------------------------------------------------------------------
# Project root detection and path setup
# ---------------------------------------------------------------------------

def find_project_root(start: Path, markers=("fusesoc.conf", ".dojo_root")) -> Path:
    """
    Walk upwards from `start` until one of the marker files is found.

    This lets the script be run from anywhere inside the repository while
    still locating the project root (DOJO_ROOT).
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

# In a script, __file__ exists; in a notebook, it does not.
try:
    SCRIPT_DIR = Path(__file__).resolve().parent
except NameError:
    # Notebook / interactive: use the current working directory instead
    SCRIPT_DIR = Path.cwd()

DOJO_ROOT = find_project_root(SCRIPT_DIR)

# Core directories
AES_PY_DIR = DOJO_ROOT / "sw" / "ciphers" / "AES_python"
SCA_DIR    = DOJO_ROOT / "sw" / "sca_scripts"
HW_DIR     = DOJO_ROOT / "hw"

# Script-specific directories
XHEEP_DIR     = DOJO_ROOT / "sw" / "x-heep"
TRACESET_DIR  = DOJO_ROOT / "sw" / "traceset" / "AES" / "sw"
BASE_PLOT_DIR = DOJO_ROOT / "sw" / "sca_scripts" / "AES" / "sw" / "plot"

# Make local modules importable without fragile ../ hacks
sys.path.insert(0, str(AES_PY_DIR))
sys.path.insert(0, str(SCA_DIR))
sys.path.insert(0, str(XHEEP_DIR))

# ---------------------------------------------------------------------------
# Local imports (after sys.path setup)
# ---------------------------------------------------------------------------

import chipwhisperer as cw
from chipwhisperer.common.traces import Trace

from pico_api import PS5000aWrapper
import readFirmware
from AES_golden import AES_golden_model
from analyzer.utils.sca_plots import sca_plot


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Available S-box implementations
AVAILABLE_SBOXES = [
    "sbox_rijandael  (default AES S-Box, aes_sbox)",
    "sbox_freyre_1",
    "sbox_freyre_2",
    "sbox_freyre_3",
    "sbox_hussain_6",
    "sbox_ozkaynak_1",
    "sbox_azam_1",
    "sbox_azam_2",
    "sbox_azam_3",
]

# Default S-box to test
tested_sbox = "sbox_freyre_3"
sbox_id = tested_sbox.replace("sbox_", "")

# Whether we are attacking a masked firmware or the plain S-box firmware
masked_flag = False

# Flow flags
save_traces            = True   # Store traces into a CW project (.cwp)
traces_overlapped_plot = True   # Plot overlapped power traces
save_plot              = True   # Save overlapped plot to disk

# Bitstream and Verilog defines, rooted at DOJO_ROOT
bitstream_path = HW_DIR / "fpga" / "bitstream" / "xheep" / "cw305_top.bit"
verilog_defines_path = (
    HW_DIR
    / "vendor"
    / "cw305-heep"
    / "hw"
    / "fpga"
    / "cw305_aes_defines.v"
)

bitstream = str(bitstream_path)
verilog_defines = str(verilog_defines_path)

# Firmware and project (.cwp) paths:
# - Firmware is under DOJO_ROOT/sw/x-heep
# - Project is under DOJO_ROOT/sw/traceset/AES/sw
if masked_flag:
    firmware_path = XHEEP_DIR / "AES_masked_firmware_random_plaintext" / f"main_{sbox_id}.hex"
    project_file_path = TRACESET_DIR / f"CW305_xheep_AES_{sbox_id}_masked.cwp"
else:
    firmware_path = XHEEP_DIR / "AES_Sbox_firmware_random_plaintext" / f"main_{sbox_id}.hex"
    project_file_path = TRACESET_DIR / f"CW305_xheep_AES_{sbox_id}.cwp"

firmware    = str(firmware_path)
project_file = str(project_file_path)

# Plot directory per S-box
PLOT_DIR = BASE_PLOT_DIR / tested_sbox

# Ensure output directories exist
TRACESET_DIR.mkdir(parents=True, exist_ok=True)
PLOT_DIR.mkdir(parents=True, exist_ok=True)


def _yn(flag: bool) -> str:
    """Return 'yes' or 'no' for a boolean flag."""
    return "yes" if flag else "no"


def print_configuration():
    """Pretty-print the script configuration."""
    print("\n================= CONFIGURATION =================")
    print(f"DOJO_ROOT           : {DOJO_ROOT}")
    print()
    print("Target")
    print(f"  Tested S-box      : {tested_sbox}")
    print(f"  Masked firmware   : {_yn(masked_flag)}")
    print()
    print("Paths")
    print(f"  Bitstream         : {bitstream}")
    print(f"  Verilog defines   : {verilog_defines}")
    print(f"  Firmware          : {firmware}")
    print(f"  CW project (.cwp) : {project_file}")
    print(f"  Traceset dir      : {TRACESET_DIR}")
    print(f"  Plot dir          : {PLOT_DIR}")
    print()
    print("Online phase")
    print(f"  Save traces       : {_yn(save_traces)}")
    print(f"  Overlapped plot   : {_yn(traces_overlapped_plot)}")
    print(f"  Save plot         : {_yn(save_plot)}")
    print("=================================================\n")


# ---------------------------------------------------------------------------
# Hardware setup
# ---------------------------------------------------------------------------

def prepare_board(firmware: str):
    """
    Prepare the CW305 + X-HEEP board for the capture:
      1. Initialize the PicoScope.
      2. Initialize CW305 with the given bitstream and Verilog defines.
      3. Configure PLL and clock settings.
      4. Load the X-HEEP firmware into the microcontroller.

    Returns:
        (ps, cw305) handles for scope and board.
    """
    # 1) Initialize PicoScope
    ps = PS5000aWrapper()
    ps.get_unitInfo()
    # 0.1 ms window, 4k samples → ~25 ns sampling interval
    ps.scope_setup(obs_time=1e-4, nSamples=4000)

    # 2) Initialize CW305 with required parameters
    cw305 = cw.target(
        None,
        cw.targets.CW305,
        bsfile=bitstream,
        force=True,
        slurp=True,
        defines_files=[verilog_defines],
    )

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


# ---------------------------------------------------------------------------
# Capture logic
# ---------------------------------------------------------------------------

def capture_traces(n_trc: int):
    """
    Capture `n_trc` traces, store them in a CW project (if enabled),
    and optionally plot overlapped traces for alignment inspection.
    """
    # AES key and initial plaintext (fixed for this experiment)
    key  = [0x2B, 0x7E, 0x15, 0x16, 0x28, 0xAE, 0xD2, 0xA6,
            0xAB, 0xF7, 0x15, 0x88, 0x09, 0xCF, 0x4F, 0x3C]
    text = [0x6B, 0xC1, 0xBE, 0xE2, 0x2E, 0x40, 0x9F, 0x96,
            0xE9, 0x3D, 0x7E, 0x11, 0x73, 0x93, 0x17, 0x2A]

    formatted_key = "".join(format(el, "02x") for el in key)
    print(f"[ONLINE] Fixed key used for acquisition: {[hex(subkey) for subkey in key]}")
    print(f"[ONLINE] Trace acquisition enabled. Target traces: {n_trc}")
    print(f"[ONLINE] Using project file : {project_file}")
    print(f"[ONLINE] Programming bitstream: {bitstream}")
    print(f"[ONLINE] Firmware           : {firmware}")

    # Software AES golden model used both for reference ciphertexts and leakage models
    cipher = AES_golden_model()

    # Prepare board (PicoScope + CW305)
    try:
        ps, cw305 = prepare_board(firmware)
        print("\n[ONLINE] Board initialized successfully.")
        print("[ONLINE] Picoscope settings:")
        print(ps.get_scopeSettings())
        print(f"[ONLINE] Sampling Interval : {ps.get_samplingInterval()} s\n")
    except Exception as e:
        print(f"[ERROR] Failed to prepare board (PicoScope + CW305): {e}")
        raise

    sampling_interval = ps.get_samplingInterval()
    project = None

    try:
        # Ensure traceset directory exists (already done above, but safe)
        TRACESET_DIR.mkdir(parents=True, exist_ok=True)

        if save_traces:
            print("[ONLINE] Trace storage enabled. Creating CW project...")
            project_dir = os.path.dirname(project_file)
            os.makedirs(project_dir, exist_ok=True)
            project = cw.create_project(project_file, overwrite=True)
        else:
            print("[ONLINE] Trace storage disabled (save_traces = False).")

        # Trigger the iteration start in the firmware (board-side handshake)
        cw305.fpga_write(cw305.REG_BRIDGE_STATUS, data=bytearray([0x08]))
        time.sleep(1e-3)  # 1 ms
        cw305.fpga_write(cw305.REG_BRIDGE_STATUS, data=bytearray([0x00]))

        print("[ONLINE] Starting trace capture...")
        for _ in tqdm(range(n_trc), desc="Capturing traces"):
            # Run the target: start acquisition on PicoScope
            ps.runBlock()
            time.sleep(0.05)

            # Trigger program execution and acquisition via status register
            cw305.fpga_write(cw305.REG_BRIDGE_STATUS, data=bytearray([0x08]))

            ps.waitReady()

            # Retrieve captured power trace
            data = ps.getDataV()

            # Compute corresponding ciphertext with the emulated AES
            ciphertext = cipher.encrypt(formatted_key, text, tested_sbox)

            if save_traces and project is not None:
                # Store trace and metadata in ChipWhisperer project
                trace = Trace(np.array(data), text, ciphertext, key)
                project.traces.append(trace)

            # Update plaintext as previous ciphertext (chaining)
            text = ciphertext

            time.sleep(1e-3)  # 1 ms
            # Reset the status register for next iteration
            cw305.fpga_write(cw305.REG_BRIDGE_STATUS, data=bytearray([0x00]))

        # Save project if enabled
        if save_traces and project is not None:
            project.save()
            project.close()
            print(f"[ONLINE] Capture completed. Traces saved to: {project_file}")
        else:
            print("[ONLINE] Capture completed. Traces were not saved (save_traces = False).")

        # Optional: generate overlapped traces plot for alignment check
        if traces_overlapped_plot and save_traces:
            print("[ONLINE] Generating overlapped power traces plot...")
            sca_plt = sca_plot()

            # Re-open the project to reuse the saved traces
            proj = cw.open_project(project_file)
            power_plt = sca_plt.power_traces_overlapped(
                proj.waves,
                sampling_interval,
            )

            out_file = PLOT_DIR / f"AES_power_traces_overlapped_{tested_sbox}.png"
            if save_plot:
                power_plt.savefig(out_file)
                print(f"[ONLINE] Overlapped traces plot saved to: {out_file}")

            # Optionally show the plot interactively
            # power_plt.show()

            power_plt.close()
            proj.close()

    except Exception as e:
        print(f"[ERROR] Capture aborted due to error: {e}")
        # Try to safely close the project if it was opened
        if project is not None:
            try:
                project.close()
            except Exception:
                pass
        raise
    finally:
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
# Main entry point
# ---------------------------------------------------------------------------

def main():
    print_configuration()
    # Number of traces to capture
    n_trc = 5000
    capture_traces(n_trc)


if __name__ == "__main__":
    main()
