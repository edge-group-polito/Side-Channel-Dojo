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

###################### INITIALIZATION ######################

trace_acquisition = False

bitstream = r"../../hw/fpga/bitstream/xheep/cw305_top.bit"
verilog_defines = r"../../hw/vendor/cw305-heep/hw/fpga/cw305_aes_defines.v"

# Precompiled ASCON firmware for the CW305 board
firmware = r"../x-heep/ASCON_firmware/main.hex"
# To run another firmware compiled with the xheep toolchain, uncomment the following line: 
#firmware = r"../../hw/vendor/cw305-heep/sw/build/main.hex"

# Traces file path
traces_dir  = r"../../build/xheep_test/"
traces_file = r"../../build/xheep_test/ASCON_traces.h5"

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

# Initialize key and plain text.
key  = [ 0x2b, 0x7e, 0x15, 0x16, 0x28, 0xae, 0xd2, 0xa6, 0xab, 0xf7, 0x15, 0x88, 0x09, 0xcf, 0x4f, 0x3c ]
text = [ 0x6e, 0xc1, 0x53, 0x9c, 0xfb, 0xe7, 0xf6, 0x18, 0x92, 0xac, 0x19, 0x87, 0xf5, 0x94, 0xe1, 0x2b ]

# Each element of the key is converted to a 2-digit hex string 
formatted_key = ''.join(format(el, '02x') for el in key)
print("Key: ", [ hex(subkey) for subkey in key])

# Initialize the AES software emulated cipher
# cipher = AES_golden_model() #TODO: change this to the ASCON cipher


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
    traces = np.zeros((N, ps.get_nSamples()))

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

        # Update the plain text as the previous chipertext
        # text = cipher.encrypt(formatted_key, text, tested_sbox) #TODO: save also the plaintexts in a file

        time.sleep(1E-3) # 1 ms
        # Reset the status register to reload the program execution and the scope acquisition
        cw305.fpga_write(cw305.REG_BRIDGE_STATUS, data=bytearray([0x00]))

    # Disconnect CW305 and picoscope
    cw305.dis()
    ps.dis()

    # Check if the traces file path exists, if not create the directory
    if not os.path.exists(traces_dir):
        os.makedirs(traces_dir)
    # Save the traces to a file
    with h5py.File(traces_file, 'w') as f_write_traces:
        f_write_traces.create_dataset('traces', data=traces)

    print(f"\nTraces saved to {traces_file}")


####################### OFFLINE PHASE #######################

# Load the traces from the file, if it exists
try:
    with h5py.File(traces_file, 'r') as f_read_traces:
        traces = f_read_traces['traces']

        # Plot one trace
        print(f"Number of traces: {len(traces)}")
        print(f"Number of samples per trace: {len(traces[0])}")
        xrange = np.arange(0, len(traces[0])) * sampling_interval # Convert samples to time
        plt.plot(xrange, 1000*traces[0])
        plt.title(f"Trace 0")
        plt.xlabel("Time samples (s)")
        plt.ylabel("Voltage (mV)")
        plt.grid()
        plt.show()

        # Plot 40 traces overlapped
        print("Generating power traces overlapped plot...")
        sca_plt = sca_plot()
        power_plt = sca_plt.power_traces_overlapped(traces, sampling_interval)
        power_plt.show()

        # Ensure the Graphs directory exists and save the plot
        # os.makedirs("../x-heep/Graphs/AES_c", exist_ok=True)
        # power_plt.savefig("../x-heep/Graphs/AES_c/")

        # power_plt.show()
        power_plt.close()

except FileNotFoundError:
    print(f"ERROR: Traces file {traces_file} not found. Please run the trace acquisition phase first.")
