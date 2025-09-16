#!/usr/bin/env python3

import sys
sys.path.append( '../sca_python' )
from analyzer.attack.ascon.xheep_ascon_cpa.ascon_first_round import ascon_first_round

from tqdm import tqdm
import numpy as np
from multiprocessing import Pool, shared_memory
import time
import matplotlib.pyplot as plt
import h5py

# Utility functions
def prepare_data(trace_set, labels_set):
    """
    trace_set = a set of traces
    labels_set = the leakage model of the target intermediate value
    
    returns a dictionary of the form
       'label_value': list of traces associated with 'label_value'
    """
   
    labels=np.unique(labels_set)
    # Initialize the dictionary
    d={}
    for i in labels:
         d[i]=[]
    for count, label in enumerate(labels_set):
        d[label].append(trace_set[count])
    return d

def return_snr_trace(trace_set, labels_set):
    """
    trace_set = a set of traces
    labels_set = a set of labels of the same lenght as trace_set

    returns a dictionary of the form
       'label_value': mean_sample trace with 'label_value'
    """
    mean_trace={}
    signal_trace=[]
    noise_trace=[]
    # Determine the set of unique values for the leakage model. In this case,
    # the leakage model is the attacked bit, so the labels = {0,1}.
    labels=np.unique(labels_set)
    # Group the traces according to the label
    grouped_traces=prepare_data(trace_set, labels_set)
    # Compute the mean trace (the same are the signal traces)
    for i in labels:
        mean_trace[i]=np.mean(grouped_traces[i], axis=0)
        signal_trace.append(mean_trace[i])
    # Compute the noise trace
    for i in labels:
        for trace in grouped_traces[i]:
            noise_trace.append(trace-mean_trace[i])
    var_noise=np.var(noise_trace, axis=0)
    var_signal=np.var(signal_trace, axis=0)
    snr_trace=var_signal/var_noise
    return snr_trace

# Number of traces
N = 150000
sbox_type = "lut_lu_5" # Options: lut_ascon, lut_bilgin, lut_allouzi, lut_lu_4, lut_lu_5, lut_lu_6, lut_lu_7

