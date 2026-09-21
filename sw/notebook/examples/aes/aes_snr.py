import os
import sys
import time
import numpy as np
import matplotlib.pyplot as plt
import serial.tools.list_ports as port_list

# Use standard tqdm instead of notebook version
from tqdm import trange, tqdm
from Crypto.Cipher import AES
import chipwhisperer as cw
import chipwhisperer.analyzer as cwa

# Adding paths (ensure these paths exist relative to the script execution directory)
sys.path.append( '../../../ciphers/AES_python' )
sys.path.append( '../../../sca_scripts' )
sys.path.append('../../../sca_scripts/utils')
sys.path.append('../../../sca_scripts/analyzer/attack/aes')

# Import custom modules 
from dat_tracereader import dat_tracereader
from pico_api import PS5000aWrapper
from CW305_api import CW305Wrapper
from AES_golden import AES_golden_model
from analyzer.utils.sca_plots import sca_plot
from analyzer.attack.aes.key_schedule import key_schedule_rounds
from sbox_modified_funcs import inv_sbox_lut

# --- Configuration ---
tested_sbox = "sbox_rijandael"
sbox_id = tested_sbox.replace("sbox_", "")

# If capture is set to True, the script will capture data from the PicoScope
capture = False
# If save_dataset is set to True, the script will save the captured data to a .dat file
save_dataset = False

pt_len = 16  # size of the plaintext in bytes
ct_len = 16  # size of the ciphertext in bytes
key_len = 16  # size of the key in bytes
n_trc = 5000  # number of traces to capture or read from dataset

# --- Data Loading / Initialization ---
if not capture:
    try:
        reader = dat_tracereader()
        reader.open_ro("traceset/aes_"+sbox_id+".dat")
        trace, key, plaintext, ciphertext =  reader.read_traces(n_trc)
        num_samples = trace.shape[1]  # number of samples per trace
        reader.close()
    except Exception as e:
        print("Error loading dataset: ", e)
else: 
    # Allocate memory for traces and data
    num_samples = 1612
    trace = np.empty((n_trc, num_samples), dtype=np.float64)  
    plaintext = np.empty((n_trc, pt_len), dtype=np.uint8)  
    ciphertext = np.empty((n_trc, ct_len), dtype=np.uint8)  
    key = np.empty(key_len, dtype=np.uint8) 

# --- Optional online phase : AES power traces capture ---
if capture:
    bitstream = r"../../../../hw/fpga/bitstream/aes/aes_single_round/cw305_top_"+sbox_id+"_lut.bit"

    try:
        ps = PS5000aWrapper()
        ps.get_unitInfo()
        ps.scope_setup()
        num_samples = ps.nSamples
        cw305 = CW305Wrapper(ps, bitstream)
    except ModuleNotFoundError as e:
        print(e)
    
    ktp = cw.ktp.Basic()
    key, plaintext[0] = ktp.next()

    cipher = AES_golden_model()
    formatted_key = ''.join(format(el, '02x') for el in key)
    print("Key: ", [ hex(subkey) for subkey in key])

    cw305.set_key(key)
    cw305.capture_trace(plaintext[0])

    for i in trange(n_trc, desc='Capturing traces'):
        ciphertext[i], trace[i] = cw305.capture_trace(plaintext[i])
        formatted_pt = (format(el, '02x') for el in plaintext[i])
        text = [int(subbyte, 16) for subbyte in formatted_pt]
        assert (list(ciphertext[i]) == list(cipher.encrypt(formatted_key, text, tested_sbox))), "Incorrect encryption result!\nGot {}\nExp {}\n".format(list(ciphertext[i]), list(plaintext[i]))
        if (i < n_trc-1):
            _ , plaintext[i+1] = ktp.next() 

    cw305.dis()
    ps.dis()

    if (save_dataset):
        try:
            writer = dat_tracereader()
            key = np.array(key, dtype=np.uint8)
            writer.create(
                pathname="dataset/aes_"+sbox_id+".dat",
                trace_len=int(num_samples),
                sample_type='d',
                key_len=key_len,
                plaintext_len=pt_len,
                ciphertext_len=ct_len
            )
            writer.write_traces(trace, key, plaintext, ciphertext)
            print("Traces written:", writer.num_traces)
            writer.close()
        except Exception as e:
            print("Error saving dataset: ", e)

