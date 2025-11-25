from IncrementalStats import IncrementalStatsMath
import pandas as pd
import numpy as np
from IPython.display import display, clear_output, HTML
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import threading
from multiprocessing.pool import ThreadPool
from multiprocessing import Pool, cpu_count, Process, current_process
import utils as utils
import ascon_funcs as ascon

class dpa_round_1_output_x0:
    """
    Class that implement a DPA attack on ASCON
    """
    def __init__(self, key, iv=[0x80, 0x40, 0x0c, 0x06, 0x00, 0x00, 0x00, 0x00], c_r=[0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xf0]):
        """
        Args:
            key (list): value of the correct key for comparison with the guessed key
            iv (list, optional): value of the initial value. Defaults to [0x80, 0x40, 0x0c, 0x06, 0x00, 0x00, 0x00, 0x00].
            c_r (list, optional): value of the round constant. Defaults first round constant to [0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xf0].
        """
        self.stats = [[IncrementalStatsMath() for _ in range(8)] for _ in range(36)]
        self.iv_bit = utils.bytearray_to_bitlist(iv)[::-1]
        self.c_r_bit = utils.bytearray_to_bitlist(c_r)[::-1]
        self.key_bit = utils.bytearray_to_bitlist(key)[::-1]
        self.correct_list = []
    
    def attack_leak_model(self, traces, nonces, sub_layer_type, callback):
        """Function that run the DPA attack on 1 bit.
        Args:
            traces (list): list of traces to process
            nonces (list): list of nonces
            callback (int): specify the number of traces for the callback
        Returns:
            list: list of the best guess key bits
        """
        numtraces = np.shape(traces)[0]
        
        for cb in range(0,numtraces, callback):
            callback_traces = traces[cb:cb+callback]
            callback_nonces = nonces[cb:cb+callback]

            guess_key = [0] * 128
            full_diffs_list = []
            #taken 36 output columns to retrieve the key
            for bitnum in range(36):
                max_diffs = [0]*8
                full_diffs = [0]*8

                for kguess in range(0, 8):
                    full_diff_trace = self.calculate_diffs(bitnum, kguess, callback_traces, callback_nonces, sub_layer_type)
                    max_diffs[kguess] = np.max(full_diff_trace)

                guess = np.argsort(max_diffs)[::-1]
                guess_bit = [int(bit) for bit in bin(guess[0])[2:].zfill(3)][::-1]
                guess_key[(bitnum+64)%128] = guess_bit[0]
                if (bitnum+109) < 128:
                    guess_key[(bitnum+109)%128] = guess_bit[1]
                if (bitnum+100) < 109:
                    guess_key[(bitnum+100)%128] = guess_bit[2]

            self.display_results(guess_key,cb,cb+callback)
            
        return guess_key
    
    def calculate_diffs(self, bitnum, kguess, traces, nonces, sub_layer_type):
        """ Function that calculates for the register x4 the difference of means for a certain subkey

        Args:
            bitnum (int): value of the column in which calculate the correlation value.
            kguess (int): value of the subkey in which the correlation value is calculated.
            traces (list): traces of the current callback to add to the previous callbacks traces.
            nonces (list): nonces of the current callback to add to the previous callbacks nonces.
            sub_layer_type (string): specify the type of S-box.
        """
        def sub_layer(x1, x2, x3, x4, bitnum, rs, sub_layer_type):
            sbox_input = utils.bit_to_hex(self.iv_bit[(bitnum + rs) % 64], x1, x2^self.c_r_bit[(bitnum + rs) % 64], x3[(bitnum + rs) % 64], x4[(bitnum + rs) % 64])
            return utils.hex_to_bit(ascon.sbox(sub_layer_type, sbox_input))
        
        k = [int(bit) for bit in bin(kguess)[2:].zfill(3)][::-1]
        
        one_list = []
        zero_list = []
        
        trace_index = 0
        for text in nonces:
            v = utils.bytearray_to_bitlist(text)[::-1]
            x3 = v[64:128]
            x4 = v[0:64]
            rs = [0, 19, 28]
            sub_layer_list = []
            for i in range(3):
                sub_layer_list.append(sub_layer(k[i], 0, x3, x4, bitnum, rs[i], sub_layer_type))
            S0 = sub_layer_list[0][0] ^ sub_layer_list[1][0] ^ sub_layer_list[2][0]
            
            if S0:
                one_list.append(traces[trace_index])
            else:
                zero_list.append(traces[trace_index])
            trace_index += 1
            
        self.stats[bitnum][kguess].add_data(one_list,zero_list)
        
        one_avg = self.stats[bitnum][kguess].mean_X()
        zero_avg = self.stats[bitnum][kguess].mean_Y()
        
        return abs(one_avg - zero_avg)
    
    def display_results(self,best_guess,tstart,tend):
        reference_key = self.key_bit[64:128][::-1]
        key_list = [reference_key[0:16],reference_key[16:32],reference_key[32:48],reference_key[48:64]]
        bit_list = best_guess[64:128][::-1]
        show_list = [bit_list[0:16],bit_list[16:32],bit_list[32:48],bit_list[48:64]]

        ncorrect = 0
        for r in range(4):
            for c in range(16):
                if show_list[r][c] == key_list[r][c]:
                    ncorrect += 1
        self.correct_list.append(ncorrect)
        
        clear_output(wait=True)  
        df = utils.create_table_3(show_list)
        
        caption = f'Finished traces {tstart} to {tend}. Correct {ncorrect}/64<br>Correct key: {utils.convert_to_hex(reference_key)}<br> Guessed key: {utils.convert_to_hex(bit_list)}'
        
        display(df.style.apply(utils.highlight_bits, key=key_list, axis=None).set_caption(caption).set_table_attributes('style="width: 100%;"'))
        
    def plot_correct(self,resolution, index):
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
        
        filename = "./results/success_rate/dpa_correct_" + str(xtick[len(xtick)-1]) + "_" + str(index) + ".txt"
        with open(filename,'w') as correct_file:
            for correct in self.correct_list:
                print(correct, file=correct_file)

        return plt

class cpa_round_1_output_x0_1_bit:
    """
    Class that implement a CPA attack on ASCON to retrieve 1 bit of the first
    half of the key. It uses the content of the register x4 for the leakage model.
    """
    def __init__(self, key, iv=[0x80, 0x40, 0x0c, 0x06, 0x00, 0x00, 0x00, 0x00], c_r=[0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xf0]):
        """
        Args:
            key (list): value of the correct key for comparison with the guessed key
            iv (list, optional): value of the initial value. Defaults to [0x80, 0x40, 0x0c, 0x06, 0x00, 0x00, 0x00, 0x00].
            c_r (list, optional): value of the round constant. Defaults first round constant to [0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xf0].
        """
        self.stats = [IncrementalStatsMath() for _ in range(2**3)]
        self.iv_bit = utils.bytearray_to_bitlist(iv)[::-1]
        self.c_r_bit = utils.bytearray_to_bitlist(c_r)[::-1]
        self.key_bit = utils.bytearray_to_bitlist(key)[::-1]
        self.HW = [bin(n).count("1") for n in range(0, 2**3)]
    
    def attack_leak_model(self, traces, nonces, sub_layer_type, callback, bitnum):
        """Function that run the CPA attack on 1 bit.

        Args:
            traces (list): list of traces
            nonces (list): list of nonces
            callback (int): specify the number of traces for the callback
            bitnum (int): column index for the attack

        Returns:
            list: list of the best guess key bit
            list: list of the correlation values for every callback
        """
        numtraces = np.shape(traces)[0]
        
        best_guess = [0] * int(numtraces/callback)
        guess_corr = []
        
        for cb in range(0,numtraces, callback):
            callback_traces = traces[cb:cb+callback]
            callback_nonces = nonces[cb:cb+callback]

            maxcpa = [0] * (2**3)
            threads = []

            for kguess in range(0, 2**3):
                thread = threading.Thread(target=self.key_correlation_1, args=(bitnum, kguess, callback_traces, callback_nonces, sub_layer_type, maxcpa))
                thread.start()
                threads.append(thread)
                
            for thread in threads:
                thread.join()

            guess = np.argmax(maxcpa)
            best_guess[int(cb/callback)] = guess
            guess_corr.append(maxcpa)
            
            guess_key_bits = [int(bit) for bit in bin(guess)[2:].zfill(3)][::-1]
            
            keys = list(range(2**3))
            sorted_pairs = sorted(zip(keys, maxcpa), key=lambda x: x[1], reverse=True)
            sorted_keys = [key for key, _ in sorted_pairs]
            sorted_correlations = [value for _, value in sorted_pairs]

            sorted_keys_bits = []
            for key_guess in sorted_keys:
                sorted_keys_bits.append([int(bit) for bit in bin(key_guess)[2:].zfill(3)][::-1])

            self.display_results(sorted_keys_bits, sorted_correlations, bitnum,cb,cb+callback)
            
            if cb+callback == 150000:
                plt = self.plot_corr(callback, guess_corr, bitnum)
                print("Plotting correlation 150000 traces")
            
        return guess_key_bits, guess_corr
    
    def key_correlation_1(self, bitnum, kguess, traces, nonces, sub_layer_type, maxcpa):
        """ Function that calculates for the register x0 the correlation values for a certain subkey

        Args:
            bitnum (int): value of the column in which calculate the correlation value.
            kguess (int): value of the subkey in which the correlation value is calculated.
            traces (list): traces of the current callback to add to the previous callbacks traces.
            nonces (list): nonces of the current callback to add to the previous callbacks nonces.
            sub_layer_type (string): specify the type of S-box.
            maxcpa (list): list where the correlation values of the guessed subkeys are returned.
        """
        def sub_layer(x1, x2, x3, x4, bitnum, rs, sub_layer_type):
            sbox_input = utils.bit_to_hex(self.iv_bit[(bitnum + rs) % 64], x1, x2^self.c_r_bit[(bitnum + rs) % 64], x3[(bitnum + rs) % 64], x4[(bitnum + rs) % 64])
            return utils.hex_to_bit(ascon.sbox(sub_layer_type, sbox_input))
        
        
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
            v = utils.bytearray_to_bitlist(text)[::-1]
            x3 = v[64:128]
            x4 = v[0:64]
            rs = [0, 19, 28]
            sub_layer_list = []
            for i in range(3):
                sub_layer_list.append(sub_layer(k[i], 0, x3, x4, bitnum, rs[i], sub_layer_type))

            S0 = sub_layer_list[0][0] ^ sub_layer_list[1][0] ^ sub_layer_list[2][0]
            
            #hws.append(self.HW[self.iv_bit[bitnum] ^ S0])
            hws.append(SD(self.iv_bit[bitnum], S0))
            
        self.stats[kguess].add_data(traces,hws)
        
        o_t = self.stats[kguess].std_dev_X()
        o_hws = self.stats[kguess].std_dev_Y()
        correlation = self.stats[kguess].covariance()
        cpaout = correlation/(o_t*o_hws)
        
        cpaout = apply_gaussian_filter(cpaout)
        cpaout = correlation_derivative(cpaout)
        
        maxcpa[kguess] = max(abs(cpaout))
        
    def display_results(self, sorted_key_guess, sorted_correlation, bitnum, tstart, tend):
        """ Function that print on a table the ranking of the guessed subkeys with their correlation.

        Args:
            sorted_key_guess (list): list of the sorted subkey.
            sorted_correlation (list): list of the sorted correlations of the subkey.
            bitnum (int): value of the column in which calculate the correlation value.
            tstart (int): trace number from which the callback started.
            tend (int): trace number from which the callback ended.
        """ 
        key_list = [self.key_bit[((bitnum) % 64) + 64], self.key_bit[((19 + bitnum) % 64) + 64], self.key_bit[((28 + bitnum) % 64) + 64]]
        ncorrect = 0
        for i in range(3):
            if key_list[i] == sorted_key_guess[0][i]:
                ncorrect += 1
        
        clear_output(wait=True)  
        df = utils.create_table_2(sorted_key_guess,sorted_correlation, bitnum)
        
        caption = f'Finished traces {tstart} to {tend}. Correct {ncorrect}/3'
        
        display(df.head(10).style.apply(utils.highlight_bits_2, key=key_list, axis=None).set_caption(caption).set_table_attributes('style="width: 50%;"'))
        
    def plot_corr(self, resolution, traces, bitnum):
        """Plot correlation with matplotlib.

            resolution: sampling interval in seconds
            traces: list of correlations as numpy arrays
            start: initial sample to plot
            finish: final sample to plot
        
        """
        correct_key = [self.key_bit[((bitnum) % 64) + 64], self.key_bit[((19 + bitnum) % 64) + 64], self.key_bit[((28 + bitnum) % 64 ) + 64]][::-1]
        guess_corr = [[] for _ in range(2**3)]
        for element in traces:
            for i in range(2**3):
                guess_corr[i].append(element[i])

        fig, ax1 = plt.subplots(nrows=1, ncols=1, sharex=True, figsize=[18,12])

        xticks_samples = range(len(guess_corr[0]))
        xtick = [x*resolution+resolution for x in xticks_samples]

        t = "Correlation plot for the guessed key " + str(bitnum) + "[k[" + str(((bitnum) % 64) + 64) + "], k[" + str(((bitnum + 19) % 64 ) + 64) + "], k[" + str(((bitnum + 28) % 64 ) + 64) + "]]"
        plt.title(t)
        ax1.set_xlabel("# Traces")
        ax1.set_ylabel("Correlation")

        for i in range(2**3):
            ax1.plot(xtick, guess_corr[i], color=mcolors.CSS4_COLORS["orange"], alpha=0.5)
        ax1.plot(xtick, guess_corr[int(''.join(str(bit) for bit in correct_key), 2)], color=mcolors.CSS4_COLORS["red"], alpha=0.5)
        
        name_fig = "./Figures/corr_" + str(xtick[len(xtick)-1]) + "_" + str(bitnum) + ".png"
        plt.savefig(name_fig)
    
        return plt
    