#traces_file = r"../../build/xheep_test/ASCON_RV32I_traces_nonces_500k.h5"
#traces_file = r"../../build/xheep_test/ASCON_C_traces_nonces_50k.h5"
traces_file = r"../../build/xheep_test/ascon_opt32_" + sbox_type + "_" + str(N//1000) + "k.h5"

state_register_index = 0 # 0 or 1
shift_amount = [19, 28] if state_register_index == 0 else [61, 39]

key   = "000102030405060708090A0B0C0D0E0F"
# Reverse the key bytes to match X-HEEP's endianness
key_bytes = [key[i:i+2] for i in range(0, len(key), 2)]
key_reversed = ''.join(key_bytes[::-1])
key = int(key_reversed, 16)

verbose = False
plot = False
# This list contains the maximum SNR value for each attacked bit
max_SNR_values = []


def worker(args):
    (TARGET_BIT, shm_traces_name, shm_nonces_name, shape_traces, shape_nonces, dtype_traces, dtype_nonces, key, sbox_type, state_register_index, plot) = args
    import numpy as np
    import matplotlib.pyplot as plt
    from multiprocessing import shared_memory
    from analyzer.attack.ascon.xheep_ascon_cpa.ascon_first_round import ascon_first_round

    # Attach to shared memory
    shm_traces = shared_memory.SharedMemory(name=shm_traces_name)
    shm_nonces = shared_memory.SharedMemory(name=shm_nonces_name)
    traces = np.ndarray(shape_traces, dtype=dtype_traces, buffer=shm_traces.buf)
    nonces = np.ndarray(shape_nonces, dtype=dtype_nonces, buffer=shm_nonces.buf)

    label_attacked_bit = []
    for i in range(len(traces)):
        nonce = int(nonces[i][0]) << 64 | int(nonces[i][1])
        S = ascon_first_round(key, nonce, sbox_type)
        if state_register_index == 0:
            label_attacked_bit.append((S[0] >> TARGET_BIT) & 0x01)
        else:
            label_attacked_bit.append((S[1] >> TARGET_BIT) & 0x01)

    snr_trace_attacked_bit = return_snr_trace(traces, label_attacked_bit)
    max_snr_value = np.max(snr_trace_attacked_bit)

    if plot:
        plt.figure(figsize=(14,5))
        total_traces = len(traces)
        num_traces_to_plot = 40
        indices = np.linspace(0, total_traces-1, num_traces_to_plot, dtype=int)
        for idx in indices:
            plt.plot(traces[idx], color='gray', alpha=0.3, linewidth=0.7)

        ax1 = plt.gca()
        ax2 = ax1.twinx()
        ax2.plot(snr_trace_attacked_bit, color='red', linewidth=2, label='SNR')
        ax2.set_ylabel('SNR value', color='red')
        ax2.tick_params(axis='y', labelcolor='red')

        ax1.set_title(f"SNR trace and overlapped power traces for bit {TARGET_BIT + state_register_index*64}")
        ax1.set_xlabel('Time sample')
        ax1.set_ylabel('Power', color='gray')
        ax1.tick_params(axis='y', labelcolor='gray')

        plt.savefig(f"../x-heep/Graphs/ASCON_c/ASCON_SNR_bit_{TARGET_BIT + state_register_index*64}_with_traces.png")
        plt.close()

    # Clean up shared memory references (do not unlink)
    shm_traces.close()
    shm_nonces.close()
    return max_snr_value

try:
    with h5py.File(traces_file, 'r') as f_read_traces:
        traces = f_read_traces['traces'][:N]
        nonces = f_read_traces['nonces'][:N]

        print(f"Number of traces: {len(traces)}, Number of samples: {len(traces[0])}")

        # Create shared memory for traces and nonces
        shm_traces = shared_memory.SharedMemory(create=True, size=traces.nbytes)
        shm_nonces = shared_memory.SharedMemory(create=True, size=nonces.nbytes)
        shm_traces_np = np.ndarray(traces.shape, dtype=traces.dtype, buffer=shm_traces.buf)
        shm_nonces_np = np.ndarray(nonces.shape, dtype=nonces.dtype, buffer=shm_nonces.buf)
        np.copyto(shm_traces_np, traces)
        np.copyto(shm_nonces_np, nonces)

        # Prepare arguments for each bit
        args_list = []
        for TARGET_BIT in range(0, 64):
            args_list.append((TARGET_BIT, shm_traces.name, shm_nonces.name, traces.shape, nonces.shape, traces.dtype, nonces.dtype, key, sbox_type, state_register_index, plot))

        tic = time.perf_counter()
        # Run multiprocessing pool
        with Pool(4) as pool:
            max_SNR_values = list(tqdm(pool.imap(worker, args_list), total=len(args_list), desc="Attacking bits"))

        toc = time.perf_counter()
        print(f"Processing time: {(toc - tic)/60:.2f} minutes")

        # Cleanup shared memory
        shm_traces.close()
        shm_traces.unlink()
        shm_nonces.close()
        shm_nonces.unlink()

        if verbose:
            print("Maximum SNR values for each attacked bit:")
            for i, max_snr in enumerate(max_SNR_values):
                print(f"Bit {i + state_register_index*64}: {max_snr}")

        # Transform the list of max SNR values into python dictionary where the key is 
        # the bit index and the value is the max_SNR[bit_index]
        max_snr_dict = {i: max_SNR_values[i] for i in range(len(max_SNR_values))}

        # Sort dictionary keys by correlation value (highest to lowest)
        sorted_keys = sorted(max_snr_dict, key=lambda k: max_snr_dict[k], reverse=True)

        bits_to_attack = []
        covered_bits = set()

        for index in sorted_keys:
            bits = {index % 64, (index + shift_amount[0]) % 64, (index + shift_amount[1]) % 64}
            if bits - covered_bits:  # at least one new bit
                bits_to_attack.append(index)
                covered_bits.update(bits)
            if len(covered_bits) == 64:  # all bits covered
                break

        print(f"State register index: {state_register_index}")
        print(f"Number of bits to attack: {len(bits_to_attack)}")
        print(f"Bits to attack: {bits_to_attack}")

except FileNotFoundError:
    print(f"ERROR: Traces file {traces_file} not found.")
