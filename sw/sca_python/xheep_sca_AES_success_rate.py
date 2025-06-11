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
from AES import AES as AESpy
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

# An already generated bitstream is available in the repository at the path:
bitstream = r"../../hw/fpga/bitstream/xheep/cw305_top.bit"

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
    project_file = "../../build/xheep_test/CW305_xheep_AES_SR_"+sbox_id+"_masked.cwp"
else:
    firmware = r"../x-heep/AES_Sbox_firmware_random_plaintext/main_"+sbox_id+".hex"
    project_file = "../../build/xheep_test/CW305_xheep_AES_SR_"+sbox_id+".cwp"

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



# Number of iterations
max_iterations = 1
# Number of traces to capture
N = 5000

# Initialize key and plain text.
key  = [ 0x2b, 0x7e, 0x15, 0x16, 0x28, 0xae, 0xd2, 0xa6, 0xab, 0xf7, 0x15, 0x88, 0x09, 0xcf, 0x4f, 0x3c ]
text = [ 0x6e, 0xc1, 0x53, 0x9c, 0xfb, 0xe7, 0xf6, 0x18, 0x92, 0xac, 0x19, 0x87, 0xf5, 0x94, 0xe1, 0x2b ]

# Each element of the key is converted to a 2-digit hex string 
formatted_key = ''.join(format(el, '02x') for el in key)
print("Key: ", [ hex(subkey) for subkey in key])

# Initialize the AES software emulated cipher
cipher = AES_golden_model()


# Trace acquisition
if trace_acquisition:
    # Prepare the board
    ps, cw305 = prepare_board(firmware)

    print("Picoscope initialized: \n")
    print(ps.get_scopeSettings())
    print()
    print("Sampling Interval: ", ps.get_samplingInterval(), "s")
    print()

    for iteration in range(1,max_iterations+1):
        print("Iteration: ", iteration)
        project_file = "../../build/xheep_test/xheep_CW305_AES_success_rate_" + sbox_id + "_iteration_" + str(iteration) + ".cwp"
        project = cw.create_project(project_file, overwrite=True)

        # TODO: solve this bug. Apparently the sbox_rijandael is called sbox_aes somewhere.
        if tested_sbox == "sbox_rijandael":
            tested_sbox = "sbox_aes"

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



# TODO: fix this bug.
if tested_sbox == "sbox_aes":
    tested_sbox = "sbox_rijandael"



# Functions to display the results in a Jupyter Notebook
def format_stat(stat):
    return str("{:02X}<br>{:.3f}".format(stat[0], stat[2]))

def color_corr_key(row):
    global key
    ret = [""] * 16
    for i,bnum in enumerate(row):
        if bnum[0] == key[i]:
            ret[i] = "color: red"
        else:
            ret[i] = ""
    return ret
    
# This function is used to check if the recovered key matches the initial key.
# To speed up the attack, if the recovered key matches the initial key for 10 
# consecutive iterations, the attack stops, since the result will be the same
# even analyzing more and more traces.
def check_success(bestguess):
    global successCount
    recv_key = AESpy.get_initial_key(bestguess, 0, sbox_id)
    if initial_key == recv_key:
        successCount +=1
        if successCount >= 10:
            return 1
        else:
            return 0
    else:
        successCount = 0
        return 0
    
class StopExecutionException(Exception):
    pass

# This function is used to display the statistics of the attack
def stats_callback():
    global current_trace_iteration
    global result_success
    global partialGuessingEntropy
    
    results = attack.results
    results.set_known_key(key)
    
    # Success rate calculation
    bestguess = [kguess[0][0] for kguess in results.find_maximums()]
    results_success[current_trace_iteration] = check_success(bestguess)
    if results_success[current_trace_iteration] == 1:
        raise StopExecutionException("Reached Limit")
    
    stat_data = results.find_maximums()
    df = pd.DataFrame(stat_data).transpose()
    # clear_output(wait=True)
    tstart = current_trace_iteration * resolution
    tend = tstart + resolution
    current_trace_iteration += 1
    # display(df.head().style.format(format_stat).apply(color_corr_key,axis=1).set_caption("Iteration {}. Trial {}. Finished traces {} to {}. Success {}".format(iteration, trial, tstart, tend, successCount)))


