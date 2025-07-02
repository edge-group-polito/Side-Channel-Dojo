#!/usr/bin/env python3


import sys
sys.path.append( '../sca_python' )
sys.path.append( '../x-heep' )
import readFirmware
import os
os.system("pip list | grep chipwhisperer")

from pico_api import PS5000aWrapper
import chipwhisperer as cw
from analyzer.utils.sca_plots import sca_plot

from tqdm import tqdm
import time
import numpy as np
import matplotlib.pyplot as plt
import h5py

from analyzer.attack.ascon.xheep_ascon_cpa.ascon_first_round import ascon_first_round
from analyzer.attack.ascon.xheep_ascon_cpa.ascon_leakage_model import ascon_leakage_model
from analyzer.attack.ascon.xheep_ascon_cpa.ascon_cpa import ascon_cpa

###################### INITIALIZATION ######################
debug = False

trace_acquisition = False
save_traces = False

traces_overlapped_plot = False

bitstream = r"../../hw/fpga/bitstream/xheep/cw305_top.bit"
verilog_defines = r"../../hw/vendor/cw305-heep/hw/fpga/cw305_aes_defines.v"

# Precompiled ASCON firmware for the CW305 board
firmware = r"../x-heep/ASCON_firmware/main.hex"
# To run another firmware compiled with the xheep toolchain, uncomment the following line: 
#firmware = r"../../hw/vendor/cw305-heep/sw/build/main.hex"

# Traces file path
traces_dir  = r"../../build/xheep_test/"
traces_file = r"../../build/xheep_test/ASCON_traces_nonces.h5"

print()
print("bitstream: ", bitstream)
print("firmware: ", firmware)
print("verilog_defines: ", verilog_defines)
print()


# This function prepares the board for the attack by:
# 1. Initializing the picoscope
# 2. Initializing the CW305 board with the required parameters
# 3. Loading the bitstream to the FPGA
# 4. Loading the microcontroller firmware to the FPGA
def prepare_board(firmware):
    try:
        # Initialize picoscope
        ps = PS5000aWrapper()
        ps.get_unitInfo()
        # The complete permutation phase (12 repetitions) takes about 1800-1900 clock cycles, 
        # which corresponds to 180-190 us at 10 MHz clock frequency.
        # So, to capture just the first permutation, we need a time window of about 18 us.
        # 16 us observation time with sampling frequency of 125 MHz, so nSamples = 1600
        ps.scope_setup(obs_time=16E-6, nSamples=1600)

        # In particular, a single repetition is composed by:
        # 1. A round constant addition (XOR operation) with the state (~2 us)
        # 2. A substitution layer (~2.5 us)
        # 3. Keccak S-box (~7 to us)
        # 4. Some rotations (~3 to us)
        # 5. A linear diffusion layer (~9.5 us)

        # Initialize CW305 with required parameters. More in detail:
        # ps: picoscope object
        # cw.targets.CW305: target device
        # bsfile: bitstream file
        # force: force programming
        # slurp: used to get the device verilog defines for the register addresses
        # defines_files: verilog defines file path.
        cw305 = cw.target(None, cw.targets.CW305, bsfile=bitstream, force=True, slurp=True, defines_files=[verilog_defines])
        cw305.vccint_set(1.0)
        cw305.pll.pll_enable_set(True)             # enable PLL chip
        cw305.pll.pll_outenable_set(False, 0)      # disable PLL 0
        cw305.pll.pll_outenable_set(True, 1)       # enable PLL 1
        cw305.pll.pll_outenable_set(False, 2)      # disable PLL 2
        cw305.pll.pll_outfreq_set(10E6, 1)         # PLL1 frequency set to 10 MHz
        # Disable usb_clock. Optional, but reduces power trace noise
        cw305.clkusbautooff = True
        # 1 ms is plenty idling time 
        cw305.clksleeptime = 1

        # Set the clock source writing the corresponding register
        cw305.fpga_write(cw305.REG_CLKSETTINGS, data=bytearray([0x01]))
        # DEBUG
        # print("FPGA CLKSETTINGS REGISTER: ", cw305.fpga_read(cw305.REG_CLKSETTINGS, 1)[::-1])

        # Load firmware
        readFirmware.readFirmware(cw305, firmware)

        # Return the picoscope and cw305 objects
        return ps, cw305
        
    except ModuleNotFoundError as e:
        print(e)



####################### ONLINE PHASE #######################



# Number of traces to capture
N = 50000
# Default sampling interval is 8 ns
sampling_interval = 8E-9

# Initialize key and nonce
key   = "000102030405060708090A0B0C0D0E0F"
nonce = "000102030405060708090A0B0C0D0E0F"

# The key is converted to a 2-digit hex string 
formatted_key = [key[i:i+2] for i in range(0, len(key), 2)]
print("Key: ", formatted_key)

# Nonce and key are first reversed by groups of 2 char (to be compliant with 
# the endianess of the C application) and then converted to integers
# Reverse by bytes (2 hex chars per byte)
key_bytes = [key[i:i+2] for i in range(0, len(key), 2)]
key_reversed = ''.join(key_bytes[::-1])
key = int(key_reversed, 16)