class cpa_round_1_output_x4_1_bit:
    """
    Class that implement a CPA attack on ASCON to retrieve 1 bit of the first
    half of the key. It uses the content of the register x4 for the leakage model.
    """
    def __init__(self, key, iv=[0x80, 0x40, 0x0c, 0x06, 0x00, 0x00, 0x00, 0x00], c_r=[0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xf0]):
        """
        Args:
            key (list): value of the correct key for comparison with the guessed key
            iv (list, optional): value of the initial value. Defaults to [0x80, 0x40, 0x0c, 0x06, 0x00, 0x00, 0x00, 0x00].
            c_r (list, optional): value of the round constant. Defaults first round constant to [0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xf0].
        """
        self.stats = [IncrementalStatsMath() for _ in range(2**3)]
        self.iv_bit = utils.bytearray_to_bitlist(iv)[::-1]
        self.c_r_bit = utils.bytearray_to_bitlist(c_r)[::-1]
        self.key_bit = utils.bytearray_to_bitlist(key)[::-1]
        
        self.HW = [bin(n).count("1") for n in range(0, 2**3)]
    
    def attack_leak_model(self, traces, nonces, sub_layer_type, callback, bitnum):
        """Function that run the CPA attack on 1 bit.

        Args:
            traces (list): list of traces to process
            nonces (list): list of nonces.

            callback (int): specify the number of traces for the callback
            bitnum (int): column index for the attack

        Returns:
            list: list of the best guess key bit
            list: list of the correlation values for every callback
        """
        numtraces = np.shape(traces)[0]
        
        best_guess = [0] * int(numtraces/callback)
        guess_corr = []
        
        for cb in range(0,numtraces, callback):
            callback_traces = traces[cb:cb+callback]
            callback_nonces = nonces[cb:cb+callback]

            maxcpa = [0] * (2**3)
            threads = []

            for kguess in range(0, 2**3):
                thread = threading.Thread(target=self.key_correlation_1, args=(bitnum, kguess, callback_traces, callback_nonces, sub_layer_type, maxcpa))
                thread.start()
                threads.append(thread)
                
            for thread in threads:
                thread.join()

            guess = np.argmax(maxcpa)
            best_guess[int(cb/callback)] = guess
            guess_corr.append(maxcpa)
            
            guess_key_bits = [int(bit) for bit in bin(guess)[2:].zfill(3)][::-1]
            
            keys = list(range(2**3))
            sorted_pairs = sorted(zip(keys, maxcpa), key=lambda x: x[1], reverse=True)
            sorted_keys = [key for key, _ in sorted_pairs]
            sorted_correlations = [value for _, value in sorted_pairs]

            sorted_keys_bits = []
            for key_guess in sorted_keys:
                sorted_keys_bits.append([int(bit) for bit in bin(key_guess)[2:].zfill(3)][::-1])

            self.display_results(sorted_keys_bits, sorted_correlations, bitnum,cb,cb+callback)
            
            if cb+callback == 150000:
                plt = self.plot_corr(callback, guess_corr, bitnum)
                print("Plotting correlation 150000 traces")
            
        return guess_key_bits, guess_corr
    
    def key_correlation_1(self, bitnum, kguess, traces, nonces, sub_layer_type, maxcpa):
        """ Function that calculates for the register x4 the correlation values for a certain subkey

        Args:
            bitnum (int): value of the column in which calculate the correlation value.
            kguess (int): value of the subkey in which the correlation value is calculated.
            traces (list): traces of the current callback to add to the previous callbacks traces.
            nonces (list): nonces of the current callback to add to the previous callbacks nonces.
            sub_layer_type (string): specify the type of S-box.
            maxcpa (list): list where the correlation values of the guessed subkeys are returned.
        """
        def sub_layer(x1, x2, x3, x4, bitnum, rs, sub_layer_type):
            sbox_input = utils.bit_to_hex(self.iv_bit[(bitnum + rs) % 64], x1, x2^self.c_r_bit[(bitnum + rs) % 64], x3[(bitnum + rs) % 64], x4[(bitnum + rs) % 64])
            return utils.hex_to_bit(ascon.sbox(sub_layer_type, sbox_input))
        
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
            v = utils.bytearray_to_bitlist(text)[::-1]
            x3 = v[64:128]
            x4 = v[0:64]
            rs = [0, 7, 41]
            sub_layer_list = []
            for i in range(3):
                sub_layer_list.append(sub_layer(k[i], 0, x3, x4, bitnum, rs[i], sub_layer_type))

            S4 = sub_layer_list[0][4] ^ sub_layer_list[1][4] ^ sub_layer_list[2][4]
            
            hws.append(self.HW[x4[bitnum] ^ S4])
            
        self.stats[kguess].add_data(traces,hws)
        
        o_t = self.stats[kguess].std_dev_X()
        o_hws = self.stats[kguess].std_dev_Y()
        correlation = self.stats[kguess].covariance()
        cpaout = correlation/(o_t*o_hws)
        
        cpaout = apply_gaussian_filter(cpaout)
        cpaout = correlation_derivative(cpaout)
        
        maxcpa[kguess] = max(abs(cpaout))
        
    def display_results(self, sorted_key_guess, sorted_correlation, bitnum, tstart, tend):
        """ Function that print on a table the ranking of the guessed subkeys with their correlation.

        Args:
            sorted_key_guess (list): list of the sorted subkey.
            sorted_correlation (list): list of the sorted correlations of the subkey.
            bitnum (int): value of the column in which calculate the correlation value.
            tstart (int): trace number from which the callback started.
            tend (int): trace number from which the callback ended.
        """ 
        key_list = [self.key_bit[((bitnum) % 64) + 64], self.key_bit[((7 + bitnum) % 64) + 64], self.key_bit[((41 + bitnum) % 64) + 64]]
        ncorrect = 0
        for i in range(3):
            if key_list[i] == sorted_key_guess[0][i]:
                ncorrect += 1
        
        clear_output(wait=True)  
        df = utils.create_table_4(sorted_key_guess,sorted_correlation, bitnum)
        
        caption = f'Finished traces {tstart} to {tend}. Correct {ncorrect}/3'
        
        display(df.head(10).style.apply(utils.highlight_bits_2, key=key_list, axis=None).set_caption(caption).set_table_attributes('style="width: 50%;"'))
        
    def plot_corr(self, resolution, traces, bitnum):
        """Plot correlation with matplotlib.

            resolution: sampling interval in seconds
            traces: list of correlations as numpy arrays
            start: initial sample to plot
            finish: final sample to plot
        
        """
        correct_key = [self.key_bit[((bitnum) % 64) + 64], self.key_bit[((7 + bitnum) % 64) + 64], self.key_bit[((41 + bitnum) % 64) + 64]][::-1]
        guess_corr = [[] for _ in range(2**3)]
        for element in traces:
            for i in range(2**3):
                guess_corr[i].append(element[i])

        fig, ax1 = plt.subplots(nrows=1, ncols=1, sharex=True, figsize=[18,12])

        xticks_samples = range(len(guess_corr[0]))
        xtick = [x*resolution+resolution for x in xticks_samples]

        t = "Correlation plot for the guessed key " + str(bitnum) + "[k[" + str(((bitnum) % 64) + 64) + "], k[" + str(((bitnum + 7) % 64 ) + 64) + "], k[" + str(((bitnum + 41) % 64 ) + 64) + "]]"
        plt.title(t)
        ax1.set_xlabel("# Traces")
        ax1.set_ylabel("Correlation")

        for i in range(2**3):
            ax1.plot(xtick, guess_corr[i], color=mcolors.CSS4_COLORS["orange"], alpha=0.5)
        ax1.plot(xtick, guess_corr[int(''.join(str(bit) for bit in correct_key), 2)], color=mcolors.CSS4_COLORS["red"], alpha=0.5)
        
        name_fig = "./Figures/corr_x4_" + str(xtick[len(xtick)-1]) + "_" + str(bitnum) + ".png"
        plt.savefig(name_fig)
    
        return plt
    
