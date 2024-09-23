"""
Quindi qui dentro definisco l'attacco sulla singola sbox
Poi devo fare i file per l'attacco, quindi dove definisco il 
key scheduling inverso, il leakage model etc...
Quelli per il setup del picoscope e il cw305
Per i risultati riferirsi alla cartella di build del progetto
Infine devo automatizzare il tutto con il makefile 
1. Inizializzo picoscope
2. Inizializzo target e flasho il bitstream
3. Performo cattura
4. Attacco
5. Salvo i risultati (grahfici inclusi)
"""


import numpy as np
import matplotlib.pyplot as plt
import ipywidgets as widgets
import serial
import time
from picoscope import ps5000a
import picosdk
from picosdk.discover import find_all_units
import serial.tools.list_ports as port_list
import chipwhisperer as cw
import sys
sys.path.append( '../AES_python' )

# Check if the Picoscope is connected
scopes = find_all_units()
for scope in scopes:
    print("Working with:")
    print(scope.info)
    scope.close()
ports = list(port_list.comports())
for p in ports:
    print (p)

ps = ps5000a.PS5000a()
print("Found the following picoscope:")
print(ps.getAllUnitInfo())

# Since target runnning at 10 MHz and AES requires from trigger
obs_duration = 3.225E-6
# Sample at least 1260 points within that window
sampling_interval = obs_duration / 1260
# Configure timebase
(actualSamplingInterval, nSamples, maxSamples) = ps.setSamplingInterval(sampling_interval, obs_duration)
print("Nsamples : ", nSamples)
print("Sampling interval = %f us" % (actualSamplingInterval*nSamples*1E6))

# 50mV range on channel A, AC coupled, 20 MHz BW limit
ps.setChannel('A', 'AC', 0.05, 0.0, enabled=True, BWLimited=True)
# Channel B is trigger
ps.setChannel('B', 'DC', 10.0, 0.0, enabled=True)
ps.setSimpleTrigger('B', 2.0, 'Rising', timeout_ms=2000, enabled=True)

#fpga_id = '100t'
## Programming the target with default AES bitstream
#target = cw.target(None, cw.targets.CW305, fpga_id=fpga_id, force = True)

bitstream = r"/home/sca.user/Desktop/AES_sca_resilient/hw/fpga/bitstream/cw305_top_freyre_2.bit"
#bitstream = r"../../hw/fpga/bitstream/cw305_top_rijandael.bit"

target = cw.target(scope, cw.targets.CW305, bsfile=bitstream, force=True)

print("Target programmed :", target.is_programmed())

target.vccint_set(1.0)
target.pll.pll_enable_set(True)             # enable PLL chip
target.pll.pll_outenable_set(False, 0)      # disable PLL 0
target.pll.pll_outenable_set(True, 1)       # enable PLL 1
target.pll.pll_outenable_set(False, 2)      # disable PLL 2
target.pll.pll_outfreq_set(10E6, 1)         # PLL1 frequency set to 10 MHz
# 1 ms is plenty idling time --> maybe not useful with picoscope (?) 
target.clksleeptime = 1 


from tqdm.notebook import tnrange
from Crypto.Cipher import AES
from chipwhisperer.common.traces import Trace
from AES_golden import AES_golden_model

project_file = "../../build/sca_test/sca_test_CW305.cwp"
project = cw.create_project(project_file, overwrite=True)

# Initialize emulated cipher to verify DUT results
ktp = cw.ktp.Basic()
key, text = ktp.next()
cipher = AES.new(bytes(key), AES.MODE_ECB)
print("Key: ", [ hex(subkey) for subkey in key])

N = 2000       # Number of traces
traces = []
textin = []
keys = []
data_mV = []

target.fpga_write(target.REG_CRYPT_KEY, key[::-1])

# Dummy capture call due to bug of using AC coupling
pico_capture()

for i in tnrange(N, desc='Capturing traces'):
    
    # Write plaintext to target
    inputtext = text[::-1]
    target.fpga_write(target.REG_CRYPT_TEXTIN, inputtext)

    # Capture the trace 
    data = pico_capture()
    traces.append(np.array(data))
    data_mV.append(np.array(data)*1E3)

    # Organize and store data
    response = target.fpga_read(target.REG_CRYPT_CIPHEROUT, 16)
    response = response[::-1]
    trace_i = Trace(np.array(data), text, response, key)
    project.traces.append(trace_i)
    
    # Sanity check with expected ciphertext
    #print("Response fpga: ",[ hex(el) for el in response])
    #print("Expected instead: ", [hex(el) for el in cipher.encrypt(bytes(text))])
    #assert (list(response) == list(cipher.encrypt(bytes(text)))), "Incorrect encryption result!\nGot {}\nExp {}\n".format(list(response), list(text))
    
    key, text = ktp.next() 
    textin.append(text)
    keys.append(key)

project.save()
project.close()
target.dis()

print("Crypto model cp: ", [hex(el) for el in cipher.encrypt(bytes(plaintext))])


## AES gpòden model 

ciphertext_golden = cipher_golden.encrypt(formatted_key, plaintext, "sbox_rijandael")
# convert integer to hex 
ciphertext_golden = [hex(i) for i in ciphertext_golden]
# remove '0x' prefix
ciphertext_golden = [s.replace('0x', '') for s in ciphertext_golden]
# pad with zero on the left ig necessary
ciphertext_golden = [s.zfill(2) for s in ciphertext_golden]
# concatenate all elements into a single string
ciphertext_golden = ''.join(ciphertext_golden)
print("Golden model cp: ", ciphertext_golden)

#print("Golden model cp: ", [hex(el) for el in ciphertext_golden])