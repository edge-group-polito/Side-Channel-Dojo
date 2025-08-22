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

trace_acquisition = False
save_traces = False
cpa_phase_1_bit = False
cpa_phase_full_key = True

traces_overlapped_plot = False

bitstream = r"../../hw/fpga/bitstream/xheep/cw305_top.bit"
verilog_defines = r"../../hw/vendor/cw305-heep/hw/fpga/cw305_aes_defines.v"

# Precompiled ASCON firmware for the CW305 board
firmware = r"../x-heep/ASCON_firmware/main.hex"
# To run another firmware compiled with the xheep toolchain, uncomment the following line: 
#firmware = r"../../hw/vendor/cw305-heep/sw/build/main.hex"

# Traces file path
traces_dir  = r"../../build/xheep_test/"
traces_file = r"../../build/xheep_test/ASCON_RV32I_traces_nonces_500k.h5"
#traces_file = r"../../build/xheep_test/ASCON_RV32I_traces_nonces_50k.h5"
# traces_file = r"../../build/xheep_test/ASCON_RV32I_traces_nonces_50k_2.h5"

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
        #ps.scope_setup(obs_time=16E-6, nSamples=1600)
        # The scope is triggered before the registers update, and it is set for only 34 clock cycles.
        ps.scope_setup(obs_time=3.5E-6, nSamples=350) # ~3.5 us, 350 samples

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
initialization_vector = "00001000808C0001" # Computed from the ASCON 128A parameters
sbox_type = "lut_ascon"

# Nonce and key are first reversed by groups of 2 char (to be compliant with 
# the endianess of the C application) and then converted to integers
# Reverse by bytes (2 hex chars per byte)
key_bytes = [key[i:i+2] for i in range(0, len(key), 2)]
key_reversed = ''.join(key_bytes[::-1])
key = int(key_reversed, 16)

# The key is converted to a 2-digit hex string 
formatted_key = [key_reversed[i:i+2] for i in range(0, len(key_reversed), 2)]
print("Key: ", formatted_key)

# Reverse by bytes (2 hex chars per byte)
nonce_bytes = [nonce[i:i+2] for i in range(0, len(nonce), 2)]
nonce_reversed = ''.join(nonce_bytes[::-1])
nonce = int(nonce_reversed, 16)