class cpa_round_1_output_x0_recover_x1_pool:
    """
    Class that implement a CPA attack on ASCON to retrieve the first
    half of the key. It uses the content of the register x0 for the leakage model.
    """
    def __init__(self, key, iv=[0x80, 0x40, 0x0c, 0x06, 0x00, 0x00, 0x00, 0x00], c_r=[0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xf0]):
        """
        Args:
            key (list): value of the correct key for comparison with the guessed key
            iv (list, optional): value of the initial value. Defaults to [0x80, 0x40, 0x0c, 0x06, 0x00, 0x00, 0x00, 0x00].
            c_r (list, optional): value of the round constant. Defaults first round constant to [0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xf0].
        """
        self.stats = [[IncrementalStatsMath() for _ in range(2**3)]for _ in range(64)]
        self.iv_bit = utils.bytearray_to_bitlist(iv)[::-1]
        self.c_r_bit = utils.bytearray_to_bitlist(c_r)[::-1]
        self.key_bit = utils.bytearray_to_bitlist(key)[::-1]
        
        self.HW = [bin(n).count("1") for n in range(0, 2**3)]
        self.success = []
        self.correct_list = []
        self.guess_corr = [[] for _ in range(64)]
    
    def find_max_subkeys(self, maxcpa, max_key_bit, i):
        """Function to find the guessed key bit with maximum correlation value.

        Args:
            maxcpa (list): list of correlation values. The indexes indicate the value of the guessed key
            max_key_bit (list): list where the bit of the guessed key are returned.
                                max_key_bit[0] -> first bit of the guessed key
                                max_key_bit[1] -> second bit of the guessed key
                                max_key_bit[2] -> third bit of the guessed key
                                max_key_bit[3] -> correlation value of the guessed key
                                max_key_bit[4] -> distance value of the guessed key from the second ranked guessed key
                                max_key_bit[5] -> multiplication between the correlation and the distance value of the guessed key
            i (int): index of the column where to calculate the guessed key bit.
        """
        guess = np.argmax(maxcpa[i])
        guess_key_bit = [int(bit) for bit in bin(guess)[2:].zfill(3)][::-1]
        self.guess_corr[i].append(maxcpa[i])
        
        sorted_corr = sorted(maxcpa[i], reverse=True)
        for b in range(3):
            max_key_bit[i].append(guess_key_bit[b])
        max_key_bit[i].append(sorted_corr[0])
        max_key_bit[i].append(sorted_corr[0]-sorted_corr[1])
        max_key_bit[i].append(sorted_corr[0]*(sorted_corr[0]-sorted_corr[1]))
        
    def find_key(self, max_key_bit, guess_key, i):
        """Function to find the value of the first half of the guessed key.

        Args:
            max_key_bit (list): list of the guessed key bits with maximum correlation
            guess_key (list): list where the guessed key is returned
            i (int): index of the column where to calculate the guessed key
        """
        max_corr = max_key_bit[i][3]
        max_diff_corr = max_key_bit[i][4]
        max_tot = max_key_bit[i][5]
        max_bit_0 = max_key_bit[i][0]
        max_bit_1 = max_key_bit[i][0]
        max_bit_2 = max_key_bit[i][0]
            
        if max_corr < max_key_bit[(i - 19) % 64][3]:
            max_corr = max_key_bit[(i - 19) % 64][3]
            max_bit_0 = max_key_bit[(i - 19) % 64][1]
            
        if max_diff_corr < max_key_bit[(i - 19) % 64][4]:
            max_diff_corr = max_key_bit[(i - 19) % 64][4]
            max_bit_1 = max_key_bit[(i - 19) % 64][1]
            
        if max_tot < max_key_bit[(i - 19) % 64][5]:
            max_tot = max_key_bit[(i - 19) % 64][5]
            max_bit_2 = max_key_bit[(i - 19) % 64][1]
            
        if max_corr < max_key_bit[(i - 28) % 64][3]:
            max_corr = max_key_bit[(i - 28) % 64][3]
            max_bit_0 = max_key_bit[(i - 28) % 64][2]
            
        if max_diff_corr < max_key_bit[(i - 28) % 64][4]:
            max_diff_corr = max_key_bit[(i - 28) % 64][4]
            max_bit_1 = max_key_bit[(i - 28) % 64][2]
            
        if max_tot < max_key_bit[(i - 28) % 64][5]:
            max_tot = max_key_bit[(i - 28) % 64][5]
            max_bit_2 = max_key_bit[(i - 28) % 64][2]
            
        if max_bit_0 == max_bit_1:
            max_bit = max_bit_0
        elif max_bit_0 == max_bit_2:
            max_bit = max_bit_0
        else:
            max_bit = max_bit_1
        
        guess_key[i] = max_bit
    
    def attack_leak_model(self, traces, nonces, sub_layer_type, callback, index):
        """Function that run the CPA attack.

        Args:
            traces (list): list of traces to process
            nonces (list): list of nonces.

            callback (int): specify the number of traces for the callback
            index (int): attack number index.

        Returns:
            list: list of the best guessed keys for every callback
            list: list of the correlation values for every callback
        """
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
                    for bitnum in range(64)
                ]
                for result in results:
                    result.get()  # wait for each thread to complete

            with ThreadPool() as pool:
                results = [
                    pool.apply_async(self.find_max_subkeys, args=(maxcpa, max_key_bit, i))
                    for i in range(64)
                ]
                for result in results:
                    result.get()  # wait for each thread to complete
                
            with ThreadPool() as pool:
                results = [
                    pool.apply_async(self.find_key, args=(max_key_bit, guess_key, i))
                    for i in range(64)
                ]
                for result in results:
                    result.get()  # wait for each thread to complete
            
            best_guess_keys.append(guess_key)
            self.display_results(guess_key, index, cb, cb + callback)
            
        self.plot_success(callback, index)
        self.plot_correct(callback, index)

        return best_guess_keys, self.guess_corr

    def recover_x1(self, bitnum, callback_traces, callback_nonces, sub_layer_type, maxcpa):
        """ Function that calculate for every value of the subkey of the register x0 the correlation value

        Args:
            bitnum (int): value of the column in which calculate the correlation value.
            callback_traces (list): traces of the current callback to add to the previous callbacks traces.
            callback_nonces (list): nonces of the current callback to add to the previous callbacks nonces.
            sub_layer_type (sting): specify the type of S-box.
            maxcpa (list): list where the correlation values of the guessed subkeys are returned.
        """
        with ThreadPool() as pool:
            results = [
                pool.apply_async(self.key_correlation_1, args=(bitnum, kguess, callback_traces, callback_nonces, sub_layer_type, maxcpa))
                for kguess in range(0, 2**3)
            ]
            for result in results:
                result.get()  # wait for each thread to complete

    def key_correlation_1(self, bitnum, kguess, traces, nonces, sub_layer_type, maxcpa):
        """ Function that calculates for the register x0 the correlation values for a certain subkey

        Args:
            bitnum (int): value of the column in which calculate the correlation value.
            kguess (int): value of the subkey in which the correlation value is calculated.
            traces (list): traces of the current callback to add to the previous callbacks traces.
            nonces (list): nonces of the current callback to add to the previous callbacks nonces.
            sub_layer_type (string): specify the type of S-box.
            maxcpa (list): list where the correlation values of the guessed subkeys are returned.
        """
        def sub_layer(x1, x2, x3, x4, bitnum, rs, sub_layer_type):
            sbox_input = utils.bit_to_hex(self.iv_bit[(bitnum + rs) % 64], x1, x2^self.c_r_bit[(bitnum + rs) % 64], x3[(bitnum + rs) % 64], x4[(bitnum + rs) % 64])
            return utils.hex_to_bit(ascon.sbox(sub_layer_type, sbox_input))

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
            v = utils.bytearray_to_bitlist(text)[::-1]
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
    
    def display_results(self,best_guess,index,tstart,tend):
        """ Function that calculates the number of correct bits and prints them to the screen in a table.

        Args:
            best_guess (list): list of the 64 guessed key bits.
            index (int): attack number index.
            tstart (int): trace number from which the callback started.
            tend (int): trace number from which the callback ended.
        """ 
        reference_key = self.key_bit[64:128][::-1]
        key_list = [reference_key[0:16],reference_key[16:32],reference_key[32:48],reference_key[48:64]]
        bit_list = best_guess[::-1]
        show_list = [bit_list[0:16],bit_list[16:32],bit_list[32:48],bit_list[48:64]]

        ncorrect = 0
        for r in range(4):
            for c in range(16):
                if show_list[r][c] == key_list[r][c]:
                    ncorrect += 1
                    
        self.correct_list.append(ncorrect)
        
        if ncorrect == 64:
            self.success.append(1)
        else:
            self.success.append(0)
        
        clear_output(wait=True)  
        df = utils.create_table_3(show_list)
        
        caption = f'Process {index}. Finished traces {tstart} to {tend}. Correct {ncorrect}/64<br>Correct key: {utils.convert_to_hex(reference_key)}<br> Guessed key: {utils.convert_to_hex(bit_list)}'
        
        display(df.style.apply(utils.highlight_bits, key=key_list, axis=None).set_caption(caption).set_table_attributes('style="width: 100%;"'))

    def plot_success(self,resolution, index):
        """Plot success with matplotlib.

            resolution (int): sampling interval in traces
            index (int): attack number index.
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

            resolution (int): sampling interval in traces
            index (int): attack number index.

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
    
class cpa_round_1_output_x4_recover_x1_pool:
    """
    Class that implement a CPA attack on ASCON to retrieve the first
    half of the key. It uses the content of the register x4 for the leakage model.
    """
    def __init__(self, key, iv=[0x80, 0x40, 0x0c, 0x06, 0x00, 0x00, 0x00, 0x00], c_r=[0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xf0]):
        """
        Args:
            key (list): value of the correct key for comparison with the guessed key
            iv (list, optional): value of the initial value. Defaults to [0x80, 0x40, 0x0c, 0x06, 0x00, 0x00, 0x00, 0x00].
            c_r (list, optional): value of the round constant. Defaults first round constant to [0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xf0].
        """
        self.stats = [[IncrementalStatsMath() for _ in range(2**3)]for _ in range(64)]
        self.iv_bit = utils.bytearray_to_bitlist(iv)[::-1]
        self.c_r_bit = utils.bytearray_to_bitlist(c_r)[::-1]
        self.key_bit = utils.bytearray_to_bitlist(key)[::-1]
        
        self.HW = [bin(n).count("1") for n in range(0, 2**3)]
        self.success = []
        self.correct_list = []
        self.guess_corr = [[] for _ in range(64)]
    
    def find_max_subkeys(self, maxcpa, max_key_bit, i):
        """Function to find the guessed key bit with maximum correlation value.

        Args:
            maxcpa (list): list of correlation values. The indexes indicate the value of the guessed key
            max_key_bit (list): list where the bit of the guessed key are returned.
                                max_key_bit[0] -> first bit of the guessed key
                                max_key_bit[1] -> second bit of the guessed key
                                max_key_bit[2] -> third bit of the guessed key
                                max_key_bit[3] -> correlation value of the guessed key
                                max_key_bit[4] -> distance value of the guessed key from the second ranked guessed key
                                max_key_bit[5] -> multiplication between the correlation and the distance value of the guessed key
            i (int): index of the column where to calculate the guessed key bit.
        """
        guess = np.argmax(maxcpa[i])
        guess_key_bit = [int(bit) for bit in bin(guess)[2:].zfill(3)][::-1]
        self.guess_corr[i].append(maxcpa[i])
        
        sorted_corr = sorted(maxcpa[i], reverse=True)
        for b in range(3):
            max_key_bit[i].append(guess_key_bit[b])
        max_key_bit[i].append(sorted_corr[0])
        max_key_bit[i].append(sorted_corr[0]-sorted_corr[1])
        max_key_bit[i].append(sorted_corr[0]*(sorted_corr[0]-sorted_corr[1]))
        
    def find_key(self, max_key_bit, guess_key, i):
        """Function to find the value of the first half of the guessed key.

        Args:
            max_key_bit (list): list of the guessed key bits with maximum correlation
            guess_key (list): list where the guessed key is returned
            i (int): index of the column where to calculate the guessed key
        """
        max_corr = max_key_bit[i][3]
        max_diff_corr = max_key_bit[i][4]
        max_tot = max_key_bit[i][5]
        max_bit_0 = max_key_bit[i][0]
        max_bit_1 = max_key_bit[i][0]
        max_bit_2 = max_key_bit[i][0]
            
        if max_corr < max_key_bit[(i - 7) % 64][3]:
            max_corr = max_key_bit[(i - 7) % 64][3]
            max_bit_0 = max_key_bit[(i - 7) % 64][1]
            
        if max_diff_corr < max_key_bit[(i - 7) % 64][4]:
            max_diff_corr = max_key_bit[(i - 7) % 64][4]
            max_bit_1 = max_key_bit[(i - 7) % 64][1]
            
        if max_tot < max_key_bit[(i - 7) % 64][5]:
            max_tot = max_key_bit[(i - 7) % 64][5]
            max_bit_2 = max_key_bit[(i - 7) % 64][1]
            
        if max_corr < max_key_bit[(i - 41) % 64][3]:
            max_corr = max_key_bit[(i - 41) % 64][3]
            max_bit_0 = max_key_bit[(i - 41) % 64][2]
            
        if max_diff_corr < max_key_bit[(i - 41) % 64][4]:
            max_diff_corr = max_key_bit[(i - 41) % 64][4]
            max_bit_1 = max_key_bit[(i - 41) % 64][2]
            
        if max_tot < max_key_bit[(i - 41) % 64][5]:
            max_tot = max_key_bit[(i - 41) % 64][5]
            max_bit_2 = max_key_bit[(i - 41) % 64][2]
            
        if max_bit_0 == max_bit_1:
            max_bit = max_bit_0
        elif max_bit_0 == max_bit_2:
            max_bit = max_bit_0
        else:
            max_bit = max_bit_1
        
        guess_key[i] = max_bit
    
    def attack_leak_model(self, traces, nonces, sub_layer_type, callback, index):
        """Function that run the CPA attack.

        Args:
            traces (list): list of traces to process
            nonces (list): list of nonces.

            callback (int): specify the number of traces for the callback.
            index (int): attack number index.

        Returns:
            list: list of the best guessed keys for every callback
            list: list of the correlation values for every callback
        """
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
                    for bitnum in range(64)
                ]
                for result in results:
                    result.get()  # wait for each thread to complete

            with ThreadPool() as pool:
                results = [
                    pool.apply_async(self.find_max_subkeys, args=(maxcpa, max_key_bit, i))
                    for i in range(64)
                ]
                for result in results:
                    result.get()  # wait for each thread to complete
                
            with ThreadPool() as pool:
                results = [
                    pool.apply_async(self.find_key, args=(max_key_bit, guess_key, i))
                    for i in range(64)
                ]
                for result in results:
                    result.get()  # wait for each thread to complete
            
            best_guess_keys.append(guess_key)
            self.display_results(guess_key, index, cb, cb + callback)
            
        self.plot_correct(callback, index)
        self.plot_success(callback, index)

        return best_guess_keys, self.guess_corr

    def recover_x1(self, bitnum, callback_traces, callback_nonces, sub_layer_type, maxcpa):
        """ Function that calculate for every value of the subkey of the register x4 the correlation value

        Args:
            bitnum (int): value of the column in which calculate the correlation value.
            callback_traces (list): traces of the current callback to add to the previous callbacks traces.
            callback_nonces (list): nonces of the current callback to add to the previous callbacks nonces.
            sub_layer_type (sting): specify the type of S-box.
            maxcpa (list): list where the correlation values of the guessed subkeys are returned.
        """
        with ThreadPool() as pool:
            results = [
                pool.apply_async(self.key_correlation_1, args=(bitnum, kguess, callback_traces, callback_nonces, sub_layer_type, maxcpa))
                for kguess in range(0, 2**3)
            ]
            for result in results:
                result.get()  # wait for each thread to complete

    def key_correlation_1(self, bitnum, kguess, traces, nonces, sub_layer_type, maxcpa):
        """ Function that calculates for the register x4 the correlation values for a certain subkey

        Args:
            bitnum (int): value of the column in which calculate the correlation value.
            kguess (int): value of the subkey in which the correlation value is calculated.
            traces (list): traces of the current callback to add to the previous callbacks traces.
            nonces (list): nonces of the current callback to add to the previous callbacks nonces.
            sub_layer_type (string): specify the type of S-box.
            maxcpa (list): list where the correlation values of the guessed subkeys are returned.
        """
        def sub_layer(x1, x2, x3, x4, bitnum, rs, sub_layer_type):
            sbox_input = utils.bit_to_hex(self.iv_bit[(bitnum + rs) % 64], x1, x2^self.c_r_bit[(bitnum + rs) % 64], x3[(bitnum + rs) % 64], x4[(bitnum + rs) % 64])
            return utils.hex_to_bit(ascon.sbox(sub_layer_type, sbox_input))

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
            v = utils.bytearray_to_bitlist(text)[::-1]
            x3 = v[64:128]
            x4 = v[0:64]
            rs = [0, 7, 41]
            sub_layer_list = []
            for i in range(3):
                sub_layer_list.append(sub_layer(k[i], 0, x3, x4, bitnum, rs[i], sub_layer_type))
            S4 = sub_layer_list[0][4] ^ sub_layer_list[1][4] ^ sub_layer_list[2][4]
            hws.append(self.HW[x4[bitnum] ^ S4])

        self.stats[bitnum][kguess].add_data(traces, hws)
        o_t = self.stats[bitnum][kguess].std_dev_X()
        o_hws = self.stats[bitnum][kguess].std_dev_Y()
        correlation = self.stats[bitnum][kguess].covariance()
        cpaout = correlation / (o_t * o_hws)
        
        cpaout = apply_gaussian_filter(cpaout)
        cpaout = correlation_derivative(cpaout)

        maxcpa[bitnum][kguess] = max(abs(cpaout))
    
    def display_results(self,best_guess,index,tstart,tend):
        """ Function that calculates the number of correct bits and prints them to the screen in a table.

        Args:
            best_guess (list): list of the 64 guessed key bits.
            index (int): attack number index.
            tstart (int): trace number from which the callback started.
            tend (int): trace number from which the callback ended.
        """ 
        reference_key = self.key_bit[64:128][::-1]
        key_list = [reference_key[0:16],reference_key[16:32],reference_key[32:48],reference_key[48:64]]
        bit_list = best_guess[::-1]
        show_list = [bit_list[0:16],bit_list[16:32],bit_list[32:48],bit_list[48:64]]

        ncorrect = 0
        for r in range(4):
            for c in range(16):
                if show_list[r][c] == key_list[r][c]:
                    ncorrect += 1
                    
        self.correct_list.append(ncorrect)
        
        if ncorrect == 64:
            self.success.append(1)
        else:
            self.success.append(0)
        
        clear_output(wait=True)  
        df = utils.create_table_3(show_list)
        
        caption = f'Process {index}. Finished traces {tstart} to {tend}. Correct {ncorrect}/64<br>Correct key: {utils.convert_to_hex(reference_key)}<br> Guessed key: {utils.convert_to_hex(bit_list)}'
        
        display(df.style.apply(utils.highlight_bits, key=key_list, axis=None).set_caption(caption).set_table_attributes('style="width: 100%;"'))

    def plot_success(self,resolution, index):
        """Plot success with matplotlib.

            resolution (int): sampling interval in traces
            index (int): attack number index.

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

            resolution (int): sampling interval in traces.
            index (int): attack number index.

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
            for success in self.correct_list:
                print(success, file=correct_file)

        return plt
    
