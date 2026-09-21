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
from sbox_modified_funcs import sbox_lut, inv_sbox_lut
from analyzer.attack.aes.SBox_leakage_models import AES128SboxResistantLeakageModels


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

    ## ------- Other case
    def calculate_snr(traces, plaintexts, ciphertexts, leak_model, keys=None, bnum=0, db=False):
        """
        Calculate the Signal-to-Noise Ratio (SNR) using standard partitioning by leakage value.

        Formula: Var(E[Traces | Leakage]) / E[Var(Traces | Leakage)]

        Args:
            traces (np.ndarray): Shape (N, n_samples)
            plaintexts (np.ndarray): Shape (N, 16)
            ciphertexts (np.ndarray): Shape (N, 16)
            leak_model: Leakage model instance implementing .leakage(textin, textout, None, bnum, state)
            keys (np.ndarray, optional): Shape (N, 16) or (16,) if key is required by the leakage model.
            bnum (int): Target byte index (0-15).
            db (bool): Return SNR in decibels (10 * log10(SNR)).

        Returns:
            np.ndarray: SNR curve across all sample points (shape: (n_samples,)).
        """
        n_traces, n_samples = traces.shape

        # 1. Compute leakage values for all traces
        leakages = np.zeros(n_traces, dtype=int)
        for i in range(n_traces):
            pt = plaintexts[i] if plaintexts is not None else None
            ct = ciphertexts[i] if ciphertexts is not None else None
            k = keys[i] if (keys is not None and keys.ndim > 1) else keys

            state = {'knownkey': k}
            leakages[i] = int(leak_model.leakage(pt, ct, None, bnum, state))

        # 2. Partition traces by leakage value
        unique_vals, counts = np.unique(leakages, return_counts=True)

        group_means = []
        group_vars = []
        valid_counts = []

        for val, count in zip(unique_vals, counts):
            # Only evaluate classes with > 1 trace to compute variance
            if count > 1:
                group_traces = traces[leakages == val]
                group_means.append(np.mean(group_traces, axis=0))
                group_vars.append(np.var(group_traces, axis=0, ddof=1))
                valid_counts.append(count)

        group_means = np.array(group_means) # Shape: (n_classes, n_samples)
        group_vars = np.array(group_vars)   # Shape: (n_classes, n_samples)
        valid_counts = np.array(valid_counts)

        # 3. Compute Signal (variance of class means) and Noise (pooled within-class variance)
        # Signal: Var(E[T|L])
        signal_var = np.var(group_means, axis=0)

        # Noise: Pooled average within-class variance E[Var(T|L)]
        # Weighted by degrees of freedom (N_i - 1)
        weights = (valid_counts - 1)[:, np.newaxis]
        noise_var = np.sum(group_vars * weights, axis=0) / np.sum(valid_counts - 1)

        # Prevent division by zero
        noise_var = np.where(noise_var == 0, np.nan, noise_var)
        snr = signal_var / noise_var

        if db:
            return 10 * np.log10(snr)

        return snr

    
    # --- HW / HD Utility ---
    def HW(x):
        return sum([x&(1<<i)>0 for i in range(32)])

    def hamming_distance(a,b):
        return HW(a^b)

    # ==========================================
    # 1. FIRST ROUND SNR (HD Leakage)
    # ==========================================
    #label_pt_HD = [] 
    #for i in tqdm(range(0, n_trc), desc='Preparing HD labels of First Round'):
    #    # Safely handle 1D or 2D key arrays based on how traces were loaded
    #    k_byte = key[i, TARGET_BYTE] if key.ndim == 2 else key[TARGET_BYTE]
    #    
    #    # Calculate SBox output for the first round
    #    sbox_out = sbox_lut(plaintext[i, TARGET_BYTE] ^ k_byte, tested_sbox)
    #    label_pt_HD.append(hamming_distance(plaintext[i, TARGET_BYTE], sbox_out))
    #snr_pt = return_snr_trace(trace, label_pt_HD)

        # 1. Plaintext-associated leakage (First Round S-Box)
    leak_model_pt = AES128SboxResistantLeakageModels().FirstRound_ModifiedSbox_Output(tested_sbox)
    snr_pt = calculate_snr(trace, plaintext, ciphertext, leak_model=leak_model_pt, keys=key, bnum=TARGET_BYTE, db=True)
    
    # Plot First Round SNR separately
    plt.figure(figsize=(14,5))
    plt.plot(snr_pt[50:650], color='green', label='First Round SNR')
    plt.title("SNR trace for First Round (HD leakage model)")
    plt.xlabel('Samples')
    plt.ylabel('SNR value')
    plt.legend()
    plt.savefig("log/SNR_HD_First_Round.pdf", format="pdf")
    #plt.show()

    # ==========================================
    # 2. LAST ROUND SNR (HD Leakage)
    # ==========================================
    label_ct_HD = [] 
    for i in tqdm(range(0, n_trc), desc='Preparing HD labels of Last Round'):
        label_ct_HD.append(hamming_distance(round9_byte[i], ciphertext[i, TARGET_BYTE]))
        
    snr_trace_ct = return_snr_trace(trace, label_ct_HD)
    snr_trace_ct_dB = 10 * np.log10(snr_trace_ct)
    
    # Plot Last Round SNR separately
    plt.figure(figsize=(14,5))
    plt.plot(snr_trace_ct_dB[50:60], color='blue', label='Last Round SNR')
    plt.title("SNR trace for Last Round (HD leakage model)")
    plt.xlabel('Time sample')
    plt.ylabel('SNR value')
    plt.axvline(x=490, color='red', linestyle='--', label='start round 10')
    plt.axvline(x=550, color='red', linestyle='--', label='end round 10')
    plt.legend()
    plt.savefig("log/SNR_HD_Last_Round.pdf", format="pdf")
    #plt.show()

    # ==========================================
    # 3. OVERLAPPED PLOT (First Round & Last Round)
    # ==========================================
    plt.figure(figsize=(14,5))

    # Plot both traces
    plt.plot(snr_pt[50:650], color='#EE9B00', alpha=0.8, label='SNR of Plaintext')
    plt.plot(snr_trace_ct_dB[50:650], color='#AE2012', alpha=0.8, label='SNR of Ciphertext')

    # Find the index and value of the max SNR in HD trace for Last Round
    window = slice(0, 800)
    snr_hd_window = snr_trace_ct_dB[window]
    max_idx_last = np.argmax(snr_hd_window)
    max_val_last = snr_hd_window[max_idx_last]
    #plt.scatter([max_idx_last], [max_val_last], color='#005F73', s=30, marker='o', label='Max SNR (Last Round)', zorder=5)

    # Find the index and value of the max SNR in HD trace for First Round
    snr_pt_window = snr_pt[window]
    max_idx_first = np.argmax(snr_pt_window)
    max_val_first = snr_pt_window[max_idx_first]
    #plt.scatter([max_idx_first], [max_val_first], color='orange', s=30, marker='o', label='Max SNR (First Round)', zorder=5)

    #plt.title("SNR traces Overlapped (First Round vs. Last Round)")
    plt.xlabel('Time sample', fontweight='bold', fontsize=17, labelpad=12)
    plt.ylabel('SNR value', fontweight='bold', fontsize=17, labelpad=12)
    plt.axvline(x=490, color='#005F73', linestyle='--', label='Start round 10')
    plt.axvline(x=550, color='#005F73', linestyle='--', label='End round 10')
    plt.legend(fontsize=17)
    plt.tight_layout()
    plt.savefig("log/SNR_pt_Vs_ct_in_HW.pdf", format="pdf", bbox_inches='tight')
    #plt.show()

    print("All SNR Trace Calculations and Plot Generation Complete.")

except NameError as e:
    print(f"SNR calculation skipped due to missing variables or modules: {e}")