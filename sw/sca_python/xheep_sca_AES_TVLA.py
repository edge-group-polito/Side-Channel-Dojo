#!/usr/bin/env python3

import sys
sys.path.append( '../AES_python' )
sys.path.append( '../sca_python' )
sys.path.append( '../x-heep' )
import readFirmware

import chipwhisperer as cw
from chipwhisperer.common.traces import Trace
from AES_golden import AES_golden_model
import time
from pico_api import PS5000aWrapper

from tqdm import tqdm
import numpy as np
import scipy.stats as stats
import matplotlib.pyplot as plt

import os
os.system("pip list | grep chipwhisperer")

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
        print()
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

###################### INITIALIZATION ######################

trace_acquisition = True

# An already generated bitstream is available in the repository at the path:
bitstream = r"../../hw/fpga/bitstream/xheep/cw305_top.bit"

verilog_defines = r"../../hw/vendor/cw305-heep/hw/fpga/cw305_aes_defines.v"

# NOTE: for the moment only the default AES S-Box is available.
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

# To perform also TVLA tests, traces have to be collected twice. So two different
# firmware have to be loaded. The first one is with random plaintext and the second one 
# is with fixed plaintext. The key is always fixed for both cases.
# The firmware is already compiled and available in the repository for all S-boxes.

masked_flag = False

#TODO: remove the project file and use just the traces
if masked_flag:
    firmware_fixed_pt       = r"../x-heep/AES_masked_firmware_fixed_plaintext/main_"+sbox_id+".hex"
    firmware_random_pt      = r"../x-heep/AES_masked_firmware_random_plaintext/main_"+sbox_id+".hex"
    project_file_fixed_pt   = "../../build/xheep_test/CW305_xheep_AES_TVLA_"+sbox_id+"_masked_fixed_pt.cwp"
    project_file_random_pt  = "../../build/xheep_test/CW305_xheep_AES_TVLA_"+sbox_id+"_masked_random_pt.cwp"
else:
    firmware_fixed_pt       = r"../x-heep/AES_Sbox_firmware_fixed_plaintext/main_"+sbox_id+".hex"
    firmware_random_pt      = r"../x-heep/AES_Sbox_firmware_random_plaintext/main_"+sbox_id+".hex"
    project_file_fixed_pt   = "../../build/xheep_test/CW305_xheep_AES_TVLA_"+sbox_id+"_fixed_pt.cwp"
    project_file_random_pt  = "../../build/xheep_test/CW305_xheep_AES_TVLA_"+sbox_id+"_random_pt.cwp"


print()
print("bitstream: ", bitstream)
print("verilog_defines: ", verilog_defines)
print("firmware FIXED: ", firmware_fixed_pt)
print("firmware RANDOM: ", firmware_random_pt)
print("project_file FIXED: ", project_file_fixed_pt)
print("project_file RANDOM: ", project_file_random_pt)
print()


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

if trace_acquisition:
    # Create both projects for fixed and random plaintext
    project_fixed   = cw.create_project(project_file_fixed_pt, overwrite=True)
    project_random  = cw.create_project(project_file_random_pt, overwrite=True)

    firmwares   = [firmware_fixed_pt, firmware_random_pt]
    projects    = [project_fixed, project_random]

    # TODO: solve this bug. Apparently the sbox_rijandael is called sbox_aes somewhere.
    if tested_sbox == "sbox_rijandael":
        tested_sbox = "sbox_aes"

    # For each of the 2 firmwares, prepare the board, load the firmware, and capture traces.
    # The results are saved in the corresponding project file.
    for fw, proj in zip(firmwares, projects):
        # Prepare the board
        ps, cw305 = prepare_board(fw)

        print("Picoscope initialized: \n")
        print(ps.get_scopeSettings())
        print()
        print("Sampling Interval: ", ps.get_samplingInterval(), "s")
        print()

        # Trigger the iteration start in the firmware
        cw305.fpga_write(cw305.REG_BRIDGE_STATUS, data=bytearray([0x08]))
        time.sleep(1E-3) # 1 ms
        cw305.fpga_write(cw305.REG_BRIDGE_STATUS, data=bytearray([0x00]))

        #for i in tnrange(N, desc='Capturing traces'):
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
            proj.traces.append(trace)
            #print("Cipertext: ", [ hex(subkey) for subkey in cipher.encrypt(formatted_key, text, tested_sbox)])
            
            if fw == firmware_random_pt:
                # Update the plain text as the previous chipertext
                text = cipher.encrypt(formatted_key, text, tested_sbox)

            time.sleep(1E-3) # 1 ms
            # Reset the status register to reload the program execution and the scope acquisition
            cw305.fpga_write(cw305.REG_BRIDGE_STATUS, data=bytearray([0x00]))

        proj.save()
        proj.close()
        # Disconnect CW305 and picoscope
        cw305.dis()
        ps.dis()


####################### OFFLINE PHASE #######################

print("Generating TVLA t-test results and plot...")

# Open the projects for fixed and random plaintext
project_fixed   = cw.open_project(project_file_fixed_pt)
project_random  = cw.open_project(project_file_random_pt)

# Get the traces from both projects
traces_fixed    = project_fixed.waves[:]
traces_random   = project_random.waves[:]

# Perform the Welch's test
t_stat, p_val = stats.ttest_ind(traces_fixed, traces_random, equal_var=False)

# Static plot using matplotlib
# Assuming t_stat is a numpy array or list
xrange = np.arange(len(t_stat))
threshold_plus = np.full_like(t_stat, 4.5)
threshold_minus = np.full_like(t_stat, -4.5)

plt.figure(figsize=(12, 6))
plt.plot(xrange, t_stat, color="green", label="t-value")
plt.plot(xrange, threshold_plus, color="orange", linestyle="--", label="+4.5 threshold")
plt.plot(xrange, threshold_minus, color="orange", linestyle="--", label="-4.5 threshold")
plt.title("TVLA t-test Results")
plt.xlabel("Sample Index")
plt.ylabel("t-value")
plt.legend()
plt.grid(True)

# Save to PNG
if masked_flag:
    plt.savefig("../x-heep/Graphs/AES_c_masked/tvla_ttest_results_masked.png")
else:
    plt.savefig("../x-heep/Graphs/AES_c/tvla_ttest_results.png")

# plt.show()
plt.close()

project_fixed.close()
project_random.close()