# Reverse by bytes (2 hex chars per byte)
nonce_bytes = [nonce[i:i+2] for i in range(0, len(nonce), 2)]
nonce_reversed = ''.join(nonce_bytes[::-1])
nonce = int(nonce_reversed, 16)

# DEBUG
if debug:
    for i in range(N):
        S = ascon_first_round(key, nonce, debug)
        nonce = S[3] << 64 | S[4]

# Trace acquisition
if trace_acquisition:
    # Prepare the board
    ps, cw305 = prepare_board(firmware)

    print("Picoscope initialized: \n")
    print(ps.get_scopeSettings())
    print()
    print("Sampling Interval: ", ps.get_samplingInterval(), "s")
    print()

    # Update the sampling interval
    sampling_interval = ps.get_samplingInterval()

    # Initialize the traces matrix.
    # Shape is (N, nSamples), where N is the number of traces and nSamples is the number of samples per trace.
    traces = np.empty((N, ps.get_nSamples()))

    # Initialize the nonce vector
    nonces = np.empty((N, 2), dtype=np.uint64)

    for i in tqdm(range(N), desc="Capturing traces"):
        # Run the target
        ps.runBlock()
        time.sleep(0.05)

        # Write 8 to the status register to trigger the program execution and the scope acquisition
        cw305.fpga_write(cw305.REG_BRIDGE_STATUS, data=bytearray([0x08]))

        ps.waitReady()

        # Get captured trace 
        data = ps.getDataV()

        # Convert the data to a numpy array
        trace = np.array(data)

        # Add the trace to the traces matrix
        traces[i] = trace
        # Add the nonce to the nonces vector. Each half of the nonce is stored into 2 64-bit integers.
        nonces[i, 0] = (nonce >> 64) & 0xFFFFFFFFFFFFFFFF # Most significant 64 bits of the nonce
        nonces[i, 1] = nonce & 0xFFFFFFFFFFFFFFFF         # Least significant 64 bits of the nonce

        # Update the nonce for the next iteration using 2 of the state registers concatenated
        S = ascon_first_round(key, nonce)
        nonce = S[3] << 64 | S[4]

        time.sleep(1E-3) # 1 ms
        # Reset the status register to reload the program execution and the scope acquisition
        cw305.fpga_write(cw305.REG_BRIDGE_STATUS, data=bytearray([0x00]))

    # Disconnect CW305 and picoscope
    cw305.dis()
    ps.dis()

    if save_traces:
        print("Saving traces...")
        # Check if the traces file path exists, if not create the directory
        if not os.path.exists(traces_dir):
            os.makedirs(traces_dir)
        # Save the traces to a file
        with h5py.File(traces_file, 'w') as f_write_traces:
            f_write_traces.create_dataset('nonces', data=nonces)
            f_write_traces.create_dataset('traces', data=traces)

        print(f"\nTraces saved to {traces_file}")


####################### OFFLINE PHASE #######################

# Load the traces from the file, if it exists
try:
    with h5py.File(traces_file, 'r') as f_read_traces:
        traces = f_read_traces['traces']
        nonces = f_read_traces['nonces']

        # Sanity check: traces and nonces should have the same number of rows
        if traces.shape[0] != nonces.shape[0]:
            raise ValueError("Number of traces and nonces do not match. Please capture the traces again.")

        if traces_overlapped_plot:
            # Plot 40 traces overlapped
            print("Generating power traces overlapped plot...")
            sca_plt = sca_plot()
            power_plt = sca_plt.power_traces_overlapped(traces, sampling_interval)

            # Ensure the Graphs directory exists and save the plot
            os.makedirs("../x-heep/Graphs/ASCON_c", exist_ok=True)
            power_plt.savefig("../x-heep/Graphs/ASCON_c/ASCON_power_traces_overlapped.png")
            power_plt.close()


        print("Running CPA attack (this might take a while)...")

        # TODO: for the moment, the attack is performed only on the first half key register (x0).
        # Still needed to add an external loop over the necessary key bits to retrieve the
        # full key register x0. For each bit index, the leakage model is built and the CPA attack is performed.

        # Build the leakage model matrix for all the nonces
        H_matrix = np.empty((len(traces), 8), dtype=np.uint8)
        for i in range(len(traces)):
            leakage_model_i = ascon_leakage_model(nonces[i, 0], nonces[i, 1], state_register_index=0, bit_index=0, debug=debug)
            H_matrix[i] = leakage_model_i

        print("Leakage model matrix dimensions: ", H_matrix.shape)
        
        # CPA attack
        tic = time.perf_counter()
        results = ascon_cpa(traces, H_matrix, debug=debug)
        toc = time.perf_counter()
        print(f"CPA attack completed in {(toc - tic)/60:.2f} minutes.")

except FileNotFoundError:
    print(f"ERROR: Traces file {traces_file} not found. Please run the trace acquisition phase first.")
