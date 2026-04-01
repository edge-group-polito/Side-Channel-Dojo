#!/usr/bin/env python3


import sys
sys.path.append( '../sca_scripts' )
sys.path.append( '../x-heep' )

from tqdm import tqdm
import time
import numpy as np
import h5py
import multiprocessing as mp
from multiprocessing import shared_memory

from sw.sca_scripts.analyzer.attack.ascon.xheep_ascon_cpa.ascon_std_leakage_model import ascon_std_leakage_model
from analyzer.attack.ascon.xheep_ascon_cpa.ascon_cpa import ascon_cpa

###################### INITIALIZATION ######################

# Number of traces
N = 10000
sbox_type = "lut_ascon" # Options: lut_ascon, lut_bilgin, lut_allouzi, lut_lu_4, lut_lu_5, lut_lu_6, lut_lu_7

cpa_phase_full_key = True

# Traces file path
traces_dir  = r"../../build/xheep_test/"
# traces_file = r"../../build/xheep_test/ASCON_RV32I_traces_nonces_500k.h5"
traces_file = r"../../build/xheep_test/ascon_opt32_" + sbox_type + "_" + str(N//1000) + "k.h5"

print()
print("traces_file: ", traces_file)
print()

# Initialize key and nonce
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

# Load the traces from the file, if it exists
try:
    with h5py.File(traces_file, 'r') as f_read_traces:
        # Read the first 50000 traces and nonces. It is better to use the slicing
        # operator even to load the whole dataset, since with the h5 format 
        # data is read from the disk each time. The slicing operator forces the data 
        # to be loaded into the RAM.
        traces = f_read_traces['traces'][:N]
        nonces = f_read_traces['nonces'][:N]
        # Ensure arrays are contiguous and C-ordered
        traces = np.ascontiguousarray(traces, dtype=np.float64)
        nonces = np.ascontiguousarray(nonces, dtype=np.uint64)


        # Sanity check: traces and nonces should have the same number of rows
        if traces.shape[0] != nonces.shape[0]:
            raise ValueError("Number of traces and nonces do not match. Please capture the traces again.")


        if cpa_phase_full_key:

            # Full key recovery phase
            print("Starting full key recovery phase...")

            # Print the number of traces and the number of samples for each trace
            print(f"Number of traces: {traces.shape[0]}")
            print(f"Number of samples per trace: {traces.shape[1]}")
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

            # --- Multiprocessing parallel CPA attack ---
            def cpa_worker_k0(args):
                key_bit, traces_shape, nonces_shape, traces_shm_name, nonces_shm_name, initialization_vector, sbox_type = args
                traces_shm = shared_memory.SharedMemory(name=traces_shm_name)
                nonces_shm = shared_memory.SharedMemory(name=nonces_shm_name)
                traces = np.ndarray(traces_shape, dtype=np.float64, buffer=traces_shm.buf, order='C')
                nonces = np.ndarray(nonces_shape, dtype=np.uint64, buffer=nonces_shm.buf, order='C')
                H_matrix = np.empty((nonces.shape[0], 8), dtype=np.uint8)
                for n in range(nonces.shape[0]):
                    nonce_MSB = nonces[n][1]
                    nonce_LSB = nonces[n][0]
                    leakage_model_i = ascon_std_leakage_model(initialization_vector, nonce_MSB, nonce_LSB, 0, key_bit)
                    H_matrix[n] = leakage_model_i
                R_matrix = ascon_cpa(traces, H_matrix)
                corr_vs_keyguess = np.max(np.abs(R_matrix), axis=1)
                best_key_guess = np.argmax(corr_vs_keyguess)
                traces_shm.close()
                nonces_shm.close()
                return (key_bit, best_key_guess)

            def cpa_worker_k1(args):
                key_bit, traces_shape, nonces_shape, traces_shm_name, nonces_shm_name, initialization_vector, sbox_type, k0 = args
                traces_shm = shared_memory.SharedMemory(name=traces_shm_name)
                nonces_shm = shared_memory.SharedMemory(name=nonces_shm_name)
                traces = np.ndarray(traces_shape, dtype=np.float64, buffer=traces_shm.buf, order='C')
                nonces = np.ndarray(nonces_shape, dtype=np.uint64, buffer=nonces_shm.buf, order='C')
                H_matrix = np.empty((nonces.shape[0], 8), dtype=np.uint8)
                for n in range(nonces.shape[0]):
                    nonce_MSB = nonces[n][1]
                    nonce_LSB = nonces[n][0]
                    leakage_model_i = ascon_std_leakage_model(initialization_vector, nonce_MSB, nonce_LSB, 1, key_bit, k0)
                    H_matrix[n] = leakage_model_i
                R_matrix = ascon_cpa(traces, H_matrix)
                corr_vs_keyguess = np.max(np.abs(R_matrix), axis=1)
                best_key_guess = np.argmax(corr_vs_keyguess)
                traces_shm.close()
                nonces_shm.close()
                return (key_bit, best_key_guess)

            # Prepare shared memory for traces and nonces
            traces_shm = shared_memory.SharedMemory(create=True, size=traces.nbytes)
            nonces_shm = shared_memory.SharedMemory(create=True, size=nonces.nbytes)
            traces_shared = np.ndarray(traces.shape, dtype=traces.dtype, buffer=traces_shm.buf)
            nonces_shared = np.ndarray(nonces.shape, dtype=nonces.dtype, buffer=nonces_shm.buf)
            traces_shared[:] = traces[:]
            nonces_shared[:] = nonces[:]

            k0_bits = np.zeros(64, dtype=np.uint8)
            k1_bits = np.zeros(64, dtype=np.uint8)

            tic = time.perf_counter()
            print()

            # --- Parallel CPA for k0 ---
            args_list_k0 = [
                (key_bit, traces.shape, nonces.shape, traces_shm.name, nonces_shm.name, initialization_vector, sbox_type)
                for key_bit in key_bit_indexes_0
            ]
            with mp.Pool(4) as pool:
                results_k0 = list(tqdm(pool.imap(cpa_worker_k0, args_list_k0), total=len(args_list_k0), desc="Key bit recovery progress (k0)"))

            for key_bit, best_key_guess in results_k0:
                k0_bits[(key_bit)      % 64] = (best_key_guess >> 2) & 1
                k0_bits[(key_bit + 19) % 64] = (best_key_guess >> 1) & 1
                k0_bits[(key_bit + 28) % 64] = (best_key_guess >> 0) & 1

            k0 = 0
            for i in range(64):
                k0 |= ((k0_bits[i] & 0x01) << i)
            k0 = int(k0) & 0xFFFFFFFFFFFFFFFF
            print(f"Recovered most significand half of the key: {k0:016x}")
            print()

            # --- Parallel CPA for k1 ---
            args_list_k1 = [
                (key_bit, traces.shape, nonces.shape, traces_shm.name, nonces_shm.name, initialization_vector, sbox_type, k0)
                for key_bit in key_bit_indexes_1
            ]
            with mp.Pool(4) as pool:
                results_k1 = list(tqdm(pool.imap(cpa_worker_k1, args_list_k1), total=len(args_list_k1), desc="Key bit recovery progress (k1)"))

            for key_bit, best_key_guess in results_k1:
                k1_bits[(key_bit)      % 64] = (best_key_guess >> 2) & 1
                k1_bits[(key_bit + 61) % 64] = (best_key_guess >> 1) & 1
                k1_bits[(key_bit + 39) % 64] = (best_key_guess >> 0) & 1

            k1 = 0
            for i in range(64):
                k1 |= (k1_bits[i] & 0x01) << i
            k1 = int(k1) & 0xFFFFFFFFFFFFFFFF
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

            # The strange symbols are for coloring the output in red (error) or green (success)
            if recovered_key != key_for_printing:
                print(f"\033[91mERROR\033[0m: Key recovery failed.\nGot: 0x{recovered_key}\nExpected: 0x{key_for_printing}\n")
            else:
                print("\033[92mSUCCESS\033[0m: Key correctly recovered!\n")

            toc = time.perf_counter()
            print(f"Full key recovery phase completed in {(toc - tic)/60:.2f} minutes.")

            # Clean up shared memory
            traces_shm.close()
            traces_shm.unlink()
            nonces_shm.close()
            nonces_shm.unlink()

except FileNotFoundError:
    print(f"ERROR: Traces file {traces_file} not found. Please run the trace acquisition phase first.")
