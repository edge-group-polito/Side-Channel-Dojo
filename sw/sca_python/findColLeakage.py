from IncrementalStats import IncrementalStatsMath
import pandas as pd
import numpy as np
from IPython.display import display, clear_output, HTML
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import threading
from multiprocessing.pool import ThreadPool
from scipy.stats import t

def bytearray_to_bitlist(byte_array):
    bit_list = []
    for byte in byte_array:
        bits = bin(byte)[2:].zfill(8)
        bit_list.extend([int(bit) for bit in bits])
    return bit_list

def bit_to_hex(x0, x1, x2, x3, x4):
    bitlist = []
    bitlist.append(x0)
    bitlist.append(x1)
    bitlist.append(x2)
    bitlist.append(x3)
    bitlist.append(x4)
    return int(''.join(str(bit) for bit in bitlist), 2)

def hex_to_bit(value):
    binary_string = format(value, f'05b')
    bitlist = [int(bit) for bit in binary_string]
    return bitlist

def check_coverage(indices):
    covered_positions = set()
    
    for i in indices:
        pos1 = i
        pos2 = (i - 19) % 64
        pos3 = (i - 28) % 64
        
        covered_positions.update([pos1, pos2, pos3])
    
    all_positions = set(range(64))
    
    uncovered_positions = all_positions - covered_positions
    
    if uncovered_positions:
        print("The following bits are not covered:", sorted(uncovered_positions))
        return 0
    else:
        print("All bits are covered.")
        return 1
    
def convert_to_hex(bit_list):
    hex_string = ""
    
    for i in range(0, len(bit_list), 8):
        byte_bits = bit_list[i:i+8]
        byte_str = ''.join(str(bit) for bit in byte_bits)
        byte_int = int(byte_str, 2)
        hex_string += format(byte_int, '02X')
    
    return hex_string