class cpa_round_1_pool:
    """
    Class that implement a CPA attack on ASCON. 
    It uses the content of the register x4 and x1 for the leakage model.
    Prima attacca x4 per trovare x1, poi attacca x1 per trovare x2
    """
    def __init__(self, key, iv=[0x80, 0x40, 0x0c, 0x06, 0x00, 0x00, 0x00, 0x00], c_r=[0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xf0]):
        """
        Args:
            key (list): value of the correct key for comparison with the guessed key
            iv (list, optional): value of the initial value. Defaults to [0x80, 0x40, 0x0c, 0x06, 0x00, 0x00, 0x00, 0x00].
            c_r (list, optional): value of the round constant. Defaults first round constant to [0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xf0].
        """
        self.stats_x4 = [[IncrementalStatsMath() for _ in range(2**3)]for _ in range(64)]
        self.stats_x1 = [[IncrementalStatsMath() for _ in range(2**3)]for _ in range(64)]
        self.iv_bit = utils.bytearray_to_bitlist(iv)[::-1]
        self.c_r_bit = utils.bytearray_to_bitlist(c_r)[::-1]
        self.key_bit = utils.bytearray_to_bitlist(key)[::-1]
        
        self.HW = [bin(n).count("1") for n in range(0, 2**3)]
        
        self.success = []
        self.correct_list = []
        
        self.success_x4 = []
        self.correct_list_x4 = []
        
        self.success_x1 = []
        self.correct_list_x1 = []
    
    def find_max_subkeys(self, maxcpa, max_key_bit, i):
        """Function to find the guessed key bit with maximum correlation value.

        Args:
            maxcpa (list): list of correlation values. The indexes indicate the value of the guessed key
            max_key_bit (list): list where the bit of the guessed key are returned.
                                max_key_bit[0] -> first bit of the guessed key
                                max_key_bit[1] -> second bit of the guessed key
                                max_key_bit[2] -> third bit of the guessed key
                                max_key_bit[3] -> correlation value of the guessed key
                                max_key_bit[4] -> distance value of the guessed key from the second ranked guessed key
                                max_key_bit[5] -> multiplication between the correlation and the distance value of the guessed key
            i (int): index of the column where to calculate the guessed key bit.
        """
        guess = np.argmax(maxcpa[i])
        guess_key_bit = [int(bit) for bit in bin(guess)[2:].zfill(3)][::-1]
        
        sorted_corr = sorted(maxcpa[i], reverse=True)
        for b in range(3):
            max_key_bit[i].append(guess_key_bit[b])
        max_key_bit[i].append(sorted_corr[0])
        max_key_bit[i].append(sorted_corr[0]-sorted_corr[1])
        max_key_bit[i].append(sorted_corr[0]*(sorted_corr[0]-sorted_corr[1]))
        
    def find_key_x4(self, max_key_bit, guess_key, i):
        """Function to find the value of the first half of the guessed key.

        Args:
            max_key_bit (list): list of the guessed key bits with maximum correlation
            guess_key (list): list where the guessed key is returned
            i (int): index of the column where to calculate the guessed key
        """
        max_corr = max_key_bit[i][3]
        max_diff_corr = max_key_bit[i][4]
        max_tot = max_key_bit[i][5]
        max_bit_0 = max_key_bit[i][0]
        max_bit_1 = max_key_bit[i][0]
        max_bit_2 = max_key_bit[i][0]
            
        if max_corr < max_key_bit[(i - 7) % 64][3]:
            max_corr = max_key_bit[(i - 7) % 64][3]
            max_bit_0 = max_key_bit[(i - 7) % 64][1]
            
        if max_diff_corr < max_key_bit[(i - 7) % 64][4]:
            max_diff_corr = max_key_bit[(i - 7) % 64][4]
            max_bit_1 = max_key_bit[(i - 7) % 64][1]
            
        if max_tot < max_key_bit[(i - 7) % 64][5]:
            max_tot = max_key_bit[(i - 7) % 64][5]
            max_bit_2 = max_key_bit[(i - 7) % 64][1]
            
        if max_corr < max_key_bit[(i - 41) % 64][3]:
            max_corr = max_key_bit[(i - 41) % 64][3]
            max_bit_0 = max_key_bit[(i - 41) % 64][2]
            
        if max_diff_corr < max_key_bit[(i - 41) % 64][4]:
            max_diff_corr = max_key_bit[(i - 41) % 64][4]
            max_bit_1 = max_key_bit[(i - 41) % 64][2]
            
        if max_tot < max_key_bit[(i - 41) % 64][5]:
            max_tot = max_key_bit[(i - 41) % 64][5]
            max_bit_2 = max_key_bit[(i - 41) % 64][2]
            
        if max_bit_0 == max_bit_1:
            max_bit = max_bit_0
        elif max_bit_0 == max_bit_2:
            max_bit = max_bit_0
        else:
            max_bit = max_bit_1
        
        guess_key[i] = max_bit
        
    def find_key_x1(self, max_key_bit, guess_key, x1, i):
        """Function to find the value of the second half of the guessed key.

        Args:
            max_key_bit (list): list of the guessed key bits with maximum correlation
            guess_key (list): list where the guessed key is returned
            x1 (list): list of the first half of the guessed key
            i (int): index of the column where to calculate the guessed key
        """
        max_corr = max_key_bit[i][3]
        max_diff_corr = max_key_bit[i][4]
        max_tot = max_key_bit[i][5]
        max_bit_0 = max_key_bit[i][0]
        max_bit_1 = max_key_bit[i][0]
        max_bit_2 = max_key_bit[i][0]
            
        if max_corr < max_key_bit[(i - 61) % 64][3]:
            max_corr = max_key_bit[(i - 61) % 64][3]
            max_bit_0 = max_key_bit[(i - 61) % 64][1]
            
        if max_diff_corr < max_key_bit[(i - 61) % 64][4]:
            max_diff_corr = max_key_bit[(i - 61) % 64][4]
            max_bit_1 = max_key_bit[(i - 61) % 64][1]
            
        if max_tot < max_key_bit[(i - 61) % 64][5]:
            max_tot = max_key_bit[(i - 61) % 64][5]
            max_bit_2 = max_key_bit[(i - 61) % 64][1]
            
        if max_corr < max_key_bit[(i - 39) % 64][3]:
            max_corr = max_key_bit[(i - 39) % 64][3]
            max_bit_0 = max_key_bit[(i - 39) % 64][2]
            
        if max_diff_corr < max_key_bit[(i - 39) % 64][4]:
            max_diff_corr = max_key_bit[(i - 39) % 64][4]
            max_bit_1 = max_key_bit[(i - 39) % 64][2]
            
        if max_tot < max_key_bit[(i - 39) % 64][5]:
            max_tot = max_key_bit[(i - 39) % 64][5]
            max_bit_2 = max_key_bit[(i - 39) % 64][2]
            
        if max_bit_0 == max_bit_1:
            max_bit = max_bit_0
        elif max_bit_0 == max_bit_2:
            max_bit = max_bit_0
        else:
            max_bit = max_bit_1
        
        guess_key[i] = max_bit ^ x1[i]
    
    def attack_leak_model(self, traces, nonces, sub_layer_type, callback, i):
        """Function that run the CPA attack.

        Args:
            traces (list): list of traces to process
            nonces (list): list of nonces.

            callback (int): specify the number of traces for the callback
            i (int): attack number index

        Returns:
            list: best guessed key
        """
        numtraces = np.shape(traces)[0]
        self.resolution = callback
        
        best_guess_keys = [] 

        # CPA attack on x4 to retrieve the first half of the key
        for cb in range(0, numtraces, callback):
            callback_traces = traces[cb:cb + callback]
            callback_nonces = nonces[cb:cb + callback]

            guess_key_x1 = [0] * 64
            maxcpa_x1 = [[[0] for _ in range(2**3)] for _ in range(64)]
            max_key_bit_x1 = [[] for _ in range(64)]

            # Calculation of the correlation for all the subkeys
            with ThreadPool() as pool:
                results = [
                    pool.apply_async(self.recover_x1, args=(bitnum, callback_traces, callback_nonces, sub_layer_type, maxcpa_x1))
                    for bitnum in range(64)
                ]
                for result in results:
                    result.get()  # wait for each thread to complete

            # Finding the subkey with the highest correlation value
            with ThreadPool() as pool:
                results = [
                    pool.apply_async(self.find_max_subkeys, args=(maxcpa_x1, max_key_bit_x1, i))
                    for i in range(64)
                ]
                for result in results:
                    result.get()  # wait for each thread to complete
                
            # Finding the bit of the guessed key with the highest correlation value
            with ThreadPool() as pool:
                results = [
                    pool.apply_async(self.find_key_x4, args=(max_key_bit_x1, guess_key_x1, i))
                    for i in range(64)
                ]
                for result in results:
                    result.get()  # wait for each thread to complete

            # Saving the number of correct bits and the success rate value
            self.correct_x1(guess_key_x1)
                
            clear_output(wait=True)  
            display("Process " + str(i) + ". Finished traces " + str(cb) + " to " + str(cb+callback) + ". (x4)")

        x1 = guess_key_x1

        print("Finished for " + str(i) + " the attack on x4")

        # CPA attack on x1 to retrieve the second half of the key
        for cb in range(0, numtraces, callback):
            callback_traces = traces[cb:cb + callback]
            callback_nonces = nonces[cb:cb + callback]
            
            guess_key_x2 = [0] * 64
            maxcpa_x2 = [[[0] for _ in range(2**3)] for _ in range(64)]
            max_key_bit_x2 = [[] for _ in range(64)]

            # Calculation of the correlation for all the subkeys        
            with ThreadPool() as pool:
                results = [
                    pool.apply_async(self.recover_x2, args=(bitnum, callback_traces, callback_nonces, sub_layer_type, maxcpa_x2, x1))
                    for bitnum in range(64)
                ]
                for result in results:
                    result.get()  # wait for each thread to complete

            # Finding the subkey with the highest correlation value  
            with ThreadPool() as pool:
                results = [
                    pool.apply_async(self.find_max_subkeys, args=(maxcpa_x2, max_key_bit_x2, i))
                    for i in range(64)
                ]
                for result in results:
                    result.get()  # wait for each thread to complete

            # Finding the bit of the guessed key with the highest correlation value   
            with ThreadPool() as pool:
                results = [
                    pool.apply_async(self.find_key_x1, args=(max_key_bit_x2, guess_key_x2, x1, i))
                    for i in range(64)
                ]
                for result in results:
                    result.get()  # wait for each thread to complete
                    
            guess_key = []
            for bit in x1[::-1]:
                guess_key.append(bit)
            for bit in guess_key_x2[::-1]:
                guess_key.append(bit)
            
            # Saving the number of correct bits and the success rate value
            self.correct_x2(guess_key_x2)
            # Displaying the results obtained
            clear_output(wait=True)  
            display("Process " + str(i) + ". Finished traces " + str(cb) + " to " + str(cb+callback) + ". (x1)")
            self.display_results(guess_key, i, cb, cb + callback)
            
        # Plotting the final results obtained
        self.plot_correct(callback, i)
        self.plot_success(callback, i)
        self.print_results(callback, i)

        return guess_key

    def recover_x1(self, bitnum, callback_traces, callback_nonces, sub_layer_type, maxcpa):
        """ Function that calculate for every value of the subkey of the register x4 the correlation value

        Args:
            bitnum (int): value of the column in which calculate the correlation value.
            callback_traces (list): traces of the current callback to add to the previous callbacks traces.
            callback_nonces (list): nonces of the current callback to add to the previous callbacks nonces.
            sub_layer_type (sting): specify the type of S-box.
            maxcpa (list): list where the correlation values of the guessed subkeys are returned.
        """
        with ThreadPool() as pool:
            results = [
                pool.apply_async(self.key_correlation_x4, args=(bitnum, kguess, callback_traces, callback_nonces, sub_layer_type, maxcpa))
                for kguess in range(0, 2**3)
            ]
            for result in results:
                result.get()  # wait for each thread to complete
                
    def recover_x2(self, bitnum, callback_traces, callback_nonces, sub_layer_type, maxcpa, x1):
        """ Function that calculate for every value of the subkey of the register x1 the correlation value

        Args:
            bitnum (int): value of the column in which calculate the correlation value.
            callback_traces (list): traces of the current callback to add to the previous callbacks traces.
            callback_nonces (list): nonces of the current callback to add to the previous callbacks nonces.
            sub_layer_type (sting): specify the type of S-box.
            maxcpa (list): list where the correlation values of the guessed subkeys are returned.
            x1 (list): list of the guessed bits of the register x1.
        """
        with ThreadPool() as pool:
            results = [
                pool.apply_async(self.key_correlation_x1, args=(bitnum, kguess, callback_traces, callback_nonces, sub_layer_type, maxcpa, x1))
                for kguess in range(0, 2**3)
            ]
            for result in results:
                result.get()  # wait for each thread to complete

    def key_correlation_x4(self, bitnum, kguess, traces, nonces, sub_layer_type, maxcpa):
        """ Function that calculates for the register x4 the correlation values for a certain subkey

        Args:
            bitnum (int): value of the column in which calculate the correlation value.
            kguess (int): value of the subkey in which the correlation value is calculated.
            traces (list): traces of the current callback to add to the previous callbacks traces.
            nonces (list): nonces of the current callback to add to the previous callbacks nonces.
            sub_layer_type (string): specify the type of S-box.
            maxcpa (list): list where the correlation values of the guessed subkeys are returned.
        """
        def sub_layer(x1, x2, x3, x4, bitnum, rs, sub_layer_type):
            sbox_input = utils.bit_to_hex(self.iv_bit[(bitnum + rs) % 64], x1, x2^self.c_r_bit[(bitnum + rs) % 64], x3[(bitnum + rs) % 64], x4[(bitnum + rs) % 64])
            return utils.hex_to_bit(ascon.sbox(sub_layer_type, sbox_input))

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

        # Calculating the leakage value for each nonce
        for text in nonces:
            v = utils.bytearray_to_bitlist(text)[::-1]
            x3 = v[64:128]
            x4 = v[0:64]
            rs = [0, 7, 41]
            sub_layer_list = []
            # Guessing the content of register x4 after one round
            for i in range(3):
                sub_layer_list.append(sub_layer(k[i], 0, x3, x4, bitnum, rs[i], sub_layer_type))
            S4 = sub_layer_list[0][4] ^ sub_layer_list[1][4] ^ sub_layer_list[2][4]
            # Calculating the Hamming Distance for the x4 register
            hws.append(self.HW[x4[bitnum] ^ S4])

        # Calculating the correlation value
        self.stats_x4[bitnum][kguess].add_data(traces, hws)
        o_t = self.stats_x4[bitnum][kguess].std_dev_X()
        o_hws = self.stats_x4[bitnum][kguess].std_dev_Y()
        correlation = self.stats_x4[bitnum][kguess].covariance()
        cpaout = correlation / (o_t * o_hws)
        
        # Processing correlation values ​​for better result
        cpaout = apply_gaussian_filter(cpaout)
        cpaout = correlation_derivative(cpaout)

        # Selecting the highest correlation value
        maxcpa[bitnum][kguess] = max(abs(cpaout))
        
    def key_correlation_x1(self, bitnum, kguess, traces, nonces, sub_layer_type, maxcpa, x1):
        """ Function that calculates for the register x1 the correlation values for a certain subkey

        Args:
            bitnum (int): value of the column in which calculate the correlation value.
            kguess (int): value of the subkey in which the correlation value is calculated.
            traces (list): traces of the current callback to add to the previous callbacks traces.
            nonces (list): nonces of the current callback to add to the previous callbacks nonces.
            sub_layer_type (string): specify the type of S-box.
            maxcpa (list): list where the correlation values of the guessed subkeys are returned.
            x1 (list): list of the guessed bits of the register x1.
        """
        def sub_layer(x1, x2, x3, x4, bitnum, rs, sub_layer_type):
            sbox_input = utils.bit_to_hex(self.iv_bit[(bitnum + rs) % 64], x1[(bitnum + rs) % 64], x2 ^ self.c_r_bit[(bitnum + rs) % 64], x3[(bitnum + rs) % 64], x4[(bitnum + rs) % 64])
            return utils.hex_to_bit(ascon.sbox(sub_layer_type, sbox_input))

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

        # Calculating the leakage value for each nonce
        for text in nonces:
            v = utils.bytearray_to_bitlist(text)[::-1]
            x3 = v[64:128]
            x4 = v[0:64]
            rs = [0, 61, 39]
            sub_layer_list = []
            # Guessing the content of register x4 after one round
            for i in range(3):
                sub_layer_list.append(sub_layer(x1, k[i], x3, x4, bitnum, rs[i], sub_layer_type))
            S1 = sub_layer_list[0][1] ^ sub_layer_list[1][1] ^ sub_layer_list[2][1]
            # Calculating the Hamming Distance for the x4 register
            hws.append(self.HW[x1[bitnum] ^ S1])

        # Calculating the correlation value
        self.stats_x1[bitnum][kguess].add_data(traces, hws)
        o_t = self.stats_x1[bitnum][kguess].std_dev_X()
        o_hws = self.stats_x1[bitnum][kguess].std_dev_Y()
        correlation = self.stats_x1[bitnum][kguess].covariance()
        cpaout = correlation / (o_t * o_hws)
        
        # Processing correlation values ​​for better result
        cpaout = apply_gaussian_filter(cpaout)
        cpaout = correlation_derivative(cpaout)

        # Selecting the highest correlation value
        maxcpa[bitnum][kguess] = max(abs(cpaout))
    
    def display_results(self,best_guess,i,tstart,tend):
        """ Function that calculates the number of correct bits and prints them to the screen in a table.

        Args:
            best_guess (list): list of the 128 guessed key bits.
            i (int): attack number index.
            tstart (int): trace number from which the callback started.
            tend (int): trace number from which the callback ended.
        """  
        reference_key = self.key_bit[::-1]
        key_list = [reference_key[0:16],reference_key[16:32],reference_key[32:48],reference_key[48:64],reference_key[64:80],reference_key[80:96],reference_key[96:112],reference_key[112:128]]
        bit_list = best_guess
        show_list = [bit_list[0:16],bit_list[16:32],bit_list[32:48],bit_list[48:64],bit_list[64:80],bit_list[80:96],bit_list[96:112],bit_list[112:128]]

        ncorrect = 0
        for r in range(8):
            for c in range(16):
                if show_list[r][c] == key_list[r][c]:
                    ncorrect += 1
                    
        self.correct_list.append(ncorrect)
        
        if ncorrect == 128:
            self.success.append(1)
        else:
            self.success.append(0)
        
        clear_output(wait=True)  
        df = create_table_total(show_list)
        
        caption = f'Process {i}.Finished traces {tstart} to {tend}. Correct {ncorrect}/128<br>Correct key: {utils.convert_to_hex(reference_key)}<br> Guessed key: {utils.convert_to_hex(bit_list)}'
        
        display(df.style.apply(utils.highlight_bits, key=key_list, axis=None).set_caption(caption).set_table_attributes('style="width: 100%;"'))

    def correct_x1(self,best_guess):
        """ Function that saves the number of correct bits and the success rate for the attack on the x4 register.

        Args:
            best_guess (list): list of the 64 guessed key bits.
        """        
        reference_key = self.key_bit[64:128][::-1]
        key_list = [reference_key[0:16],reference_key[16:32],reference_key[32:48],reference_key[48:64]]
        bit_list = best_guess[::-1]
        show_list = [bit_list[0:16],bit_list[16:32],bit_list[32:48],bit_list[48:64]]

        ncorrect = 0
        for r in range(4):
            for c in range(16):
                if show_list[r][c] == key_list[r][c]:
                    ncorrect += 1
                    
        self.correct_list_x4.append(ncorrect)
        
        if ncorrect == 64:
            self.success_x4.append(1)
        else:
            self.success_x4.append(0)
        
    def correct_x2(self,best_guess):
        """ Function that saves the number of correct bits and the success rate for the attack on the x1 register.

        Args:
            best_guess (list): list of the 64 guessed key bits.
        """ 
        reference_key = self.key_bit[0:64][::-1]
        key_list = [reference_key[0:16],reference_key[16:32],reference_key[32:48],reference_key[48:64]]
        bit_list = best_guess[::-1]
        show_list = [bit_list[0:16],bit_list[16:32],bit_list[32:48],bit_list[48:64]]

        ncorrect = 0
        for r in range(4):
            for c in range(16):
                if show_list[r][c] == key_list[r][c]:
                    ncorrect += 1
                    
        self.correct_list_x1.append(ncorrect)
        
        if ncorrect == 64:
            self.success_x1.append(1)
        else:
            self.success_x1.append(0)
            
    def print_results(self, callback, index):
        """ Function that saves to file the number of correct bits and the success rate for the attack on registers x4 and x1.

        Args:
            callback (int): number of tracks for each callback.
            index (int): attack number index.
        """        
        ncallback = len(self.correct_list_x1) * callback
        filename = "./results/success_rate/success_rate_" + str(ncallback) + "_x1_" + str(index) + ".txt"
        with open(filename,'w') as success_file_x1:
            for success in self.success_x4:
                print(success, file=success_file_x1)
        filename = "./results/success_rate/success_rate_" + str(ncallback) + "_x2_" + str(index) + ".txt"
        with open(filename,'w') as success_file_x2:
            for success in self.success_x1:
                print(success, file=success_file_x2)
        filename = "./results/success_rate/correct_" + str(ncallback) + "_x1_" + str(index) + ".txt"
        with open(filename,'w') as correct_file_x1:
            for correct in self.correct_list_x4:
                print(correct, file=correct_file_x1)
        filename = "./results/success_rate/correct_" + str(ncallback) + "_x2_" + str(index) + ".txt"
        with open(filename,'w') as correct_file_x2:
            for correct in self.correct_list_x1:
                print(correct, file=correct_file_x2)

    def plot_success(self,resolution, index):
        """ Plot the success rate with matplotlib.

        Args:
            resolution(int): sampling interval in traces.
            index(int) : attack number index.
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
        """ Plot the number of correct bit with matplotlib.

        Args:
            resolution(int): sampling interval in traces.
            index(int) : attack number index.
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
    