print("Analyzing traces (this might take a while)...")

global current_trace_iteration
global result_success
global successCount

resolution = 25
max_n_traces = 5000
n_trials = 1
max_n_iteration = 1

for iteration in range(1,max_n_iteration+1):

    project_file = "../../build/xheep_test/xheep_CW305_AES_success_rate_" + sbox_id + "_iteration_" + str(iteration) + ".cwp"
    project = cw.open_project(project_file)

    traces = project.waves[:]
    textin = project.textins[:]
    keys = project.keys[:]
    ciphertext = project.textouts[:]

    # DEBUG
    print("Number of traces: ", len(traces))

    for trial in range(0,n_trials):

        success_file = "../../build/xheep_test/xheep_CW305_AES_success_rate_.cwp"
        success_project = cw.create_project(success_file, overwrite=True)

        for n_trace in range(max_n_traces):
            traces_trial = traces[trial*max_n_traces+n_trace]
            textin_trial = textin[trial*max_n_traces+n_trace]
            ciphertext_trial = ciphertext[trial*max_n_traces+n_trace]
            keys_trial = keys[trial*max_n_traces+n_trace]
            trace_i = Trace(traces_trial, textin_trial, ciphertext_trial, keys_trial)
            success_project.traces.append(trace_i)

        # DEBUG
        print(f"Trial {trial}: using traces {trial*max_n_traces} to {(trial+1)*max_n_traces-1}")

        success_project.save()

        successCount = 0
        current_trace_iteration = 0
        results_success = [1] * int(200)

        initial_key = list(success_project.keys[0])

        inpkey = success_project.keys[0]
        input_key = ""
        for subkey in inpkey:
            input_key = input_key + format(subkey, "02x")
        # round_10_key = AESpy.get_round_key(input_key, 10, sbox_type)

        leak_model = AES128SboxResistantLeakageModels().FirstRound_ModifiedSbox_Output(tested_sbox)
        attack = cwa.cpa(success_project, leak_model)
        try:
            results = attack.run(stats_callback, resolution)
        except StopExecutionException as e:
            print(f"Execution stopped: {e}")

        success_project.close()

        # Success Rate saving
        
        success_file_name = "../x-heep/results/AES_cpa_success_rate_" + sbox_id + "_success_results_trial_" + str(trial+10*(iteration-1)) + ".txt"
        with open(success_file_name,'w') as success_file:
            for success in results_success:
                print(success, file=success_file)


success_rate = [0] * int(max_n_traces/resolution)

# n_trials = 100

def mean(X):
    return np.sum(X, axis=0)/len(X)

trials_success_results_temp = []
for i in range(n_trials):
    success_file_name = "../x-heep/results/AES_cpa_success_rate_" + sbox_id + "_success_results_trial_" + str(i) + ".txt"
    with open(success_file_name, 'r') as file_read:
        data = [int(line.strip()) for line in file_read]
        trials_success_results_temp.append(data)

trials_success_results = list(zip(*trials_success_results_temp))

for i in range(int(max_n_traces/resolution)):
    success_rate[i] = mean(trials_success_results[i])



# Normal plot with matplotlib
print("Generating success rate plot...")

xrange = range(len(success_rate))
plt.figure(figsize=(10, 5))
plt.plot(xrange, success_rate, color="red")
plt.xlabel("Trace Window")
plt.ylabel("Success Rate")
plt.title("AES CPA Success Rate")
plt.grid(True)
#plt.savefig("../x-heep/Graphs/AES_c/AES_cpa_success_rate_" + sbox_id + ".png", dpi=300)
plt.show()