# Ensure the log directory exists
os.makedirs("log", exist_ok=True)

# --- Plotting power traces ---
try:
    sca_plt = sca_plot()
    power_plt = sca_plt.power_traces_overlapped(traces=list(trace), finish=800)
    power_plt.savefig(f"log/power_traces_overlapped_{tested_sbox}.pdf", format='pdf')
    print("Power traces plot saved successfully.")
except NameError as e:
     print(f"Plotting skipped due to missing variables or modules: {e}")

# --- SNR AES ---
try:
    key_last_round = np.array(key_schedule_rounds(key, 0, 10, tested_sbox), dtype=np.uint8)
    print("Last round key :\n", [hex(subkey) for subkey in key_last_round])

    def prepare_data(trace_set, labels_set):
        labels=np.unique(labels_set)
        d={}
        for i in labels:
             d[i]=[]
        for count, label in enumerate(labels_set):
            d[label].append(trace_set[count])
        return d

    def return_snr_trace(trace_set, labels_set):
        mean_trace={}
        signal_trace=[]
        noise_trace=[]
        labels=np.unique(labels_set) 
        grouped_traces=prepare_data(trace_set, labels_set) 
        for i in labels:
            mean_trace[i]=np.mean(grouped_traces[i], axis=0)
            signal_trace.append(mean_trace[i]) 
        for i in labels:
            for t in grouped_traces[i]:
                noise_trace.append(t-mean_trace[i])
        var_noise=np.var(noise_trace, axis=0)
        var_signal=np.var(signal_trace, axis=0)
        snr_trace=var_signal/var_noise  
        return snr_trace   

    TARGET_BYTE = 1  
    SHIFT_undo = [0, 13, 10, 7, 4, 1, 14, 11, 8, 5, 2, 15, 12, 9, 6, 3]

    def compute_round9_byte(ct: np.ndarray, key_round10: np.ndarray, bnum: int, verbose: bool = False) -> np.ndarray:
        if (ct.dtype != np.uint8) & (key_round10.dtype != np.uint8):
            raise TypeError("ct and key must have dtype uint8.")
        
        n_traces = ct.shape[0]
        round9_byte = np.empty(n_traces, dtype=np.uint8) 
        st10_bsl = np.empty(16, dtype=np.uint8)

        loop_range = tqdm(range(n_traces), desc='Computing output byte value') if verbose else range(n_traces)
        
        for i in loop_range:
            st10 = ct[i] ^ key_round10 
            for j in range(16):
                st10_bsl[j] = st10[SHIFT_undo[j]]
            st9 = np.uint8(inv_sbox_lut(st10_bsl[bnum], tested_sbox))
            round9_byte[i] = st9
        return round9_byte

    round9_byte = compute_round9_byte(ciphertext, key_last_round, TARGET_BYTE)

    # --- LSB ---
    label_LSB=[] 
    for i in tqdm(range(0, n_trc), desc='Preparing LSB labels'):
        label_LSB.append(round9_byte[i]&0b1)
    snr_trace_LSB=return_snr_trace(trace, label_LSB)

    # --- LS2B ---
    label_LS2B=[]
    for i in tqdm(range(0, n_trc), desc='Preparing LS2B labels'):
        label_LS2B.append(round9_byte[i]&0b11)
    snr_trace_LS2B=return_snr_trace(trace, label_LS2B)
    
    plt.figure(figsize=(14,5))
    plt.plot(snr_trace_LS2B[50:600])
    plt.title("SNR trace for LS2B leakage model")
    plt.xlabel('Time sample')
    plt.ylabel('SNR value')
    plt.axvline(x=490, color='red', linestyle='--', label='start round 10')
    plt.axvline(x=550, color='red', linestyle='--', label='end round 10')
    plt.legend()
    plt.savefig("log/SNR_LS2B.pdf", format="pdf")
    plt.show()

    # --- MSB ---
    label_MSB=[] 
    for i in tqdm(range(0, n_trc), desc='Preparing MSB labels'):
        label_MSB.append(round9_byte[i]&0b10000000)

    snr_trace_MSB=return_snr_trace(trace, label_MSB)
    plt.figure(figsize=(14,5))
    plt.plot(snr_trace_MSB[50:600])
    plt.title("SNR trace for MSB leakage model")
    plt.xlabel('Time sample')
    plt.ylabel('SNR value')
    plt.axvline(x=490, color='red', linestyle='--', label='start round 10')
    plt.axvline(x=550, color='red', linestyle='--', label='end round 10')
    plt.legend()
    plt.savefig("log/SNR_MSB.pdf", format="pdf")
    plt.show()

    # --- HW / HD ---
    def HW(x):
        return sum([x&(1<<i)>0 for i in range(32)])

    def hamming_distance(a,b):
        return HW(a^b)

    label_HD=[] 
    for i in tqdm(range(0, n_trc), desc='Preparing HD labels'):
        label_HD.append(hamming_distance(round9_byte[i], ciphertext[i, TARGET_BYTE]))
        
    snr_trace_HD=return_snr_trace(trace, label_HD)
    plt.figure(figsize=(14,5))
    plt.plot(snr_trace_HD[50:600])
    plt.title("SNR trace for HD leakage model")
    plt.xlabel('Time sample')
    plt.ylabel('SNR value')
    plt.axvline(x=490, color='red', linestyle='--', label='start round 10')
    plt.axvline(x=550, color='red', linestyle='--', label='end round 10')
    plt.legend()
    plt.savefig("log/SNR_HD.pdf", format="pdf")
    plt.show()

    # --- ID ---
    label_ID=[] 
    for i in tqdm(range(0, n_trc), desc='Preparing ID labels'):
        label_ID.append(round9_byte[i])
        
    snr_trace_ID=return_snr_trace(trace, label_ID)

    plt.figure(figsize=(14,5))
    plt.plot(snr_trace_ID[50:600])
    plt.title("SNR trace for ID leakage model")
    plt.xlabel('Time sample')
    plt.ylabel('SNR value')
    plt.axvline(x=490, color='red', linestyle='--', label='start round 10')
    plt.axvline(x=550, color='red', linestyle='--', label='end round 10')
    plt.legend()
    plt.savefig("log/SNR_ID.pdf", format="pdf")
    plt.show()

    # --- Combined Plot ---
    plt.figure(figsize=(14,5))

    # Plot all traces in gray with low alpha
    plt.plot(snr_trace_LSB[50:600], color='gray', alpha=0.3, label='LSB')
    plt.plot(snr_trace_LS2B[50:600], color='gray', alpha=0.3, label='LS2B')
    plt.plot(snr_trace_MSB[50:600], color='gray', alpha=0.3, label='MSB')
    plt.plot(snr_trace_ID[50:600], color='gray', alpha=0.3, label='ID')

    # Plot HD trace in blue, more visible
    plt.plot(snr_trace_HD[50:600], color='blue', alpha=1.0, label='HD')

    # Find the index and value of the max SNR in HD trace (in the plotted window)
    window = slice(50, 600)
    snr_hd_window = snr_trace_HD[window]
    max_idx = np.argmax(snr_hd_window)
    max_val = snr_hd_window[max_idx]

    # Plot a circle at the max point
    plt.scatter([max_idx], [max_val], color='red', s=20, marker='o', label='Max SNR (HD)')

    plt.title("SNR traces for different leakage models")
    plt.xlabel('Time sample')
    plt.ylabel('SNR value')
    plt.axvline(x=490, color='red', linestyle='--', label='start round 10')
    plt.axvline(x=550, color='red', linestyle='--', label='end round 10')
    plt.legend()
    
    # Save the combined plot
    plt.savefig("log/SNR_all_models.pdf", format="pdf")
    plt.show()

    print("All SNR Trace Calculations and Plot Generation Complete.")

except NameError as e:
    print(f"SNR calculation skipped due to missing variables or modules: {e}")