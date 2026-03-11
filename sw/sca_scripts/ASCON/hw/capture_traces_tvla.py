import os
import sys
import time
import h5py
import io                  
import contextlib          
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt  
from tqdm import tqdm

def find_project_root(start: Path, markers=("fusesoc.conf", ".dojo_root")) -> Path:
    current = start
    while current != current.parent:
        if any((current / m).exists() for m in markers):
            return current
        current = current.parent
    raise RuntimeError("Could not find project root. Please ensure you are inside the Side-Channel-Dojo repository.")

# ---------------------------------------------------------------------------
# Helper for pretty yes/no printing
# ---------------------------------------------------------------------------
def _yn(flag: bool) -> str:
    return "yes" if flag else "no"

def prepare_board(bitstream, obs_time):
    try:
        ps = PS5000aWrapper()
        ps.get_unitInfo()
        ps.scope_setup(obs_time=obs_time, nSamples=2200)
        cw305 = CW305Wrapper(ps, bitstream, True)
        return ps, cw305
    except Exception as e:
        print(f"Error during board preparation: {e}")
        raise

def main():
    # ---------------------------------------------------------------------------
    # Path Resolution & Setup
    # ---------------------------------------------------------------------------
    try:
        SCRIPT_DIR = Path(__file__).resolve().parent
    except NameError:
        SCRIPT_DIR = Path.cwd()

    DOJO_ROOT = find_project_root(SCRIPT_DIR)

    ASCON_PY_DIR = DOJO_ROOT / "sw" / "ciphers" / "ASCON_python"
    SCA_DIR      = DOJO_ROOT / "sw" / "sca_scripts"
    HW_DIR       = DOJO_ROOT / "hw"

    TRACESET_DIR = DOJO_ROOT / "sw" / "traceset" / "ASCON" / "hw"
    BASE_PLOT_DIR = DOJO_ROOT / "sw" / "sca_scripts" / "ASCON" / "hw" / "plot"

    TRACESET_DIR.mkdir(parents=True, exist_ok=True)
    BASE_PLOT_DIR.mkdir(parents=True, exist_ok=True)

    sys.path.insert(0, str(ASCON_PY_DIR))
    sys.path.insert(0, str(SCA_DIR))

    # Import custom modules
    global PS5000aWrapper, CW305Wrapper, ascon_encrypt
    from pico_api import PS5000aWrapper
    from CW305_ascon_api import CW305Wrapper
    from golden_model_ascon import ascon_encrypt

    # ---------------------------------------------------------------------------
    # Helper Functions
    # ---------------------------------------------------------------------------
    def ascon_encrypt_quiet(*args, **kwargs):
        """Silences the print output from the golden model."""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            out = ascon_encrypt(*args, **kwargs)
        return out, buf.getvalue()

    # ---------------------------------------------------------------------------
    # Configuration Parameters
    # ---------------------------------------------------------------------------
    n_fixed = 1000
    n_random = 1000
    n_trc = n_fixed + n_random

    bitstream_path = HW_DIR / "fpga" / "bitstream" / "ascon" / "ascon_masked" / "cw305_top.bit"
    bitstream = str(bitstream_path)

    obs_time = 22e-6
    nSamples = 2200

    TRACESET_FILE = TRACESET_DIR / f"ascon_masked_{n_trc // 1000}k_tvla.h5"
    PLOT_DIR = BASE_PLOT_DIR / "ascon_masked"
    PLOT_DIR.mkdir(parents=True, exist_ok=True)

    # Flags
    save_dataset = True
    traces_overlapped_plot = True
    save_plot = True
    debug = False  # Set to True to see status bits and match validations

    # ---------------------------------------------------------------------------
    # Configuration printout
    # ---------------------------------------------------------------------------
    print("\n================ ASCON HW TVLA CAPTURE CONFIGURATION ================")
    print(f"  Number of traces  : {n_trc} ({n_fixed} fixed, {n_random} random)")
    print(f"  HW traces file    : {TRACESET_FILE}")
    print(f"  Debug output      : {_yn(debug)}")
    print("=====================================================================\n")

    # ---------------------------------------------------------------------------
    # TVLA Random Interleaving & Data Setup
    # ---------------------------------------------------------------------------
    labels = np.array([0] * n_fixed + [1] * n_random, dtype=np.uint8)
    np.random.shuffle(labels)

    key = bytes.fromhex("0f0e0d0c0b0a09080706050403020100")
    fixed_nonce = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
    aad = b"\x00" * 16 
    msg = b"\x00" * 16 

    ps, cw305 = prepare_board(bitstream, obs_time)
    n_samples = getattr(ps, 'nSamples', None) or ps.get_nSamples()

    # ---------------------------------------------------------------------------
    # Trace Capture & Validation
    # ---------------------------------------------------------------------------
    try:
        cw305.reset_ascon_core()
        cw305.set_key(key)
        cw305.set_initial_data(aad, msg)

        traces = np.empty((n_trc, n_samples), dtype=float)
        nonces = np.empty((n_trc, 16), dtype=np.uint8)
        
        mismatches = 0

        print("[ONLINE] Starting ASCON Masked TVLA capture...")
        for i in tqdm(range(n_trc)):
            current_nonce = fixed_nonce if labels[i] == 0 else os.urandom(16)
            cw305.set_nonce(current_nonce)
            
            cw305.reset_ascon_core()
            status_start = cw305.read_fpga(cw305.REG_CRYPT_STATUS, 1)[0]
            
            if debug:
                tqdm.write(f"[DEBUG] Status before trigger: {status_start:08b}")

            # Hardware Capture
            trace = cw305.capture_ascon_trace() 
            hw_ct, hw_tag = cw305.read_results()
            
            traces[i] = trace
            nonces[i] = list(current_nonce)
            
            # Software Validation
            sw_all, gm_log = ascon_encrypt_quiet(key, current_nonce, aad, msg, variant="Ascon-AEAD128")
            sw_tag = sw_all[-16:]
            sw_ct = sw_all[:-16]
            
            if hw_ct != sw_ct or hw_tag != sw_tag:
                mismatches += 1
                tqdm.write("❌ Mismatch!")
                tqdm.write(f"  HW CT : {hw_ct.hex()}")
                tqdm.write(f"  SW CT : {sw_ct.hex()}")
                tqdm.write(f"  HW TAG: {hw_tag.hex()}")
                tqdm.write(f"  SW TAG: {sw_tag.hex()}")
                tqdm.write("— Golden trace —")
                tqdm.write(gm_log)
            else:
                if debug:
                    tqdm.write(f"✅ Match  CT={hw_ct.hex()}  TAG={hw_tag.hex()}")
                
        print(f"\nCapture complete. Total Mismatches: {mismatches}/{n_trc}")

        # -----------------------------------------------------------------------
        # Dataset Saving
        # -----------------------------------------------------------------------
        if save_dataset:
            with h5py.File(TRACESET_FILE, "w") as f:
                f.create_dataset("traces", data=traces)
                f.create_dataset("labels", data=labels)
                f.create_dataset("nonces", data=nonces)
                f.attrs["bitstream"] = bitstream
                f.attrs["mismatches"] = mismatches 
                
            print(f"Saved to {TRACESET_FILE}")

        # -----------------------------------------------------------------------
        # Plotting
        # -----------------------------------------------------------------------
        if traces_overlapped_plot:
            print("\nGenerating overlapped plot...")
            # Extract the first 50 traces for each dataset
            fix_idx = np.where(labels == 0)[0][:50]
            rand_idx = np.where(labels == 1)[0][:50]
            
            traces_fix = traces[fix_idx]
            traces_rand = traces[rand_idx]

            plt.figure(figsize=(14,5))
            plt.plot(np.mean(traces_fix, axis=0), label='Mean of 50 traces from fixed dataset')
            plt.plot(np.mean(traces_rand, axis=0), label='Mean of 50 traces from random dataset')
            plt.title('ASCON Power Consumption')
            plt.xlabel('Time sample')
            plt.ylabel('Power consumption')
            plt.legend()
            
            if save_plot:
                plot_file = PLOT_DIR / "ascon_overlapped_traces.png"
                plt.savefig(plot_file)
                print(f"Plot saved to {plot_file}")

    finally:
        print("Cleaning up hardware connections...")
        cw305.dis()
        ps.dis()

if __name__ == "__main__":
    main()