def highlight_bits(x):
    global show_key
    color_list = []
    for row_index in range(len(x)):
        color_row = [""] * 16
        if row_index % 2 == 1:
            for i in range(16):
                if x.iloc[row_index, i] == show_key[row_index // 2][i]:
                    color_row[i] = "color: green"
                else:
                    color_row[i] = "color: red"
        color_list.append(color_row)
    return pd.DataFrame(color_list, index=x.index, columns=x.columns)

def create_table(t_value):
    table_data = []
    number_bit = list(range(64))
    show_number_bit = [number_bit[0:8], number_bit[8:16], number_bit[16:24], number_bit[24:32], number_bit[32:40], number_bit[40:48], number_bit[48:56], number_bit[56:64]]
    show_t_value = [t_value[0:8], t_value[8:16], t_value[16:24], t_value[24:32], t_value[32:40], t_value[40:48], t_value[48:56], t_value[56:64]]
    
    for row in range(8):
        table_line = []
        for column in range(8):
            table_line.append(show_number_bit[row][column])
        table_data.append(table_line)
        table_line = []
        for column in range(8):
            table_line.append(show_t_value[row][column])
        table_data.append(table_line)
    
    df = pd.DataFrame(table_data)

    return df

def create_table_3(show_list):
    table_data = []
        
    for row in range(4):
        row_data = list(range(127-16*row, 128-16*row - 17, -1))
        table_data.append(row_data)
        table_data.append(show_list[row])
    
    df = pd.DataFrame(table_data)

    return df

class leak_t_value:
    def __init__(self, key, iv=[0x80, 0x40, 0x0c, 0x06, 0x00, 0x00, 0x00, 0x00], c_r=[0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xf0]):
        self.iv_bit = bytearray_to_bitlist(iv)[::-1]
        self.c_r_bit = bytearray_to_bitlist(c_r)[::-1]
        self.key_bit = bytearray_to_bitlist(key)[::-1]
        self.sbox = {"hw" : [
        0x04, 0x0b, 0x1f, 0x14, 0x1a, 0x15, 0x09, 0x02, 0x1b, 0x05, 0x08, 0x12, 0x1d, 0x03, 0x06, 0x1c,
        0x1e, 0x13, 0x07, 0x0e, 0x00, 0x0d, 0x11, 0x18, 0x10, 0x0c, 0x01, 0x19, 0x16, 0x0a, 0x0f, 0x17], 
                "lut_ascon" : [
        0x04, 0x0b, 0x1f, 0x14, 0x1a, 0x15, 0x09, 0x02, 0x1b, 0x05, 0x08, 0x12, 0x1d, 0x03, 0x06, 0x1c,
        0x1e, 0x13, 0x07, 0x0e, 0x00, 0x0d, 0x11, 0x18, 0x10, 0x0c, 0x01, 0x19, 0x16, 0x0a, 0x0f, 0x17],
                "lut_bilgin" : [
        0x01, 0x00, 0x19, 0x1a, 0x11, 0x1d, 0x15, 0x1b, 0x14, 0x05, 0x04, 0x17, 0x0e, 0x12, 0x02, 0x1c,
        0x0f, 0x08, 0x06, 0x03, 0x0d, 0x07, 0x18, 0x10, 0x1e, 0x09, 0x1f, 0x0a, 0x16, 0x0c, 0x0b, 0x13],
                "lut_allouzi" : [
        0x10, 0x0e, 0x0d, 0x02, 0x0b, 0x11, 0x15, 0x1e, 0x07, 0x18, 0x12, 0x1c, 0x1a, 0x01, 0x0c, 0x06,
        0x1f, 0x19, 0x00, 0x17, 0x14, 0x16, 0x08, 0x1b, 0x04, 0x03, 0x13, 0x05, 0x09, 0x0a, 0x1d, 0x0f],
                "lut_lu_4" : [
        0x18, 0x09, 0x1b, 0x06, 0x03, 0x1f, 0x16, 0x01, 0x14, 0x1e, 0x08, 0x05, 0x0a, 0x15, 0x0f, 0x10,
        0x04, 0x13, 0x17, 0x0c, 0x1c, 0x00, 0x0d, 0x1a, 0x07, 0x0b, 0x19, 0x12, 0x11, 0x14, 0x02, 0x1d],
                "lut_lu_5" : [
        0x17, 0x1c, 0x0f, 0x10, 0x02, 0x01, 0x15, 0x1e, 0x19, 0x13, 0x12, 0x0c, 0x0b, 0x08, 0x0d, 0x06,
        0x18, 0x0e, 0x00, 0x03, 0x05, 0x1d, 0x0a, 0x1b, 0x04, 0x07, 0x1f, 0x09, 0x1a, 0x16, 0x14, 0x11],
                "lut_lu_6" : [
        0x03, 0x0d, 0x1a, 0x16, 0x11, 0x02, 0x0f, 0x15, 0x00, 0x17, 0x0c, 0x09, 0x14, 0x19, 0x1e, 0x0a,
        0x1b, 0x0e, 0x04, 0x1d, 0x1c, 0x08, 0x01, 0x12, 0x07, 0x18, 0x10, 0x13, 0x1f, 0x06, 0x0b, 0x05],
                "lut_lu_7" : [
        0x16, 0x0f, 0x10, 0x09, 0x1b, 0x03, 0x05, 0x06, 0x01, 0x15, 0x1e, 0x12, 0x1c, 0x08, 0x0a, 0x1d,
        0x0e, 0x00, 0x0d, 0x1a, 0x18, 0x14, 0x11, 0x1f, 0x13, 0x0c, 0x07, 0x19, 0x0b, 0x17, 0x04, 0x02]
        }
        self.HW = [bin(n).count("1") for n in range(0, 2**3)]
        
    def find_col_leakage(self, traces, nonces, sub_layer_type, verbose=False):
        
        t_value_tot = [[0] for _ in range(64)]
        bit_col = list(range(64))
        x0_col = []
        
        #with ThreadPool() as pool:
        #        results = [
        #            pool.apply_async(self.leak_indexes, args=(traces, nonces, sub_layer_type, bitnum, t_value_tot))
        #            for bitnum in range(64)
        #        ]
        #        for result in results:
        #            result.get()  # wait for each thread to complete
        
        for bitnum in range(64):
            self.leak_indexes(traces, nonces, sub_layer_type, bitnum, t_value_tot)
            if verbose:
                self.display_results(t_value_tot, bitnum)
                
        sorted_col = sorted(range(len(t_value_tot)), key=lambda i: t_value_tot[i], reverse=True)
        for col_n in sorted_col:
            if col_n in bit_col:
                x0_col.append(col_n)
                bit_col.remove(col_n)
                if ((col_n - 19) % 64) in bit_col:
                    bit_col.remove((col_n - 19) % 64)
                if ((col_n - 28) % 64) in bit_col:
                    bit_col.remove((col_n - 28) % 64)
        
        if check_coverage(x0_col):
            return x0_col
        else:
            return 0
    
    def leak_indexes(self, traces, nonces, sub_layer_type, bitnum, t_value_tot):
        numtraces = np.shape(traces)[0]
        callback = 25
        
        n = 0
        mean_X = [[0] for _ in range(2**3)]
        M2_X = [[0] for _ in range(2**3)]
        std_dev_X = [[0] for _ in range(2**3)]
        self.stats = [IncrementalStatsMath() for _ in range(2**3)]
        
        for cb in range(0,numtraces, callback):
            callback_traces = traces[cb:cb+callback]
            callback_nonces = nonces[cb:cb+callback]

            maxcpa = [0] * (2**3)
            threads = []
            t_value = [0 for _ in range(2**3)]

            for kguess in range(0, 2**3):
                thread = threading.Thread(target=self.key_correlation, args=(bitnum, kguess, callback_traces, callback_nonces, sub_layer_type, maxcpa))
                thread.start()
                threads.append(thread)
                
            for thread in threads:
                thread.join()

            n += 1
            for i in range(2**3):
                deltaX = maxcpa[i] - mean_X[i]
                mean_X[i] += deltaX / n
                delta2X = maxcpa[i] - mean_X[i]
                M2_X[i] += deltaX * delta2X
                std_dev_X[i] = np.sqrt(M2_X[i] / (n - 1))

            for Ha in range(2**3):
                for Hb in range(2**3):
                    if Ha != Hb:
                        t_value[Ha] += (mean_X[Ha] - mean_X[Hb])/(np.sqrt((std_dev_X[Ha]**2)/n+(std_dev_X[Hb]**2)/n))
                        
        for i in range(2**3):
                t_value_tot[bitnum] += abs(t_value[i])
    
    def key_correlation(self, bitnum, kguess, traces, nonces, sub_layer_type, maxcpa):
        def sub_layer(x1, x2, x3, x4, bitnum, rs, sub_layer_type):
            return hex_to_bit(self.sbox[sub_layer_type][bit_to_hex(self.iv_bit[(bitnum + rs) % 64], x1, x2^self.c_r_bit[(bitnum + rs) % 64], x3[(bitnum + rs) % 64], x4[(bitnum + rs) % 64])])
        
        def correlation_derivative(correlation, d=25):
            """
            Calculate the first derivative of the correlation traces.
            """
            derivative_filter = np.concatenate((-np.ones(d), np.ones(d)))
            derivative_filter /= d
            return np.convolve(correlation, derivative_filter, mode='same')

        def apply_gaussian_filter(correlation, d=25, sigma=12):
            """
            Apply a Gaussian filter to smooth the correlation traces.
            """
            gaussian = np.exp(-0.5 * (np.linspace(-d/2, d/2, d) / sigma) ** 2)
            gaussian /= np.sum(gaussian)  # Normalize
            return np.convolve(correlation, gaussian, mode='same')
        
        k = [int(bit) for bit in bin(kguess)[2:].zfill(3)][::-1]
        hws = []
        
        for text in nonces:
            v = bytearray_to_bitlist(text)[::-1]
            x3 = v[64:128]
            x4 = v[0:64]
            rs = [0, 19, 28]
            sub_layer_list = []
            for i in range(3):
                sub_layer_list.append(sub_layer(k[i], 0, x3, x4, bitnum, rs[i], sub_layer_type))

            S0 = sub_layer_list[0][0] ^ sub_layer_list[1][0] ^ sub_layer_list[2][0]
            
            hws.append(self.HW[self.iv_bit[bitnum] ^ S0])
            
        self.stats[kguess].add_data(traces,hws)
        
        o_t = self.stats[kguess].std_dev_X()
        o_hws = self.stats[kguess].std_dev_Y()
        correlation = self.stats[kguess].covariance()
        cpaout = correlation/(o_t*o_hws)
        
        cpaout = apply_gaussian_filter(cpaout)
        cpaout = correlation_derivative(cpaout)
        
        maxcpa[kguess] = max(abs(cpaout))
        
    def display_results(self, t_value, bitnum):
        
        clear_output(wait=True)  
        df = create_table(t_value)
        
        caption = f'Finished bitnum {bitnum}'
        
        display(df.style.set_caption(caption).set_table_attributes('style="width: 50%;"'))
        
class cpa_attack:
    def __init__(self, key, iv=[0x80, 0x40, 0x0c, 0x06, 0x00, 0x00, 0x00, 0x00], c_r=[0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xf0]):
        self.stats = [[IncrementalStatsMath() for _ in range(2**3)]for _ in range(64)]
        self.iv_bit = bytearray_to_bitlist(iv)[::-1]
        self.c_r_bit = bytearray_to_bitlist(c_r)[::-1]
        self.key_bit = bytearray_to_bitlist(key)[::-1]
        self.sbox = {"hw" : [
        0x04, 0x0b, 0x1f, 0x14, 0x1a, 0x15, 0x09, 0x02, 0x1b, 0x05, 0x08, 0x12, 0x1d, 0x03, 0x06, 0x1c,
        0x1e, 0x13, 0x07, 0x0e, 0x00, 0x0d, 0x11, 0x18, 0x10, 0x0c, 0x01, 0x19, 0x16, 0x0a, 0x0f, 0x17], 
                "lut_ascon" : [
        0x04, 0x0b, 0x1f, 0x14, 0x1a, 0x15, 0x09, 0x02, 0x1b, 0x05, 0x08, 0x12, 0x1d, 0x03, 0x06, 0x1c,
        0x1e, 0x13, 0x07, 0x0e, 0x00, 0x0d, 0x11, 0x18, 0x10, 0x0c, 0x01, 0x19, 0x16, 0x0a, 0x0f, 0x17],
                "lut_bilgin" : [
        0x01, 0x00, 0x19, 0x1a, 0x11, 0x1d, 0x15, 0x1b, 0x14, 0x05, 0x04, 0x17, 0x0e, 0x12, 0x02, 0x1c,
        0x0f, 0x08, 0x06, 0x03, 0x0d, 0x07, 0x18, 0x10, 0x1e, 0x09, 0x1f, 0x0a, 0x16, 0x0c, 0x0b, 0x13],
                "lut_allouzi" : [
        0x10, 0x0e, 0x0d, 0x02, 0x0b, 0x11, 0x15, 0x1e, 0x07, 0x18, 0x12, 0x1c, 0x1a, 0x01, 0x0c, 0x06,
        0x1f, 0x19, 0x00, 0x17, 0x14, 0x16, 0x08, 0x1b, 0x04, 0x03, 0x13, 0x05, 0x09, 0x0a, 0x1d, 0x0f],
                "lut_lu_4" : [
        0x18, 0x09, 0x1b, 0x06, 0x03, 0x1f, 0x16, 0x01, 0x14, 0x1e, 0x08, 0x05, 0x0a, 0x15, 0x0f, 0x10,
        0x04, 0x13, 0x17, 0x0c, 0x1c, 0x00, 0x0d, 0x1a, 0x07, 0x0b, 0x19, 0x12, 0x11, 0x14, 0x02, 0x1d],
                "lut_lu_5" : [
        0x17, 0x1c, 0x0f, 0x10, 0x02, 0x01, 0x15, 0x1e, 0x19, 0x13, 0x12, 0x0c, 0x0b, 0x08, 0x0d, 0x06,
        0x18, 0x0e, 0x00, 0x03, 0x05, 0x1d, 0x0a, 0x1b, 0x04, 0x07, 0x1f, 0x09, 0x1a, 0x16, 0x14, 0x11],
                "lut_lu_6" : [
        0x03, 0x0d, 0x1a, 0x16, 0x11, 0x02, 0x0f, 0x15, 0x00, 0x17, 0x0c, 0x09, 0x14, 0x19, 0x1e, 0x0a,
        0x1b, 0x0e, 0x04, 0x1d, 0x1c, 0x08, 0x01, 0x12, 0x07, 0x18, 0x10, 0x13, 0x1f, 0x06, 0x0b, 0x05],
                "lut_lu_7" : [
        0x16, 0x0f, 0x10, 0x09, 0x1b, 0x03, 0x05, 0x06, 0x01, 0x15, 0x1e, 0x12, 0x1c, 0x08, 0x0a, 0x1d,
        0x0e, 0x00, 0x0d, 0x1a, 0x18, 0x14, 0x11, 0x1f, 0x13, 0x0c, 0x07, 0x19, 0x0b, 0x17, 0x04, 0x02]
        }
        self.HW = [bin(n).count("1") for n in range(0, 2**3)]
        self.success = []
        self.correct_list = []
        self.guess_corr = [[] for _ in range(64)]
    
    def find_max_subkeys(self, maxcpa, max_key_bit, i):
        guess = np.argmax(maxcpa[i])
        guess_key_bit = [int(bit) for bit in bin(guess)[2:].zfill(3)][::-1]
        self.guess_corr[i].append(maxcpa[i])
        
        sorted_corr = sorted(maxcpa[i], reverse=True)
        for b in range(3):
            max_key_bit[i].append(guess_key_bit[b])
    
    def attack_leak_model(self, traces, nonces, sub_layer_type, callback, x0_col):
        x0_col = x0_col[::-1]
        numtraces = np.shape(traces)[0]
        self.resolution = callback
        
        best_guess_keys = [] 

        for cb in range(0, numtraces, callback):
            callback_traces = traces[cb:cb + callback]
            callback_nonces = nonces[cb:cb + callback]

            guess_key = [0] * 64
            maxcpa = [[[0] for _ in range(2**3)] for _ in range(64)]
            max_key_bit = [[] for _ in range(64)]

            with ThreadPool() as pool:
                results = [
                    pool.apply_async(self.recover_x1, args=(bitnum, callback_traces, callback_nonces, sub_layer_type, maxcpa))
                    for bitnum in x0_col
                ]
                for result in results:
                    result.get()  # wait for each thread to complete

            with ThreadPool() as pool:
                results = [
                    pool.apply_async(self.find_max_subkeys, args=(maxcpa, max_key_bit, i))
                    for i in x0_col
                ]
                for result in results:
                    result.get()  # wait for each thread to complete
                    
            for i in x0_col:
                guess_key[i] = max_key_bit[i][0]
                guess_key[(i-19) % 64] = max_key_bit[i][1]
                guess_key[(i-28) % 64] = max_key_bit[i][2]
            
            best_guess_keys.append(guess_key)
            self.display_results(guess_key, cb, cb + callback)

        return best_guess_keys, self.guess_corr

    def recover_x1(self, bitnum, callback_traces, callback_nonces, sub_layer_type, maxcpa):
        with ThreadPool() as pool:
            results = [
                pool.apply_async(self.key_correlation_1, args=(bitnum, kguess, callback_traces, callback_nonces, sub_layer_type, maxcpa))
                for kguess in range(0, 2**3)
            ]
            for result in results:
                result.get()  # wait for each thread to complete

    def key_correlation_1(self, bitnum, kguess, traces, nonces, sub_layer_type, maxcpa):
        def y0(x0, x1, x2, x3, x4):
            return x1 & (x4 ^ x2 ^ x0 ^ 1) ^ x3 ^ x2 ^ x0
        def sub_layer(x1, x2, x3, x4, bitnum, rs, sub_layer_type):
            return hex_to_bit(self.sbox[sub_layer_type][bit_to_hex(self.iv_bit[(bitnum + rs) % 64], x1, x2 ^ self.c_r_bit[(bitnum + rs) % 64], x3[(bitnum + rs) % 64], x4[(bitnum + rs) % 64])])

        def correlation_derivative(correlation, d=25):
            """
            Calculate the first derivative of the correlation traces.
            """
            derivative_filter = np.concatenate((-np.ones(d), np.ones(d)))
            derivative_filter /= d
            return np.convolve(correlation, derivative_filter, mode='same')

        def apply_gaussian_filter(correlation, d=25, sigma=12):
            """
            Apply a Gaussian filter to smooth the correlation traces.
            """
            gaussian = np.exp(-0.5 * (np.linspace(-d/2, d/2, d) / sigma) ** 2)
            gaussian /= np.sum(gaussian)  # Normalize
            return np.convolve(correlation, gaussian, mode='same')
        
        def SD(in_val,out_val):
            if in_val == 0 and out_val == 1:
                return 1
            elif in_val == 1 and out_val == 0:
                return 1.5
            else:
                return 0
        
        k = [int(bit) for bit in bin(kguess)[2:].zfill(3)][::-1]
        hws = []

        for text in nonces:
            v = bytearray_to_bitlist(text)[::-1]
            x3 = v[64:128]
            x4 = v[0:64]
            rs = [0, 19, 28]
            sub_layer_list = []
            for i in range(3):
                sub_layer_list.append(sub_layer(k[i], 0, x3, x4, bitnum, rs[i], sub_layer_type))
            S0 = sub_layer_list[0][0] ^ sub_layer_list[1][0] ^ sub_layer_list[2][0]
            hws.append(self.HW[self.iv_bit[bitnum] ^ S0])

        self.stats[bitnum][kguess].add_data(traces, hws)
        o_t = self.stats[bitnum][kguess].std_dev_X()
        o_hws = self.stats[bitnum][kguess].std_dev_Y()
        correlation = self.stats[bitnum][kguess].covariance()
        cpaout = correlation / (o_t * o_hws)
        
        cpaout = apply_gaussian_filter(cpaout)
        cpaout = correlation_derivative(cpaout)

        maxcpa[bitnum][kguess] = max(abs(cpaout))
    
    def display_results(self,best_guess,tstart,tend):
        global show_key
        reference_key = self.key_bit[64:128][::-1]
        show_key = [reference_key[0:16],reference_key[16:32],reference_key[32:48],reference_key[48:64]]
        bit_list = best_guess[::-1]
        show_list = [bit_list[0:16],bit_list[16:32],bit_list[32:48],bit_list[48:64]]

        ncorrect = 0
        for r in range(4):
            for c in range(16):
                if show_list[r][c] == show_key[r][c]:
                    ncorrect += 1
                    
        self.correct_list.append(ncorrect)
        
        if ncorrect == 64:
            self.success.append(1)
        else:
            self.success.append(0)
        
        clear_output(wait=True)  
        df = create_table_3(show_list)
        
        caption = f'Finished traces {tstart} to {tend}. Correct {ncorrect}/64<br>Correct key: {convert_to_hex(reference_key)}<br> Guessed key: {convert_to_hex(bit_list)}'
        
        display(df.style.apply(highlight_bits, axis=None).set_caption(caption).set_table_attributes('style="width: 100%;"'))

    def plot_success(self,resolution, index):
        """Plot success with matplotlib.

            resolution: sampling interval in traces

        """

        fig, ax1 = plt.subplots(nrows=1, ncols=1, sharex=True, figsize=[18,12])

        xticks_samples = range(len(self.success))
        xtick = [x*resolution+resolution for x in xticks_samples]
        t = "Success rate for the guessed key "
        plt.title(t)
        ax1.set_xlabel("# Traces")
        ax1.set_ylabel("Success rate")

        ax1.plot(xtick, self.success, color=mcolors.CSS4_COLORS["red"], alpha=0.5)

        name_fig = "./Figures/success_" + str(xtick[len(xtick)-1]) + "_" + str(index) + ".png"
        plt.savefig(name_fig)
        filename = "./results/success_rate/success_rate_" + str(xtick[len(xtick)-1]) + "_" + str(index) + ".txt"
        with open(filename,'w') as success_file:
            for success in self.success:
                print(success, file=success_file)

        return plt
    
    def plot_correct(self,resolution, index):
        """Plot number of correct bit with matplotlib.

            resolution: sampling interval in traces

        """

        fig, ax1 = plt.subplots(nrows=1, ncols=1, sharex=True, figsize=[18,12])

        xticks_samples = range(len(self.correct_list))
        xtick = [x*resolution+resolution for x in xticks_samples]
        t = "Number of correct key bit vs. traces"
        plt.title(t)
        ax1.set_xlabel("# Traces")
        ax1.set_ylabel("# Correct")

        ax1.plot(xtick, self.correct_list, color=mcolors.CSS4_COLORS["red"], alpha=0.5)

        name_fig = "./Figures/correct_" + str(xtick[len(xtick)-1]) + "_" + str(index) + ".png"
        plt.savefig(name_fig)
        
        filename = "./results/success_rate/correct_" + str(xtick[len(xtick)-1]) + "_" + str(index) + ".txt"
        with open(filename,'w') as correct_file:
            for correct in self.correct_list:
                print(correct, file=correct_file)

        return plt
    
    def plot_corr(self, bitnum):
        """Plot correlation with matplotlib.

            bitnum: number of bit to plot the correlation
            start: initial sample to plot
            finish: final sample to plot
        
        """
        correct_key = [self.key_bit[((bitnum) % 64 ) + 64], self.key_bit[((19 + bitnum) % 64) + 64], self.key_bit[((28 + bitnum) % 64) + 64]][::-1]
        guess_corr = [[] for _ in range(2**3)]
        for element in self.guess_corr[bitnum]:
            for i in range(2**3):
                guess_corr[i].append(element[i])

        fig, ax1 = plt.subplots(nrows=1, ncols=1, sharex=True, figsize=[18,12])

        xticks_samples = range(len(guess_corr[0]))
        xtick = [x*self.resolution+self.resolution for x in xticks_samples]

        t = "Correlation plot for the guessed key " + str(bitnum) + "[k[" + str(((bitnum) % 64) + 64) + "], k[" + str(((bitnum + 19) % 64) + 64) + "], k[" + str(((bitnum + 28) % 64) + 64) + "]]"
        plt.title(t)
        ax1.set_xlabel("# Traces")
        ax1.set_ylabel("Correlation")

        for i in range(2**3):
            ax1.plot(xtick, guess_corr[i], color=mcolors.CSS4_COLORS["orange"], alpha=0.5)
        ax1.plot(xtick, guess_corr[int(''.join(str(bit) for bit in correct_key), 2)], color=mcolors.CSS4_COLORS["red"], alpha=0.5)
        
        name_fig = "./Figures/corr_" + str(xtick[len(xtick)-1]) + "_" + str(bitnum) + ".png"
        plt.savefig(name_fig)
    
        return plt