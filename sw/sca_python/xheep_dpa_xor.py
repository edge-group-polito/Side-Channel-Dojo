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
debug = False

trace_acquisition = False
save_traces = False
dpa_phase = True

traces_overlapped_plot = False

bitstream = r"../../hw/fpga/bitstream/xheep/cw305_top.bit"
verilog_defines = r"../../hw/vendor/cw305-heep/hw/fpga/cw305_aes_defines.v"

# Precompiled ASCON firmware for the CW305 board
#firmware = r"../x-heep/ASCON_firmware/main.hex"
# To run another firmware compiled with the xheep toolchain, uncomment the following line: 
firmware = r"../../hw/vendor/cw305-heep/sw/build/main.hex"

# Traces file path
traces_dir  = r"../../build/xheep_test/"
traces_file = r"../../build/xheep_test/XOR_traces_nonces_50k.h5"

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
        ps.scope_setup(obs_time=3E-6, nSamples=300) # 3 us observation time, 300 samples

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
key   = 0x03020100
nonce = 0x03020100
res   = 0x00000000

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
    nonces = np.empty(N, dtype=np.uint32)

    # Initialize the results vector
    results = np.empty(N, dtype=np.uint32)

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
        # Add the result to the results vector
        res = (nonce ^ key)
        results[i] = res
        # Add the nonce to the nonces vector.
        nonces[i] = nonce
        nonce = res + 0xCA31 + i # Update the nonce for the next iteration

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
            f_write_traces.create_dataset('results', data=results)
            f_write_traces.create_dataset('nonces', data=nonces)
            f_write_traces.create_dataset('traces', data=traces)

        print(f"\nTraces saved to {traces_file}")


####################### OFFLINE PHASE #######################

# Load the traces from the file, if it exists
try:
    with h5py.File(traces_file, 'r') as f_read_traces:
        # Read the first 50000 traces and nonces. It is better to use the slicing
        # operator even to load the whole dataset, since with the h5 format 
        # data is read from the disk each time. The slicing operator forces the data 
        # to be loaded into the RAM.
        traces =  f_read_traces[ 'traces' ][:50000]
        nonces =  f_read_traces[ 'nonces' ][:50000]
        results = f_read_traces[ 'results'][:50000]

        # DEBUG - Print the shape of the traces, nonces and results
        print("Traces shape: ", traces.shape)
        print("Nonces shape: ", nonces.shape)
        print("Results shape: ", results.shape)
        print()

        # Sanity check: traces and nonces should have the same number of rows
        if traces.shape[0] != nonces.shape[0]:
            raise ValueError("Number of traces and nonces do not match. Please capture the traces again.")

        if traces_overlapped_plot:
            # Plot 40 traces overlapped
            print("Generating power traces overlapped plot...")
            sca_plt = sca_plot()
            power_plt = sca_plt.power_traces_overlapped(list(traces), sampling_interval)

            # Ensure the Graphs directory exists and save the plot
            os.makedirs("../x-heep/Graphs/ASCON_c", exist_ok=True)
            power_plt.savefig("../x-heep/Graphs/ASCON_c/XOR_power_traces_overlapped.png")
            power_plt.close()

        if dpa_phase:
            print("Running DPA attack...")
            bit_index = 0

            # Syntax: traces_<key_bit_hypothesis>_<result_bit>
            traces_0_0 = []
            traces_0_1 = []
            traces_1_0 = []
            traces_1_1 = []
            # Loop over the nonces
            for i in range(len(nonces)):
                for key_bit_hypothesis in range(2): # 0 or 1
                    expected_value = ((nonces[i] >> bit_index) & 0x01) ^ key_bit_hypothesis
                    # Divide the traces into two groups based on the expected value
                    if key_bit_hypothesis == 0:
                        if expected_value == 0:
                            traces_0_0.append(traces[i])
                        else:
                            traces_0_1.append(traces[i])
                    else:
                        if expected_value == 0:
                            traces_1_0.append(traces[i])
                        else:
                            traces_1_1.append(traces[i])

            # Difference between the two groups for each key hypothesis
            diff_0 = np.mean(traces_0_1, axis=0) - np.mean(traces_0_0, axis=0)
            diff_1 = np.mean(traces_1_1, axis=0) - np.mean(traces_1_0, axis=0)

            # Plot the 2 differences in two side-by-side plots
            fig, axs = plt.subplots(1, 2, figsize=(18, 6))
            axs[0].plot(diff_0, color='blue')
            axs[0].set_title('Difference for Key Bit Hypothesis 0')
            axs[0].set_xlabel('Sample')
            axs[0].set_ylabel('Difference')
            axs[0].grid()
            axs[1].plot(diff_1, color='blue')
            axs[1].set_title('Difference for Key Bit Hypothesis 1')
            axs[1].set_xlabel('Sample')
            axs[1].set_ylabel('Difference')
            axs[1].grid()

            # Save the plot
            os.makedirs("../x-heep/Graphs/ASCON_c", exist_ok=True)
            plt.savefig("../x-heep/Graphs/ASCON_c/xor_dpa_attack_.png")
            plt.close()

except FileNotFoundError:
    print(f"ERROR: Traces file {traces_file} not found. Please run the trace acquisition phase first.")
