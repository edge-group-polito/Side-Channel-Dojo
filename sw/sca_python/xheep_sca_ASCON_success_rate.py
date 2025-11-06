#!/usr/bin/env python3

import sys
sys.path.append( '../sca_python' )

from tqdm import tqdm
import time
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import h5py
import json

from analyzer.attack.ascon.xheep_ascon_cpa.ascon_leakage_model import ascon_leakage_model
from analyzer.attack.ascon.xheep_ascon_cpa.ascon_cpa import ascon_cpa

###################### INITIALIZATION ######################

# Number of traces
N = 10000
resolution = 100
cpa_phase_full_key = True

sbox_type = "lut_ascon" # Options: lut_ascon, lut_bilgin, lut_allouzi, lut_lu_4, lut_lu_5, lut_lu_6, lut_lu_7
sbox_list = ["lut_ascon", "lut_bilgin", "lut_allouzi", "lut_lu_4", "lut_lu_5", "lut_lu_6", "lut_lu_7"]

# Traces file path
traces_dir  = r"../../build/xheep_test/"
# traces_file = r"../../build/xheep_test/ASCON_RV32I_traces_nonces_500k.h5"
traces_file = r"../../build/xheep_test/ascon_opt32_" + sbox_type + "_" + str(N//1000) + "k.h5"

print()
print("traces_file: ", traces_file)
print()

# Initialize key and IV
key = "000102030405060708090A0B0C0D0E0F"
initialization_vector = "00001000808C0001" # Computed from the ASCON 128A parameters

# Nonce and key are first reversed by groups of 2 char (to be compliant with 
# the endianess of the C application) and then converted to integers
# Reverse by bytes (2 hex chars per byte)
key_for_printing = key
key_bytes = [key[i:i+2] for i in range(0, len(key), 2)]
key_reversed = ''.join(key_bytes[::-1])
key = int(key_reversed, 16)

# The key is converted to a 2-digit hex string 
formatted_key = [key_reversed[i:i+2] for i in range(0, len(key_reversed), 2)]
print("Key: ", formatted_key)

initialization_vector = int(initialization_vector, 16)

# Default sampling interval is 8 ns
sampling_interval = 8E-9

####################### OFFLINE PHASE #######################

# Function for the key rank vs traces plot of the selected key bit index
def plot_key_rank_vs_traces(rank_vs_traces_list, key_bit_index):
    plt.figure()
    plt.title(f"Key Rank vs Number of Traces - Key Bit Index {key_bit_index}")
    plt.xlabel("Number of Traces", fontsize=17)
    plt.ylabel("Key Rank (0=best, 7=worst)", fontsize=17)

    ranks = rank_vs_traces_list[key_bit_index]
    x_vals = np.arange(1, len(ranks) + 1) * resolution / 1000  # in thousands
    plt.plot(x_vals, ranks, marker='o', label=f'Key Bit {key_bit_index}')

    ax = plt.gca()
    formatter = mticker.ScalarFormatter(useMathText=True)
    formatter.set_powerlimits((0, 0))
    ax.xaxis.set_major_formatter(formatter)
    ax.ticklabel_format(axis='x', style='sci', scilimits=(0,0))
    ax.xaxis.get_offset_text().set_fontsize(15)

    plt.ylim(-1, 8)
    plt.yticks(range(8))
    plt.grid(True)
    plt.legend()
    plt.savefig("../x-heep/Graphs/ASCON_c/ASCON_key_rank_vs_traces" + f"_sbox_{sbox_type}_bit_{key_bit_index}.png")
    # plt.show()

# Function for the success rate vs traces plot
def plot_success_rate_vs_traces(success_rate_list):
    plt.figure()
    plt.title(f"Success Rate vs Number of Traces - S-box Type {sbox_type}")
    plt.xlabel("Number of Traces", fontsize=17)
    plt.ylabel("Success Rate (%)", fontsize=17)

    success_rates = success_rate_list
    x_vals = np.arange(1, len(success_rates) + 1) * resolution / 1000  # in thousands
    plt.plot(x_vals, success_rates, marker='o', label=f'S-box {sbox_type}')

    ax = plt.gca()
    formatter = mticker.ScalarFormatter(useMathText=True)
    formatter.set_powerlimits((0, 0))
    ax.xaxis.set_major_formatter(formatter)
    ax.ticklabel_format(axis='x', style='sci', scilimits=(0,0))
    ax.xaxis.get_offset_text().set_fontsize(15)

    plt.ylim(0, 100)
    plt.yticks(range(0, 101, 10))
    plt.grid(True)
    plt.legend()
    plt.savefig("../x-heep/Graphs/ASCON_c/ASCON_success_rate_vs_traces" + f"_sbox_{sbox_type}.png")
    # plt.show()

# This function is only used to convert numpy types to native Python types, otherwise
# the json.dump() function raises an error.
def to_python_types(obj):
    """
        Recursively convert numpy types in obj to native Python types.
        In particular, convert:
        - np.integer to int
        - np.floating to float
        Handles nested structures like lists and dictionaries.
    """
    if isinstance(obj, dict):
        return {to_python_types(k): to_python_types(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [to_python_types(i) for i in obj]
    elif isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    else:
        return obj


# Load the traces from the file, if it exists
try:
    with h5py.File(traces_file, 'r') as f_read_traces:
        # Read the first 50000 traces and nonces. It is better to use the slicing
        # operator even to load the whole dataset, since with the h5 format 
        # data is read from the disk each time. The slicing operator forces the data 
        # to be loaded into the RAM.
        traces = f_read_traces['traces'][:N]
        nonces = f_read_traces['nonces'][:N]

        # Sanity check: traces and nonces should have the same number of rows
        if traces.shape[0] != nonces.shape[0]:
            raise ValueError("Number of traces and nonces do not match. Please capture the traces again.")

        if cpa_phase_full_key:
            # Full key recovery phase
            print("Starting full key recovery phase...")

            # Print the number of traces and the number of samples for each trace
            print(f"Number of traces: {traces.shape[0]}")
            print(f"Number of samples per trace: {traces.shape[1]}")
            print("Resolution (traces per step): ", resolution)
            print(f"S-box type: {sbox_type}\n")

            # Mapping of sbox_type to key bit indexes
            key_bit_indexes_0_dict = {
                "lut_ascon": [32, 13, 34, 4, 6, 54, 36, 0, 33, 63, 7, 16, 55, 19, 17, 41, 1, 40, 8, 48, 24, 39, 14, 31, 58, 49, 56, 47, 37, 29, 15, 46, 57, 11],
                "lut_bilgin": [4, 51, 7, 63, 31, 40, 32, 3, 43, 23, 59, 16, 13, 47, 36, 0, 41, 34, 44, 33, 6, 54, 48, 19, 17, 1, 10, 39, 56, 60, 18, 38, 11, 57, 49],
                "lut_lu_7": [32, 0, 13, 4, 16, 33, 15, 34, 63, 54, 55, 43, 6, 31, 14, 7, 39, 36, 17, 40, 48, 1, 19, 41, 24, 11, 3, 47, 29, 27, 37, 57, 8, 49],
                "lut_lu_6": [32, 13, 4, 63, 36, 33, 54, 34, 62, 16, 14, 0, 6, 17, 19, 43, 39, 40, 1, 55, 41, 8, 48, 47, 30, 58, 31, 56, 60, 38, 37, 57, 18],
                "lut_lu_5": [60, 30, 61, 28, 32, 0, 34, 23, 53, 14, 22, 44, 33, 5, 17, 38, 13, 62, 8, 56, 57, 6, 31, 15, 37, 10, 12, 39, 29, 36, 54, 49, 46, 35, 43],
                "lut_lu_4": [32, 13, 4, 36, 33, 54, 34, 6, 16, 14, 63, 0, 17, 19, 39, 43, 40, 1, 7, 55, 24, 41, 47, 48, 29, 58, 37, 50, 8, 12, 18, 57, 15, 49, 30],
                "lut_allouzi": [32, 33, 34, 14, 13, 4, 36, 30, 1, 22, 53, 31, 0, 29, 44, 62, 17, 47, 9, 54, 41, 63, 37, 19, 5, 46, 24, 16, 20, 60, 7, 2, 40, 61, 42, 39, 57],
            }
            key_bit_indexes_1_dict = {
                "lut_ascon": [32, 0, 63, 1, 14, 13, 36, 15, 31, 8, 38, 43, 5, 18, 23, 12, 45, 16, 9, 42, 3, 51, 2, 49, 24, 20, 44, 40, 28, 30, 37, 19, 47, 59, 53, 4, 46],
                "lut_bilgin": [32, 0, 63, 1, 36, 14, 13, 12, 31, 11, 45, 60, 62, 47, 41, 52, 8, 33, 46, 20, 48, 54, 44, 18, 61, 34, 58, 4, 24, 28, 26, 5, 59],
                "lut_lu_7": [50, 8, 42, 11, 59, 60, 17, 32, 49, 0, 63, 3, 10, 28, 43, 36, 1, 56, 34, 18, 33, 27, 4, 13, 25, 9, 6, 20, 19, 23, 5, 12, 15, 2, 62, 46, 55, 29],
                "lut_lu_6": [50, 8, 32, 0, 63, 1, 60, 36, 3, 56, 14, 13, 4, 28, 31, 9, 6, 12, 42, 23, 59, 19, 15, 30, 43, 44, 52, 2, 46, 49, 40, 51, 55, 22],
                "lut_lu_5": [50, 8, 32, 0, 63, 60, 1, 36, 6, 14, 4, 13, 31, 9, 42, 59, 16, 18, 5, 33, 44, 48, 15, 19, 40, 12, 20, 10, 46, 49, 30, 22, 29],
                "lut_lu_4": [32, 0, 1, 63, 47, 31, 36, 60, 8, 4, 3, 9, 56, 37, 35, 16, 2, 7, 6, 30, 11, 26, 52, 12, 28, 54, 19, 62, 15, 43, 20, 27, 46, 14],
                "lut_allouzi": [32, 0, 63, 1, 14, 36, 13, 31, 8, 38, 3, 9, 45, 18, 12, 30, 48, 15, 19, 43, 24, 46, 44, 40, 20, 2, 26, 55, 4, 37, 28, 11, 49, 59, 47],
            }

            # Select the correct list based on sbox_type
            try:
                key_bit_indexes_0 = key_bit_indexes_0_dict[sbox_type]
                key_bit_indexes_1 = key_bit_indexes_1_dict[sbox_type]
            except KeyError:
                raise ValueError(f"Unknown sbox_type: {sbox_type}")

            k0_bits = np.zeros(64, dtype=np.uint8)
            k1_bits = np.zeros(64, dtype=np.uint8)

            tic = time.perf_counter()
            print()

            # Correct key halves
            key_0_correct = key & 0xFFFFFFFFFFFFFFFF
            key_1_correct = (key >> 64) & 0xFFFFFFFFFFFFFFFF

            # Dictionary to store success rate as function of number of traces and the sbox type
            success_rate_vs_traces_0 = {sbox: [] for sbox in sbox_list}
            success_rate_vs_traces_1 = {sbox: [] for sbox in sbox_list}

            # Nested dictionaries to store rank trends as function of the sbox type and number of traces
            key_ranks_vs_traces_0 = {sbox: {key_bit: [] for key_bit in key_bit_indexes_0} for sbox in sbox_list}
            key_ranks_vs_traces_1 = {sbox: {key_bit: [] for key_bit in key_bit_indexes_1} for sbox in sbox_list}

            print("S0 Key Recovery Phase")
            pbar = tqdm(range(1, (traces.shape[0] // resolution) + 1), desc="Using 0 traces") # Loop over number of traces
            for count in pbar:
                pbar.set_description(f"Using {count*resolution} traces")
                partial_traces = traces[:(count*resolution)]
                partial_nonces = nonces[:(count*resolution)]

                # Iterate over all key bits of k0
                for key_bit in key_bit_indexes_0:
                    # Extract correct key guess
                    key_0_j     = (key_0_correct >> ((key_bit)      % 64)) & 1
                    key_0_j19   = (key_0_correct >> ((key_bit + 19) % 64)) & 1
                    key_0_j28   = (key_0_correct >> ((key_bit + 28) % 64)) & 1
                    correct_guess = (key_0_j << 2) | (key_0_j19 << 1) | (key_0_j28 << 0)

                    # Build the leakage model matrix
                    H_matrix = np.empty((len(partial_nonces), 8), dtype=np.uint8)
                    R_matrix = np.empty((8, partial_traces.shape[1]), dtype=np.float64)

                    for n in range(len(partial_nonces)):
                        nonce_MSB = partial_nonces[n][1]
                        nonce_LSB = partial_nonces[n][0]
                        leakage_model_i = ascon_leakage_model(initialization_vector, nonce_MSB, nonce_LSB, 0, key_bit, sbox_type)
                        H_matrix[n] = leakage_model_i

                    # CPA attack
                    R_matrix = ascon_cpa(partial_traces, H_matrix)

                    # Find the time samples with the maximum correlation value
                    corr_vs_keyguess = np.max(np.abs(R_matrix), axis=1) # shape (8,)

                    # Find the key guess with the maximum correlation value
                    best_key_guess = np.argmax(corr_vs_keyguess)

                    # Order the guesses by their correlation values
                    sorted_indices = np.argsort(-corr_vs_keyguess)  # Descending order
                    rank = np.where(sorted_indices == correct_guess)[0][0]  # 0 = best, 7 = worst
                    # print(f"Key bit index {key_bit}: Correct guess rank = {rank} (0=best, 7=worst)")
                    key_ranks_vs_traces_0[sbox_type][key_bit].append(rank)

                    # Save the result to the k0 vector
                    k0_bits[(key_bit)      % 64] = (best_key_guess >> 2) & 1
                    k0_bits[(key_bit + 19) % 64] = (best_key_guess >> 1) & 1
                    k0_bits[(key_bit + 28) % 64] = (best_key_guess >> 0) & 1

                # Convert the numpy array into a single hex integer
                k0 = 0
                for i in range(64):
                    k0 |= ((k0_bits[i] & 0x01) << i)
                k0 = int(k0) & 0xFFFFFFFFFFFFFFFF
                # print(f"Recovered most significand half of the key: {k0:016x}")
                # print()

                # Check how many bits have been correctly recovered so far
                k0_expected = key & 0xFFFFFFFFFFFFFFFF
                # Compare the recovered k0 with the expected one. The XOR operation returns 1 where bits differ. 
                # So count the 1s to get the number of wrong bits.
                wrong_bits = bin(k0 ^ k0_expected).count('1')
                success_rate = (64 - wrong_bits) / 64 * 100
                success_rate_vs_traces_0[sbox_type].append(success_rate)
                # print(f"Correctly recovered {64 - wrong_bits} out of 64 bits so far ({success_rate:.2f}%).\n")

            # Save the success rate to a JSON file
            with open(f"../x-heep/Graphs/ASCON_c/ASCON_success_rate_S0_sbox_{sbox_type}.json", "w") as f:
                json.dump(success_rate_vs_traces_0[sbox_type], f)
            # Success rate plot
            plot_success_rate_vs_traces(success_rate_vs_traces_0[sbox_type])

            # Save the key rank to a JSON file
            with open(f"../x-heep/Graphs/ASCON_c/ASCON_key_ranks_S0_sbox_{sbox_type}.json", "w") as f:
                json.dump(to_python_types(key_ranks_vs_traces_0[sbox_type]), f)
            # Key rank plot
            plot_key_rank_vs_traces(key_ranks_vs_traces_0[sbox_type], 11)


            print("S1 Key Recovery Phase")
            pbar = tqdm(range(1, (traces.shape[0] // resolution) + 1), desc="Using 0 traces") # Loop over number of traces
            for count in pbar:
                pbar.set_description(f"Using {count*resolution} traces")
                partial_traces = traces[:(count*resolution)]
                partial_nonces = nonces[:(count*resolution)]

                # Iterate over all key bits of k1
                for key_bit in key_bit_indexes_1:
                    key_1_j     = (key_1_correct >> ((key_bit)      % 64)) & 1
                    key_1_j61   = (key_1_correct >> ((key_bit + 61) % 64)) & 1
                    key_1_j39   = (key_1_correct >> ((key_bit + 39) % 64)) & 1
                    correct_guess = (key_1_j << 2) | (key_1_j61 << 1) | (key_1_j39 << 0)

                    # Build the leakage model matrix
                    H_matrix = np.empty((len(partial_nonces), 8), dtype=np.uint8)
                    R_matrix = np.empty((8, partial_traces.shape[1]), dtype=np.float64)

                    for n in range(len(partial_nonces)):
                        nonce_MSB = partial_nonces[n][1]
                        nonce_LSB = partial_nonces[n][0]
                        leakage_model_i = ascon_leakage_model(initialization_vector, nonce_MSB, nonce_LSB, 1, key_bit, sbox_type, k0)
                        H_matrix[n] = leakage_model_i

                    # CPA attack
                    R_matrix = ascon_cpa(partial_traces, H_matrix)

                    # Find the time samples with the maximum correlation value
                    corr_vs_keyguess = np.max(np.abs(R_matrix), axis=1) # shape (8,)

                    # Find the key guess with the maximum correlation value
                    best_key_guess = np.argmax(corr_vs_keyguess)

                    # Order the guesses by their correlation values
                    sorted_indices = np.argsort(-corr_vs_keyguess)  # Descending order
                    rank = np.where(sorted_indices == correct_guess)[0][0]  # 0 = best, 7 = worst
                    key_ranks_vs_traces_1[sbox_type][key_bit].append(rank)

                    # Save the result to the k1 vector
                    k1_bits[(key_bit)      % 64] = (best_key_guess >> 2) & 1
                    k1_bits[(key_bit + 61) % 64] = (best_key_guess >> 1) & 1
                    k1_bits[(key_bit + 39) % 64] = (best_key_guess >> 0) & 1

                # Convert the numpy array into a single hex integer
                k1 = 0
                for i in range(64):
                    k1 |= (k1_bits[i] & 0x01) << i
                k1 = int(k1) & 0xFFFFFFFFFFFFFFFF

                # Check how many bits have been correctly recovered so far
                k1_expected = (key >> 64) & 0xFFFFFFFFFFFFFFFF
                # Compare the recovered k1 with the expected one. The XOR operation returns 1 where bits differ. 
                # So count the 1s to get the number of wrong bits.
                wrong_bits = bin(k1 ^ k1_expected).count('1')
                success_rate = (64 - wrong_bits) / 64 * 100
                success_rate_vs_traces_1[sbox_type].append(success_rate)

            # Save the success rate to a JSON file
            with open(f"../x-heep/Graphs/ASCON_c/ASCON_success_rate_S1_sbox_{sbox_type}.json", "w") as f:
                json.dump(success_rate_vs_traces_1[sbox_type], f)
            # Success rate plot
            plot_success_rate_vs_traces(success_rate_vs_traces_1[sbox_type])

            # Save the key rank to a JSON file
            with open(f"../x-heep/Graphs/ASCON_c/ASCON_key_ranks_S1_sbox_{sbox_type}.json", "w") as f:
                json.dump(to_python_types(key_ranks_vs_traces_1[sbox_type]), f)
            # Key rank plot for k1
            plot_key_rank_vs_traces(key_ranks_vs_traces_1[sbox_type], 46)

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

            if recovered_key != key_for_printing:
                print(f"\033[91mERROR\033[0m: Key recovery failed.\nGot: 0x{recovered_key}\nExpected: 0x{key_for_printing}\n")
            else:
                print("\033[92mSUCCESS\033[0m: Key correctly recovered!\n")

            toc = time.perf_counter()
            print(f"Full key recovery phase completed in {(toc - tic)/60:.2f} minutes.")

except FileNotFoundError:
    print(f"ERROR: Traces file {traces_file} not found. Please run the trace acquisition phase first.")