class cpa_round_1_output_x0_x4_recover_x1_pool:
    """
    Class that implement a CPA attack on ASCON to retrieve the first
    half of the key. It uses the content of the register x0 and x4 for the leakage model.
    Si attacca x0 e x4 per recuperare x1, e poi si attacca x1 per recuperare x2. 
    """
    def __init__(self, key, iv=[0x80, 0x40, 0x0c, 0x06, 0x00, 0x00, 0x00, 0x00], c_r=[0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xf0]):
        """
        Args:
            key (list): value of the correct key for comparison with the guessed key
            iv (list, optional): value of the initial value. Defaults to [0x80, 0x40, 0x0c, 0x06, 0x00, 0x00, 0x00, 0x00].
            c_r (list, optional): value of the round constant. Defaults first round constant to [0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xf0].
        """
        self.stats_x0 = [[IncrementalStatsMath() for _ in range(2**3)]for _ in range(64)]
        self.stats_x4 = [[IncrementalStatsMath() for _ in range(2**3)]for _ in range(64)]
        self.iv_bit = utils.bytearray_to_bitlist(iv)[::-1]
        self.c_r_bit = utils.bytearray_to_bitlist(c_r)[::-1]
        self.key_bit = utils.bytearray_to_bitlist(key)[::-1]
        
        self.HW = [bin(n).count("1") for n in range(0, 2**3)]
        self.success = []
        self.correct_list = []
        self.guess_corr = [[[] for _ in range(64)] for _ in range(2)]
    
    def find_max_subkeys(self, maxcpa, max_key_bit, i, r):
        """Function to find the guessed key bit with maximum correlation value.

        Args:
            maxcpa (list): list of correlation values. The indexes indicate the value of the guessed key
            max_key_bit (list): list where the bit of the guessed key are returned.
                                max_key_bit[0] -> first bit of the guessed key
                                max_key_bit[1] -> second bit of the guessed key
                                max_key_bit[2] -> third bit of the guessed key
                                max_key_bit[3] -> correlation value of the guessed key
                                max_key_bit[4] -> distance value of the guessed key from the second ranked guessed key
                                max_key_bit[5] -> multiplication between the correlation and the distance value of the guessed key
            i (int): index of the column where to calculate the guessed key bit.
            r (int): index of the register where to calculate the guessed key bit. 0 for register x0, 1 for register x4
        """
        guess = np.argmax(maxcpa[i])
        guess_key_bit = [int(bit) for bit in bin(guess)[2:].zfill(3)][::-1]
        self.guess_corr[r][i].append(maxcpa[i])
        
        sorted_corr = sorted(maxcpa[i], reverse=True)
        for b in range(3):
            max_key_bit[i].append(guess_key_bit[b])
        max_key_bit[i].append(sorted_corr[0])
        max_key_bit[i].append(sorted_corr[0]-sorted_corr[1])
        max_key_bit[i].append(sorted_corr[0]*(sorted_corr[0]-sorted_corr[1]))
        
    def find_key(self, max_key_bit_x0, max_key_bit_x4, guess_key, i):
        """Function to find the value of the first half of the guessed key.

        Args:
            max_key_bit_x0 (list): list of the guessed key bits with maximum correlation for register x0
            max_key_bit_x4 (list): list of the guessed key bits with maximum correlation for register x4
            guess_key (list): list where the guessed key is returned
            i (int): index of the column where to calculate the guessed key
        """
        max_corr = max_key_bit_x0[i][3]
        max_diff_corr = max_key_bit_x0[i][4]
        max_bit_0 = max_key_bit_x0[i][0]
            
        if max_corr < max_key_bit_x0[(i - 19) % 64][3] and max_diff_corr < 0.002:
            max_corr = max_key_bit_x0[(i - 19) % 64][3]
            max_diff_corr = max_key_bit_x0[(i - 19) % 64][4]
            max_bit_0 = max_key_bit_x0[(i - 19) % 64][1]
            
        if max_corr < max_key_bit_x0[(i - 28) % 64][3] and max_diff_corr < 0.002:
            max_corr = max_key_bit_x0[(i - 28) % 64][3]
            max_diff_corr = max_key_bit_x0[(i - 28) % 64][4]
            max_bit_0 = max_key_bit_x0[(i - 28) % 64][2]
            
        if max_corr < max_key_bit_x4[(i) % 64][3] and max_diff_corr < 0.002:
            max_corr = max_key_bit_x4[(i) % 64][3]
            max_diff_corr = max_key_bit_x4[(i) % 64][4]
            max_bit_0 = max_key_bit_x4[(i) % 64][0]
            
        if max_corr < max_key_bit_x4[(i-7) % 64][3] and max_diff_corr < 0.002:
            max_corr = max_key_bit_x4[(i-7) % 64][3]
            max_diff_corr = max_key_bit_x4[(i-7) % 64][4]
            max_bit_0 = max_key_bit_x4[(i-7) % 64][1]
            
        if max_corr < max_key_bit_x4[(i-41) % 64][3] and max_diff_corr < 0.002:
            max_corr = max_key_bit_x4[(i-41) % 64][3]
            max_diff_corr = max_key_bit_x4[(i-41) % 64][4]
            max_bit_0 = max_key_bit_x4[(i-41) % 64][2]
        
        guess_key[i] = max_bit_0
    
    def attack_leak_model(self, traces, nonces, sub_layer_type, callback, i):
        """Function that run the CPA attack.

        Args:
            traces (list): list of traces to process
            nonces (list): list of nonces.

            callback (int): specify the number of traces for the callback
            i (int): attack number index

        Returns:
            list: list of the best guessed keys for every callback
            list: list of the correlation values for every callback
        """
        numtraces = np.shape(traces)[0]
        self.resolution = callback
        
        best_guess_keys = [] 

        for cb in range(0, numtraces, callback):
            callback_traces = traces[cb:cb + callback]
            callback_nonces = nonces[cb:cb + callback]

            guess_key = [0] * 64
            maxcpa_x0 = [[[0] for _ in range(2**3)] for _ in range(64)]
            maxcpa_x4 = [[[0] for _ in range(2**3)] for _ in range(64)]
            max_key_bit_x0 = [[] for _ in range(64)]
            max_key_bit_x4 = [[] for _ in range(64)]

            with ThreadPool() as pool:
                results = [
                    pool.apply_async(self.recover_x1_x0, args=(bitnum, callback_traces, callback_nonces, sub_layer_type, maxcpa_x0))
                    for bitnum in range(64)
                ]
                for result in results:
                    result.get()  # wait for each thread to complete
                    
            with ThreadPool() as pool:
                results = [
                    pool.apply_async(self.recover_x1_x4, args=(bitnum, callback_traces, callback_nonces, sub_layer_type, maxcpa_x4))
                    for bitnum in range(64)
                ]
                for result in results:
                    result.get()  # wait for each thread to complete

            with ThreadPool() as pool:
                results = [
                    pool.apply_async(self.find_max_subkeys, args=(maxcpa_x0, max_key_bit_x0, i, 0))
                    for i in range(64)
                ]
                for result in results:
                    result.get()  # wait for each thread to complete
                    
            with ThreadPool() as pool:
                results = [
                    pool.apply_async(self.find_max_subkeys, args=(maxcpa_x4, max_key_bit_x4, i, 1))
                    for i in range(64)
                ]
                for result in results:
                    result.get()  # wait for each thread to complete
                
            with ThreadPool() as pool:
                results = [
                    pool.apply_async(self.find_key, args=(max_key_bit_x0, max_key_bit_x4, guess_key, i))
                    for i in range(64)
                ]
                for result in results:
                    result.get()  # wait for each thread to complete
            
            best_guess_keys.append(guess_key)
            self.display_results(guess_key, cb, cb + callback)
            
            if cb == 975:
                self.plot_correct(callback, i)
                self.plot_success(callback, i)
                print("Reached for " + str(i) + " 1000 traces")
            
        self.plot_correct(callback, i)
        self.plot_success(callback, i)

        return best_guess_keys, self.guess_corr

    def recover_x1_x0(self, bitnum, callback_traces, callback_nonces, sub_layer_type, maxcpa_x0):
        """ Function that calculate for every value of the subkey of the register x0 the correlation value

        Args:
            bitnum (int): value of the column in which calculate the correlation value.
            callback_traces (list): traces of the current callback to add to the previous callbacks traces.
            callback_nonces (list): nonces of the current callback to add to the previous callbacks nonces.
            sub_layer_type (sting): specify the type of S-box.
            maxcpa_x0 (list): list where the correlation values of the guessed subkeys are returned.
        """
        with ThreadPool() as pool:
            results = [
                pool.apply_async(self.key_correlation_x0, args=(bitnum, kguess, callback_traces, callback_nonces, sub_layer_type, maxcpa_x0))
                for kguess in range(0, 2**3)
            ]
            for result in results:
                result.get()  # wait for each thread to complete
                
    def recover_x1_x4(self, bitnum, callback_traces, callback_nonces, sub_layer_type, maxcpa_x4):
        """ Function that calculate for every value of the subkey of the register x4 the correlation value

        Args:
            bitnum (int): value of the column in which calculate the correlation value.
            callback_traces (list): traces of the current callback to add to the previous callbacks traces.
            callback_nonces (list): nonces of the current callback to add to the previous callbacks nonces.
            sub_layer_type (sting): specify the type of S-box.
            maxcpa_x4 (list): list where the correlation values of the guessed subkeys are returned.
        """
        with ThreadPool() as pool:
            results = [
                pool.apply_async(self.key_correlation_x4, args=(bitnum, kguess, callback_traces, callback_nonces, sub_layer_type, maxcpa_x4))
                for kguess in range(0, 2**3)
            ]
            for result in results:
                result.get()  # wait for each thread to complete

    def key_correlation_x0(self, bitnum, kguess, traces, nonces, sub_layer_type, maxcpa):
        """ Function that calculates for the register x0 the correlation values for a certain subkey

        Args:
            bitnum (int): value of the column in which calculate the correlation value.
            kguess (int): value of the subkey in which the correlation value is calculated.
            traces (list): traces of the current callback to add to the previous callbacks traces.
            nonces (list): nonces of the current callback to add to the previous callbacks nonces.
            sub_layer_type (string): specify the type of S-box.
            maxcpa (list): list where the correlation values of the guessed subkeys are returned.
        """
        def sub_layer(x1, x2, x3, x4, bitnum, rs, sub_layer_type):
            sbox_input = utils.bit_to_hex(self.iv_bit[(bitnum + rs) % 64], x1, x2 ^ self.c_r_bit[(bitnum + rs) % 64], x3[(bitnum + rs) % 64], x4[(bitnum + rs) % 64])
            return utils.hex_to_bit(ascon.sbox(sub_layer_type, sbox_input))


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
            v = utils.bytearray_to_bitlist(text)[::-1]
            x3 = v[64:128]
            x4 = v[0:64]
            rs = [0, 19, 28]
            sub_layer_list = []
            for i in range(3):
                sub_layer_list.append(sub_layer(k[i], 0, x3, x4, bitnum, rs[i], sub_layer_type))
            S0 = sub_layer_list[0][0] ^ sub_layer_list[1][0] ^ sub_layer_list[2][0]
            hws.append(self.HW[self.iv_bit[bitnum] ^ S0])

        self.stats_x0[bitnum][kguess].add_data(traces, hws)
        o_t = self.stats_x0[bitnum][kguess].std_dev_X()
        o_hws = self.stats_x0[bitnum][kguess].std_dev_Y()
        correlation = self.stats_x0[bitnum][kguess].covariance()
        cpaout = correlation / (o_t * o_hws)
        
        cpaout = apply_gaussian_filter(cpaout)
        cpaout = correlation_derivative(cpaout)

        maxcpa[bitnum][kguess] = max(abs(cpaout))
        
    def key_correlation_x4(self, bitnum, kguess, traces, nonces, sub_layer_type, maxcpa):
        """ Function that calculates for the register x4 the correlation values for a certain subkey

        Args:
            bitnum (int): value of the column in which calculate the correlation value.
            kguess (int): value of the subkey in which the correlation value is calculated.
            traces (list): traces of the current callback to add to the previous callbacks traces.
            nonces (list): nonces of the current callback to add to the previous callbacks nonces.
            sub_layer_type (string): specify the type of S-box.
            maxcpa (list): list where the correlation values of the guessed subkeys are returned.
        """
        def sub_layer(x1, x2, x3, x4, bitnum, rs, sub_layer_type):
            sbox_input = utils.bit_to_hex(self.iv_bit[(bitnum + rs) % 64], x1, x2 ^ self.c_r_bit[(bitnum + rs) % 64], x3[(bitnum + rs) % 64], x4[(bitnum + rs) % 64])
            return utils.hex_to_bit(ascon.sbox(sub_layer_type, sbox_input))

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
            v = utils.bytearray_to_bitlist(text)[::-1]
            x3 = v[64:128]
            x4 = v[0:64]
            rs = [0, 7, 41]
            sub_layer_list = []
            for i in range(3):
                sub_layer_list.append(sub_layer(k[i], 0, x3, x4, bitnum, rs[i], sub_layer_type))
            S4 = sub_layer_list[0][4] ^ sub_layer_list[1][4] ^ sub_layer_list[2][4]
            hws.append(self.HW[x4[bitnum] ^ S4])

        self.stats_x4[bitnum][kguess].add_data(traces, hws)
        o_t = self.stats_x4[bitnum][kguess].std_dev_X()
        o_hws = self.stats_x4[bitnum][kguess].std_dev_Y()
        correlation = self.stats_x4[bitnum][kguess].covariance()
        cpaout = correlation / (o_t * o_hws)
        
        cpaout = apply_gaussian_filter(cpaout)
        cpaout = correlation_derivative(cpaout)

        maxcpa[bitnum][kguess] = max(abs(cpaout))
    
    def display_results(self,best_guess,tstart,tend):
        """ Function that calculates the number of correct bits and prints them to the screen in a table.

        Args:
            best_guess (list): list of the 64 guessed key bits.
            tstart (int): trace number from which the callback started.
            tend (int): trace number from which the callback ended.
        """  
        reference_key = self.key_bit[64:128][::-1]
        key_list = [reference_key[0:16],reference_key[16:32],reference_key[32:48],reference_key[48:64]]
        bit_list = best_guess[::-1]
        show_list = [bit_list[0:16],bit_list[16:32],bit_list[32:48],bit_list[48:64]]

        ncorrect = 0
        for r in range(4):
            for c in range(16):
                if show_list[r][c] == key_list[r][c]:
                    ncorrect += 1
                    
        self.correct_list.append(ncorrect)
        
        if ncorrect == 64:
            self.success.append(1)
        else:
            self.success.append(0)
        
        clear_output(wait=True)  
        df = utils.create_table_3(show_list)
        
        caption = f'Finished traces {tstart} to {tend}. Correct {ncorrect}/64<br>Correct key: {utils.convert_to_hex(reference_key)}<br> Guessed key: {utils.convert_to_hex(bit_list)}'
        
        display(df.style.apply(utils.highlight_bits, key=key_list, axis=None).set_caption(caption).set_table_attributes('style="width: 100%;"'))

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
    
    def plot_corr(self, bitnum, r):
        """Plot correlation with matplotlib.

            bitnum: number of bit to plot the correlation
            start: initial sample to plot
            finish: final sample to plot
        
        """
        correct_key = [self.key_bit[((bitnum) % 64 ) + 64], self.key_bit[((19 + bitnum) % 64) + 64], self.key_bit[((28 + bitnum) % 64) + 64]][::-1]
        guess_corr = [[] for _ in range(2**3)]
        for element in self.guess_corr[r][bitnum]:
            for i in range(2**3):
                guess_corr[i].append(element[i])

        fig, ax1 = plt.subplots(nrows=1, ncols=1, sharex=True, figsize=[18,12])

        xticks_samples = range(len(guess_corr[0]))
        xtick = [x*self.resolution+self.resolution for x in xticks_samples]

        t = "Correlation plot " + str(r) + " for the guessed key " + str(bitnum) + "[k[" + str(((bitnum) % 64) + 64) + "], k[" + str(((bitnum + 19) % 64) + 64) + "], k[" + str(((bitnum + 28) % 64) + 64) + "]]"
        plt.title(t)
        ax1.set_xlabel("# Traces")
        ax1.set_ylabel("Correlation")

        for i in range(2**3):
            ax1.plot(xtick, guess_corr[i], color=mcolors.CSS4_COLORS["orange"], alpha=0.5)
        ax1.plot(xtick, guess_corr[int(''.join(str(bit) for bit in correct_key), 2)], color=mcolors.CSS4_COLORS["red"], alpha=0.5)
        
        name_fig = "./Figures/corr_" + str(xtick[len(xtick)-1]) + "_" + str(bitnum) + "_" + str(r) + ".png"
        plt.savefig(name_fig)
    
        return plt
    
