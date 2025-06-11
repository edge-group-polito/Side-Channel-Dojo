#!/usr/bin/env python3


import sys
sys.path.append( '../AES_python' )
sys.path.append( '../sca_python' )
sys.path.append( '../x-heep' )
import readFirmware
import os
os.system("pip list | grep chipwhisperer")

from pico_api import PS5000aWrapper
import chipwhisperer as cw
import chipwhisperer.analyzer as cwa
from chipwhisperer.common.traces import Trace
from AES_golden import AES_golden_model
import time

from tqdm import tqdm
from analyzer.attack.aes.SBox_leakage_models import AES128SboxResistantLeakageModels
from analyzer.attack.aes.key_schedule import key_schedule_rounds
from analyzer.utils.sca_plots import sca_plot

import holoviews as hv
hv.extension('bokeh')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd



###################### INITIALIZATION ######################


trace_acquisition = True
traces_overlapped_plot = True
traces_snr_plot = True
traces_pge_plot = True
traces_correlation_plot = True

# An already generated bitstream is available in the repository at the path:
bitstream = r"../../hw/fpga/bitstream/xheep/cw305_top.bit"
# Alternatively, you can generate the bitstream yourself by running the following command:
#   make vivado-fpga
# and the generated bitstream will be available at the path:
#bitstream = r"../../hw/vendor/cw305-heep/build/polito_cw305_heep_cw305_heep_0.0.1/cw305-vivado/polito_cw305_heep_cw305_heep_0.0.1.runs/impl_1/cw305_top.bit"
# Note that this folder is temporary and will be deleted when you run the 'make clean' command.

verilog_defines = r"../../hw/vendor/cw305-heep/hw/fpga/cw305_aes_defines.v"

"""
Available S-boxes:
    sbox_rijandael (default AES S-Box) (aes_sbox)
    sbox_freyre_1
    sbox_freyre_2
    sbox_freyre_3
    sbox_hussain_6
    sbox_ozkaynak_1
    sbox_azam_1
    sbox_azam_2
    sbox_azam_3
"""
tested_sbox = "sbox_rijandael"
sbox_id = tested_sbox.replace("sbox_", "")

masked_flag = False

# The firmware is already compiled and available in the repository for all S-boxes
# for the not masked case.

#TODO: remove the project file and use just the traces
if masked_flag:
    firmware = r"../x-heep/AES_masked_firmware_random_plaintext/main_"+sbox_id+".hex"
    project_file = "../../build/xheep_test/CW305_xheep_AES_"+sbox_id+"_masked.cwp"
else:
    firmware = r"../x-heep/AES_Sbox_firmware_random_plaintext/main_"+sbox_id+".hex"
    project_file = "../../build/xheep_test/CW305_xheep_AES_"+sbox_id+".cwp"

# To run a generic firmware compiled with the X-HEEP toolchain and structure,
# you can use the following path:
#firmware = r"../../hw/vendor/cw305-heep/sw/build/main.hex"

print()
print("bitstream: ", bitstream)
print("firmware: ", firmware)
print("verilog_defines: ", verilog_defines)
print("project_file: ", project_file)
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
        #ps.scope_setup(obs_time=1E-3, nSamples=400000) # 1ms time window, 400k samples which results in 2 ns sampling interval. Much higher than the 10 MHz clock frequency for X-HEEP.
        ps.scope_setup(obs_time=1E-4, nSamples=4000) # 0.1ms time window, 4k samples which results in ~25 ns sampling interval.


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



###################### ONLINE PHASE ######################


# Initialize key and plain text.
key  = [ 0x2b, 0x7e, 0x15, 0x16, 0x28, 0xae, 0xd2, 0xa6, 0xab, 0xf7, 0x15, 0x88, 0x09, 0xcf, 0x4f, 0x3c ]
text = [ 0x6e, 0xc1, 0x53, 0x9c, 0xfb, 0xe7, 0xf6, 0x18, 0x92, 0xac, 0x19, 0x87, 0xf5, 0x94, 0xe1, 0x2b ]

# Each element of the key is converted to a 2-digit hex string 
formatted_key = ''.join(format(el, '02x') for el in key)
print("Key: ", [ hex(subkey) for subkey in key])

# Initialize the AES software emulated cipher
cipher = AES_golden_model()

# Number of traces to capture
N = 5000

# TODO: solve this bug. Apparently the sbox_rijandael is called sbox_aes somewhere.
if tested_sbox == "sbox_rijandael":
    tested_sbox = "sbox_aes"


# Prepare the board
ps, cw305 = prepare_board(firmware)

print("Picoscope initialized: \n")
print(ps.get_scopeSettings())
print()
print("Sampling Interval: ", ps.get_samplingInterval(), "s")
print()

