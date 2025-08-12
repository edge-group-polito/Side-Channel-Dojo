#!/usr/bin/env python3

import sys
sys.path.append( '../sca_python' )
from analyzer.attack.ascon.xheep_ascon_cpa.ascon_first_round import ascon_first_round

from tqdm import tqdm
import numpy as np
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


traces_file = r"../../build/xheep_test/ASCON_RV32I_traces_nonces_500k.h5"
#traces_file = r"../../build/xheep_test/ASCON_RV32I_traces_nonces_50k.h5"

#TARGET_BIT = 2

key   = "000102030405060708090A0B0C0D0E0F"
# Reverse the key bytes to match X-HEEP's endianness
key_bytes = [key[i:i+2] for i in range(0, len(key), 2)]
key_reversed = ''.join(key_bytes[::-1])
key = int(key_reversed, 16)

try:
    with h5py.File(traces_file, 'r') as f_read_traces:
        traces = f_read_traces['traces'][:500000]#, 2500:3200]
        nonces = f_read_traces['nonces'][:500000]

        # DEBUG
        print(f"Number of traces: {len(traces)}, Number of samples: {len(traces[0])}")

        for TARGET_BIT in tqdm(range(0, 64), desc="Attacking bits"):
            # Divide the traces according to the target bit value of the 
            # output register S0 at the end of the linear diffusion layer.
            label_attacked_bit=[]
            for i in range(0, len(traces)):
                # Reconstruct the nonce from the two halves
                nonce = int(nonces[i][0]) << 64 | int(nonces[i][1])
                # Compute the expected value of the state at the end of the first round
                S = ascon_first_round(key, nonce)
                # if 0 <= i < 2:
                #     print(f"Nonce: {nonce:016X}, S[0]: {S[0]:016X}")
                # Extract the bit of interest from the state register S0 and divide the traces
                # according to its value.
                label_attacked_bit.append((S[0] >> TARGET_BIT) & 0x01)

            #print("Generating the SNR plot for the attacked bit...")
            snr_trace_attacked_bit = return_snr_trace(traces, label_attacked_bit)

            plt.figure(figsize=(14,5))
            # Select 40 equally distributed indices in the range 0-(len(traces)-1)
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

            ax1.set_title(f"SNR trace and overlapped power traces for bit {TARGET_BIT}")
            ax1.set_xlabel('Time sample')
            ax1.set_ylabel('Power', color='gray')
            ax1.tick_params(axis='y', labelcolor='gray')

            plt.savefig("../x-heep/Graphs/ASCON_c/ASCON_SNR_bit_" + str(TARGET_BIT) + "_with_traces.png")
            #plt.show()
            plt.close()



except FileNotFoundError:
    print(f"ERROR: Traces file {traces_file} not found.")
