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

import matplotlib.pyplot as plt
import numpy as np

# Added for multiprocessing support
from multiprocessing import Pool

###################### INITIALIZATION ######################



trace_acquisition = False

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

# To run another firware compiled with the X-HEEP toolchain, use the following line:
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

print("Analyzing traces (this might take a while)...")

# To calculate the success rate, an incremental number of traces is used.
# The idea is that the total number of traces is first divided into N groups (e.g first only 500 traces,
# then 1000 traces, then 1500 traces and so on), then a CPA attack is performed
# on each group of traces and the success rate is calculated on each key byte (i.e. SR[key_byte] = 1
# if guessed_key_byte == correct_key_byte, otherwise SR[key_byte] = 0).
# Then, the success rate of the whole attack is calculated as the average of the success rates of each key byte,
# i.e. SR = (SR[0] + SR[1] + ... + SR[15]) / 16 (16 since for AES128 the key size is 128 bit or 16 bytes).
# The ChipWhisperer Analyzer is used to perform the CPA attack on the traces. It returns the list of the guessed
# key bytes and it supports the use of a callback function to get the statistics of the attack, which is used 
# to calculate the success rate. The callback function "resolution" parameter is used to define how often
# the statistics are updated (e.g. every 25 traces), so it basically works also as traces slicer.
# Each time the callback function is called, the guessed key bytes are compared with the correct key bytes
# and the success rate is updated. The final success rate is then plotted using matplotlib.

# Performance metrics
tic = time.perf_counter()

# Initialize the success rate list
success_rate = []

# The resolution defines how many traces are added each time to evaluate the n-success_rate.
resolution = 25

def success_rate_callback():
    global success_rate
    global key

    # Get the attack results (guessed key bytes).
    # The "find_maximums" method returns 3 nested lists:
    # 1. The first list contains the guessed key bytes ordered by subkey index
    #    [subkey0_data, subkey1_data, subkey2_data, ...]
    # 2. subkey0_data is another list containing guesses ordered by strength of correlation:
    #    [guess0, guess1, guess2, ...]
    # 3. guess0 is a tuple containing:
    #    (key_guess, location_of_max, correlation)
    # So, with the syntax kguess[0][0], we get the best key guess for each subkey.
    results = attack.results
    guessed_key = [kguess[0][0] for kguess in results.find_maximums()]
    
    iteration_success_rate = []
    # Compare the guessed key bytes with the correct key bytes
    for key_byte, guessed_key_byte in zip(key, guessed_key):
        # If the guessed key byte matches the correct key byte, i-th success_rate is 1, otherwise 0
        success_rate_i = 1 if key_byte == guessed_key_byte else 0
        iteration_success_rate.append(success_rate_i)

    # Calculate the average success rate for the current iteration
    avg_success_rate = sum(iteration_success_rate) / len(iteration_success_rate)
    # Append the average success rate to the success_rate list
    success_rate.append(avg_success_rate)


# Attack loop
for iteration in range(1,max_iterations+1):
    project_file = "../../build/xheep_test/xheep_CW305_AES_success_rate_" + sbox_id + "_iteration_" + str(iteration) + ".cwp"
    project = cw.open_project(project_file)

    # The Hamming Weight is used as the leakage model for the CPA attack.
    leak_model = AES128SboxResistantLeakageModels().FirstRound_ModifiedSbox_Output(tested_sbox)
    attack = cwa.cpa(project, leak_model)
    
    # Perform the CPA attack
    attack.run(success_rate_callback, resolution)

    project.close()


# Normal plot with matplotlib
print("Generating success rate plot...")

# On the x-axis, the number of traces is represented, which is the length of the success_rate list,
# also equal to the total number of traces divided by the resolution.
# The y-axis represents the success rate for each trial.
xrange = [i * resolution for i in range(len(success_rate))]
# xrange = range(len(success_rate))
plt.figure(figsize=(10, 5))
plt.plot(xrange, success_rate, color="red")
plt.xlabel("Number of traces") #TODO: convert to actual number of traces
plt.ylabel("Success Rate")
plt.title("AES CPA Success Rate")
plt.grid(True)
plt.savefig("../x-heep/Graphs/AES_c/AES_cpa_success_rate_" + sbox_id + ".png", dpi=300)
# plt.show()


toc = time.perf_counter()
print(f"[LOG] OFFLINE PHASE: Computation completed in {(toc - tic)/60:0.2f} minutes.")
