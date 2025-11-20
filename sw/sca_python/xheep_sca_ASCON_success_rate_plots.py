#!/usr/bin/env python3

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import json

# Function for the key rank vs traces plot of the selected key bit index
def plot_key_rank_vs_traces(rank_vs_traces_list, key_bit_index, sbox_type, resolution, register_index):
    plt.figure()
    #plt.title(f"Key Rank vs Number of Traces - Key Bit Index {key_bit_index}")
    plt.xlabel("Number of Traces", fontsize=17)
    plt.ylabel("Key Rank (0=best, 7=worst)", fontsize=17)

    ranks = rank_vs_traces_list[key_bit_index]
    x_vals = np.arange(1, len(ranks) + 1) * resolution
    plt.plot(x_vals, ranks, label=f'State Reg S{register_index} - Key Bit {key_bit_index} - S-box {sbox_type}')

    ax = plt.gca()
    formatter = mticker.ScalarFormatter(useMathText=True)
    formatter.set_powerlimits((0, 0))
    ax.xaxis.set_major_formatter(formatter)
    ax.ticklabel_format(axis='x', style='sci', scilimits=(0,0))
    ax.xaxis.get_offset_text().set_fontsize(15)

    plt.ylim(-1, 8)
    plt.yticks(range(8))
    plt.grid(True, alpha=0.3)
    plt.legend(loc='best')
    plt.savefig("../x-heep/Graphs/ASCON_c/ASCON_key_rank_vs_traces" + f"_S{register_index}_sbox_{sbox_type}_bit_{key_bit_index}.png")
    # plt.show()

# Function for the success rate vs traces plot
def plot_success_rate_vs_traces(success_rate_list, sbox_type, resolution, register_index):
    plt.figure()
    #plt.title(f"Success Rate vs Number of Traces - S-box Type {sbox_type}")
    plt.xlabel("Number of Traces", fontsize=17)
    plt.ylabel("Success Rate (%)", fontsize=17)

    success_rates = success_rate_list
    x_vals = np.arange(1, len(success_rates) + 1) * resolution
    plt.plot(x_vals, success_rates, label=f'State Reg S{register_index} - S-box {sbox_type}')

    ax = plt.gca()
    formatter = mticker.ScalarFormatter(useMathText=True)
    formatter.set_powerlimits((0, 0))
    ax.xaxis.set_major_formatter(formatter)
    ax.ticklabel_format(axis='x', style='sci', scilimits=(0,0))
    ax.xaxis.get_offset_text().set_fontsize(15)

    plt.ylim(0, 105)
    plt.yticks(range(0, 101, 10))
    plt.grid(True, alpha=0.3)
    plt.legend(loc='best')
    plt.savefig("../x-heep/Graphs/ASCON_c/ASCON_success_rate_vs_traces" + f"_S{register_index}_sbox_{sbox_type}.png")
    # plt.show()

resolution = 100 # Use 100 for ASCON standard sbox, 1500 for all other sboxes

# If true, the script will generate a plot for the key rank of the selected key bit and the 
# success rate for both registers S0 and S1, for the selected S-box.
single_sbox_plots = True

# If true, the script will generate a plot with the success rates of all S-boxes overlapped for
# both registers S0 and S1.
overlapped_success_rate_plots = False

if single_sbox_plots:
    sbox_type = "lut_ascon" # Options: lut_ascon, lut_bilgin, lut_allouzi, lut_lu_4, lut_lu_5, lut_lu_6, lut_lu_7

    success_rate_file_S0 = f"../x-heep/Graphs/ASCON_c/ASCON_success_rate_parallel_S0_sbox_{sbox_type}.json"
    key_ranks_file_S0 = f"../x-heep/Graphs/ASCON_c/ASCON_key_ranks_parallel_S0_sbox_{sbox_type}.json"

    success_rate_file_S1 = f"../x-heep/Graphs/ASCON_c/ASCON_success_rate_parallel_S1_sbox_{sbox_type}.json"
    key_ranks_file_S1 = f"../x-heep/Graphs/ASCON_c/ASCON_key_ranks_parallel_S1_sbox_{sbox_type}.json"

    print(f"Generating plots for S-box: {sbox_type}\n")

    # Load data for S0 and plot
    with open(success_rate_file_S0, "r") as f:
        success_rate_vs_traces_0 = json.load(f)
        print("Generating Success Rate vs Traces plot for state register S0...")
        plot_success_rate_vs_traces(success_rate_vs_traces_0, sbox_type, resolution, 0)

    with open(key_ranks_file_S0, "r") as f:
        key_ranks_0 = json.load(f)
        bit = "11"
        print("Generating Key Rank vs Traces plot for state register S0, bit " + bit + "...")
        plot_key_rank_vs_traces(key_ranks_0, bit, sbox_type, resolution, 0) # Example for key bit index 11


    # Load data for S1 and plot
    with open(success_rate_file_S1, "r") as f:
        success_rate_vs_traces_1 = json.load(f)
        print("Generating Success Rate vs Traces plot for state register S1...")
        plot_success_rate_vs_traces(success_rate_vs_traces_1, sbox_type, resolution, 1)

    with open(key_ranks_file_S1, "r") as f:
        key_ranks_1 = json.load(f)
        bit = "46"
        print("Generating Key Rank vs Traces plot for state register S1, bit " + bit + "...")
        plot_key_rank_vs_traces(key_ranks_1, bit, sbox_type, resolution, 1) # Example for key bit index 46


if overlapped_success_rate_plots:
    print("Generating Overlapped Success Rate vs Traces plots for all S-boxes...\n")
    # sbox_types = ["lut_ascon", "lut_bilgin", "lut_allouzi", "lut_lu_4", "lut_lu_5", "lut_lu_6", "lut_lu_7"]
    sbox_types = ["lut_bilgin", "lut_allouzi", "lut_lu_4", "lut_lu_5", "lut_lu_6"]#, "lut_lu_7"]

    for register_index in [0, 1]:
        plt.figure()
        plt.xlabel("Number of Traces", fontsize=17)
        plt.ylabel("Success Rate (%)", fontsize=17)

        for sbox in sbox_types:
            success_rate_file = f"../x-heep/Graphs/ASCON_c/ASCON_success_rate_parallel_S{register_index}_sbox_{sbox}.json"
            with open(success_rate_file, "r") as f:
                success_rate_vs_traces = json.load(f)

            success_rates = success_rate_vs_traces
            x_vals = np.arange(1, len(success_rates) + 1) * resolution
            plt.plot(x_vals, success_rates, label=f'S-box {sbox}')

        ax = plt.gca()
        formatter = mticker.ScalarFormatter(useMathText=True)
        formatter.set_powerlimits((0, 0))
        ax.xaxis.set_major_formatter(formatter)
        ax.ticklabel_format(axis='x', style='sci', scilimits=(0,0))
        ax.xaxis.get_offset_text().set_fontsize(15)

        plt.ylim(0, 105)
        plt.yticks(range(0, 101, 10))
        plt.grid(True, alpha=0.3)
        plt.legend(loc='best')
        plt.savefig("../x-heep/Graphs/ASCON_c/ASCON_success_rate_vs_traces_overlapped" + f"_S{register_index}.png")
        # plt.show()