if trace_acquisition:
    project = cw.create_project(project_file, overwrite=True)

    # Trigger the iteration start in the firmware
    cw305.fpga_write(cw305.REG_BRIDGE_STATUS, data=bytearray([0x08]))
    time.sleep(1E-3) # 1 ms
    cw305.fpga_write(cw305.REG_BRIDGE_STATUS, data=bytearray([0x00]))

    for i in tqdm(range(N), desc="Capturing traces"):
        # Run the target
        ps.runBlock()
        time.sleep(0.05)

        # Write 8 to the status register to trigger the program execution and the scope acquisition
        cw305.fpga_write(cw305.REG_BRIDGE_STATUS, data=bytearray([0x08]))

        ps.waitReady()

        # Get captured trace 
        data = ps.getDataV()

        trace = Trace(np.array(data), text, cipher.encrypt(formatted_key, text, tested_sbox), key)
        project.traces.append(trace)
        #print("Cipertext: ", [ hex(subkey) for subkey in cipher.encrypt(formatted_key, text, tested_sbox)])
        
        # Update the plain text as the previous chipertext
        text = cipher.encrypt(formatted_key, text, tested_sbox)

        time.sleep(1E-3) # 1 ms
        # Reset the status register to reload the program execution and the scope acquisition
        cw305.fpga_write(cw305.REG_BRIDGE_STATUS, data=bytearray([0x00]))

    project.save()
    project.close()

# Disconnect CW305 and picoscope
cw305.dis()
ps.dis()



####################### OFFLINE PHASE #######################

# --------- PGE, Correlation callbacks -------------------
def _default_python_callback(attack):
    global current_trace_iteration
    attack_results = attack.results
    key = attack.known_key()

    attack_results.set_known_key(key)
    stat_data = attack_results.find_maximums()
    df = pd.DataFrame(stat_data).transpose()

    # Add PGE row
    df_pge = pd.DataFrame(attack_results.pge).transpose().rename(index={0: "PGE="}, columns=int)
    df = pd.concat([df_pge, df], ignore_index=False)

    reporting_interval = attack.reporting_interval
    tstart = current_trace_iteration * reporting_interval
    tend = tstart + reporting_interval
    current_trace_iteration += 1

def get_python_callback(attack):
    global current_trace_iteration
    current_trace_iteration = 0
    return lambda: _default_python_callback(attack)
# ------------------------------------------------------------



### Power traces overlapped plot ###

# TODO: fix this bug.
if tested_sbox == "sbox_aes":
    tested_sbox = "sbox_rijandael"

project = cw.open_project(project_file)

if traces_overlapped_plot:
    print("Generating power traces overlapped plot...")
    sca_plt = sca_plot()
    power_plt = sca_plt.power_traces_overlapped(ps.get_samplingInterval(), project.waves, finish=len(project.waves[0]))

    # Ensure the Graphs directory exists and save the plot
    if masked_flag:
        os.makedirs("../x-heep/Graphs/AES_c_masked", exist_ok=True)
        power_plt.savefig("../x-heep/Graphs/AES_c_masked/AES_masked_power_traces_overlapped_"+tested_sbox+".png")
    else:
        os.makedirs("../x-heep/Graphs/AES_c", exist_ok=True)
        power_plt.savefig("../x-heep/Graphs/AES_c/AES_power_traces_overlapped_"+tested_sbox+".png")

    # power_plt.show()
    power_plt.close()



### SNR plot ###

if traces_snr_plot:
    print("Generating SNR plot...")

    # First round sbox output snr calculation
    leak_model = AES128SboxResistantLeakageModels().FirstRound_ModifiedSbox_Output(tested_sbox)
    snr_fr = cwa.calculate_snr(project.traces, leak_model=leak_model, db=False)

    plt.figure(figsize=(12, 6))  # width, height in inches
    plt.plot(np.arange(len(snr_fr)), snr_fr, color='orange', alpha=0.5)
    plt.xlabel('Sample')
    plt.ylabel('SNR')
    plt.title('SNR in time')
    plt.grid(True)

    # Save the plot
    if masked_flag:
        os.makedirs("../x-heep/Graphs/AES_c_masked", exist_ok=True)
        plt.savefig("../x-heep/Graphs/AES_c_masked/AES_masked_SNR_"+tested_sbox+".png")
    else:
        os.makedirs("../x-heep/Graphs/AES_c", exist_ok=True)
        plt.savefig("../x-heep/Graphs/AES_c/AES_SNR_"+tested_sbox+".png")

    # plt.show()
    plt.close()



### CPA attack ###

print("Running CPA attack (this might take a while)...")
leak_model = AES128SboxResistantLeakageModels().FirstRound_ModifiedSbox_Output(tested_sbox)
attack = cwa.cpa(project, leak_model)
#results = attack.run()
results = attack.run(get_python_callback(attack))
print("CPA attack finished. Results:")
print(results)