initialization_vector = int(initialization_vector, 16)

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
        nonces[i, 0] = (nonce >> 64) & 0xFFFFFFFFFFFFFFFF # Least significant 64 bits of the nonce
        nonces[i, 1] = nonce & 0xFFFFFFFFFFFFFFFF         # Most significant 64 bits of the nonce

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
        # Read the first 50000 traces and nonces. It is better to use the slicing
        # operator even to load the whole dataset, since with the h5 format 
        # data is read from the disk each time. The slicing operator forces the data 
        # to be loaded into the RAM.
        traces = f_read_traces['traces'][:25000]
        nonces = f_read_traces['nonces'][:25000]


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
            power_plt.savefig("../x-heep/Graphs/ASCON_c/ASCON_power_traces_overlapped.png")
            power_plt.close()

        if cpa_phase_1_bit:
            print("Running CPA attack (this might take a while)...")

            # TODO: for the moment, the attack is performed only on the first half key register (x0).
            # Still needed to add an external loop over the necessary key bits to retrieve the
            # full key register x0. For each bit index, the leakage model is built and the CPA attack is performed.

            # The CPA attack is repeated with an incremental number of traces,
            # in order to see how the distance between the correlation value of 
            # the correct key guess and the others increases with the number of traces.
            corr_vs_traces = []
            state_register_index = 0
            bit_index = 8
            tic = time.perf_counter()

            # DEBUG
            key_0 = key & 0xFFFFFFFFFFFFFFFF
            key_0_j     = (key_0 >> (bit_index % 64)) & 1
            key_0_j19   = (key_0 >> ((bit_index + 19) % 64)) & 1
            key_0_j28   = (key_0 >> ((bit_index + 28) % 64)) & 1

            for count in range(1, 1001):
                partial_traces = traces[:(count*25)]
                partial_nonces = nonces[:(count*25)]

                # Build the leakage model matrix for all the nonces
                H_matrix = np.empty((len(partial_nonces), 8), dtype=np.uint8)
                R_matrix = np.empty((8, partial_traces.shape[1]), dtype=np.float64)

                for n in range(len(partial_nonces)):
                    nonce_MSB = partial_nonces[n][1]
                    nonce_LSB = partial_nonces[n][0]
                    leakage_model_i = ascon_leakage_model(initialization_vector, nonce_MSB, nonce_LSB, state_register_index, bit_index, sbox_type)
                    H_matrix[n] = leakage_model_i
                
                # CPA attack
                R_matrix = ascon_cpa(partial_traces, H_matrix)

                # Find the time sample with the maximum correlation value
                corr_vs_keyguess = np.max(np.abs(R_matrix), axis=1) # shape (8,). Max value for each column (key guess) is returned
                print("Number of traces: ", len(partial_traces))
                for j in range(corr_vs_keyguess.shape[0]):
                    max_corr_value = corr_vs_keyguess[j]
                    print(f"Key guess {j}: {max_corr_value:.4f}")

                # Find the key guess with the maximum correlation value
                best_key_guess = np.argmax(corr_vs_keyguess)
                print(f"Key guess with maximum correlation value: {best_key_guess}")
                print(f"Attacked bit index: {bit_index}, State register index: {state_register_index}")
                print(f"Expected key bits (bit-j, bit-j + 19, bit-j + 28): ({key_0_j}, {key_0_j19}, {key_0_j28}), got: ({(best_key_guess >> 2) & 1}, {(best_key_guess >> 1) & 1}, {(best_key_guess >> 0) & 1})")

                # Store the correlation values for all the key guesses
                corr_vs_traces.append(corr_vs_keyguess)

            # Correlation vs traces plot
            corr_vs_traces = np.array(corr_vs_traces)  # shape (steps, 8)
            x = np.arange(1, len(corr_vs_traces) + 1) * 25

            plt.figure(figsize=(10, 5))
            for key_idx in range(8):
                plt.plot(x, corr_vs_traces[:, key_idx], label=f"Key guess {key_idx}")

            plt.xlabel("Number of traces")
            plt.ylabel("Correlation value")
            plt.title("Correlation vs Number of traces")
            plt.grid()
            plt.legend()
            plt.savefig("../x-heep/Graphs/ASCON_c/ASCON_correlation_vs_traces.png")
            plt.close()

            toc = time.perf_counter()
            print(f"\nCPA attack completed in {(toc - tic)/60:.2f} minutes.\n")

        if cpa_phase_full_key:
            # Full key recovery phase
            print("Starting full key recovery phase...")

            # Print the number of traces and the number of samples for each trace
            print(f"Number of traces: {traces.shape[0]}")
            print(f"Number of samples per trace: {traces.shape[1]}")

            # List of bit indexes to attack, ordered according to the SNR value
            key_bit_indexes_0 = [13, 32, 63, 16, 57, 52, 37, 54, 33, 43, 0, 40, 
                                  1, 45, 11, 47, 41, 62, 4, 39, 44, 8, 55, 42, 53,
                                  6, 49, 5, 14, 15, 22, 31, 38, 46, 48]
            
            key_bit_indexes_1 = [31, 32, 0, 35, 59, 60, 1, 36, 34, 63, 45, 44, 18,
                                 46, 38, 12, 39, 47, 7, 41, 51, 49, 50, 5, 15, 62,
                                 11, 25, 6, 13, 61, 48, 27, 17, 56, 16, 30]

            k0_bits = np.zeros(64, dtype=np.uint8)
            k1_bits = np.zeros(64, dtype=np.uint8)

            tic = time.perf_counter()
            print()

            # Iterate over all key bits of k0
            for key_bit in tqdm(key_bit_indexes_0, "Key bit recovery progress"):
                # Build the leakage model matrix
                H_matrix = np.empty((len(nonces), 8), dtype=np.uint8)
                R_matrix = np.empty((8, traces.shape[1]), dtype=np.float64)

                for n in range(len(nonces)):
                    nonce_MSB = nonces[n][1]
                    nonce_LSB = nonces[n][0]
                    leakage_model_i = ascon_leakage_model(initialization_vector, nonce_MSB, nonce_LSB, 0, key_bit, sbox_type)
                    H_matrix[n] = leakage_model_i

                # CPA attack
                R_matrix = ascon_cpa(traces, H_matrix)

                # Find the time samples with the maximum correlation value
                corr_vs_keyguess = np.max(np.abs(R_matrix), axis=1) # shape (8,)

                # Find the key guess with the maximum correlation value
                best_key_guess = np.argmax(corr_vs_keyguess)

                # Save the result to the k0 vector
                k0_bits[(key_bit)      % 64] = (best_key_guess >> 2) & 1
                k0_bits[(key_bit + 19) % 64] = (best_key_guess >> 1) & 1
                k0_bits[(key_bit + 28) % 64] = (best_key_guess >> 0) & 1

            # Convert the numpy array into a single hex integer
            k0 = 0
            for i in range(64):
                k0 |= ((k0_bits[i] & 0x01) << i)
            print(f"Recovered most significand half of the key: {k0:016x}")
            print()

            # Iterate over all key bits of k1
            for key_bit in tqdm(key_bit_indexes_1, "Key bit recovery progress"):
                # Build the leakage model matrix
                H_matrix = np.empty((len(nonces), 8), dtype=np.uint8)
                R_matrix = np.empty((8, traces.shape[1]), dtype=np.float64)

                for n in range(len(nonces)):
                    nonce_MSB = nonces[n][1]
                    nonce_LSB = nonces[n][0]
                    leakage_model_i = ascon_leakage_model(initialization_vector, nonce_MSB, nonce_LSB, 1, key_bit, sbox_type, k0)
                    H_matrix[n] = leakage_model_i

                # CPA attack
                R_matrix = ascon_cpa(traces, H_matrix)

                # Find the time samples with the maximum correlation value
                corr_vs_keyguess = np.max(np.abs(R_matrix), axis=1) # shape (8,)

                # Find the key guess with the maximum correlation value
                best_key_guess = np.argmax(corr_vs_keyguess)

                # Save the result to the k1 vector
                k1_bits[(key_bit)      % 64] = (best_key_guess >> 2) & 1
                k1_bits[(key_bit + 61) % 64] = (best_key_guess >> 1) & 1
                k1_bits[(key_bit + 39) % 64] = (best_key_guess >> 0) & 1

            # Convert the numpy array into a single hex integer. The XOR operation is needed to isolate the k1 bits
            k1 = 0
            for i in range(64):
                k1 |= (k1_bits[i] & 0x01) << i
            # The key recovery from the register z1 actually need this extra XOR operation
            #k1 = k1 ^ k0
            print(f"Recovered least significand half of the key: {k1:016x}\n")

            print(f"Recovered full key: {k1:016x}{k0:016x}")

            # Convert to hex strings
            k0_hex = f"{k0:016X}"
            k1_hex = f"{k1:016X}"
            # Combine the two halves
            recovered_key = k1_hex + k0_hex
            # Reverse both key strings by groups of 2 char and then reverse
            recovered_key = [recovered_key[i:i + 2] for i in range(0, len(recovered_key), 2)][::-1]
            recovered_key = ''.join(recovered_key)

            print(f"Recovered key (little-endian): 0x{recovered_key}")

            toc = time.perf_counter()
            print(f"Full key recovery phase completed in {(toc - tic)/60:.2f} minutes.")

except FileNotFoundError:
    print(f"ERROR: Traces file {traces_file} not found. Please run the trace acquisition phase first.")