# Recover key
recv_firstroundkey = [kguess[0][0] for kguess in results.find_maximums()]
recv_key = key_schedule_rounds(recv_firstroundkey, 0, 0, tested_sbox)
print("Recovered key: ", [hex(subkey) for subkey in recv_key])
key=list(project.keys[0])
assert (key == recv_key), "Failed to recover encryption key!\nGot {}\nExp {}\n".format(recv_key, key)
print("Key recovery : Success!")



### PGE vs Traces plot ###

def byte_to_color(idx):
    return hv.Palette.colormaps['Category20'](idx/16.0)


if traces_pge_plot:
    print("Generating PGE vs Traces plot...")
    """
    Plots the PGE trends for all the 16 correct key guesses with matplotlib
    """

    plot_data = cwa.analyzer_plots(results)
    pges = [plot_data.pge_vs_trace(i) for i,_ in enumerate(key)]
    fig, ax1 = plt.subplots(nrows=1, ncols=1, sharex=True, figsize=[14,10])
    plt.grid(which='major', axis='both', alpha=0.2)

    x_axis = plot_data.pge_vs_trace(0)[0]
    #step = 10
    step = 500
    for i, bnum in enumerate(key):
        plt.plot(pges[i][0], pges[i][1], linewidth=1, label=f"Byte #{i}")
    plt.plot(pges[i][0], [10 for _ in range(len(pges[i][0]))], linewidth=1, linestyle="dashed",  color="black", label=f"max(PGE) < {10}")
        
    plt.legend(title=f"Known Key", fontsize=12, loc="upper right")
    plt.title(" AES S-Box " + sbox_id + " - PGE", fontsize=18)
    ax1.set_xticks(range(0, x_axis[-1], step))
    # clip_min_y = 0
    # clip_max_y = 300
    # ax1.set_yticks(list(range(clip_min_y, clip_max_y+1, 10)))
    ax1.set_ylabel('Partial Guessing Entropy (PGE)', fontsize=16)
    ax1.set_xlabel('Traces', fontsize=16)
    #ax1.set_ylim(0, 300)
    ax1.set_xlim(0, 5000)

    # Save the plot
    if masked_flag:
        os.makedirs("../x-heep/Graphs/AES_c_masked", exist_ok=True)
        plt.savefig("../x-heep/Graphs/AES_c_masked/AES_masked_PGE_"+tested_sbox+".png")
    else:
        os.makedirs("../x-heep/Graphs/AES_c", exist_ok=True)
        plt.savefig("../x-heep/Graphs/AES_c/AES_PGE_"+tested_sbox+".png")

    # plt.show()
    plt.close(fig)



### Correlation plot ###

if traces_correlation_plot:
    print("Generating Correlation plot...")
    """
    Plots the various correlations of both the correct key guesses and the wrong ones
    """
    # 16 subkeyCW305_leakage_model
    bnum_it = range(16)

    plot_data = cwa.analyzer_plots(results)
    fig, ax1 = plt.subplots(nrows=1, ncols=1, sharex=True, figsize=[18,12])
    plt.grid(which='major', axis='both', alpha=0.2)

    # Plot correlation trends of wrong key guesses (
    for bnum in bnum_it:
        data = np.array(plot_data.corr_vs_trace(bnum)[1])
        xrangelist = plot_data.corr_vs_trace(bnum)[0]
        wrong_results = data[[i != key for i in range(256)]]
        ax1.plot(xrangelist, np.amax(wrong_results, 0), linewidth=2, linestyle ="dotted", color=byte_to_color(bnum))

    # Plot correct key_guesses on top of wrong ones
    for bnum in bnum_it:
        data = np.array(plot_data.corr_vs_trace(bnum)[1])
        xrangelist = plot_data.corr_vs_trace(bnum)[0]
        key = results.known_key[bnum]
        wrong_results = data[[i != key for i in range(256)]]
        ax1.plot(xrangelist, data[key], linewidth=1, label=f"Byte #{bnum}", color=byte_to_color(bnum))


    ax1.legend(title=f"Known Key", fontsize=12, loc="upper right")
    plt.title(" AES S-Box " + sbox_id + " - Correlations", fontsize=18)

    step = 200
    ax1.set_xticks(range(0, xrangelist[-1], step))
    ax1.set_ylabel('Correlation', fontsize=16)
    ax1.set_xlabel('Traces', fontsize=16)

    # Save the plot
    if masked_flag:
        os.makedirs("../x-heep/Graphs/AES_c_masked", exist_ok=True)
        plt.savefig("../x-heep/Graphs/AES_c_masked/AES_masked_correlations_"+tested_sbox+".png")
    else:
        os.makedirs("../x-heep/Graphs/AES_c", exist_ok=True)
        plt.savefig("../x-heep/Graphs/AES_c/AES_correlations_"+tested_sbox+".png")

    # plt.show()
    plt.close(fig)

project.close()
