"""
Copyright 2024 Politecnico di Torino.
Copyright and related rights are licensed under the Solderpad Hardware
License, Version 2.0 (the "License"); you may not use this file except in
compliance with the License. You may obtain a copy of the License at
http://solderpad.org/licenses/SHL-2.0. Unless required by applicable law
or agreed to in writing, software, hardware and materials distributed under
this License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
CONDITIONS OF ANY KIND, either express or implied. See the License for the
specific language governing permissions and limitations under the License.

File: 
Author: Mattia Mirigaldi
Date: 30/07/2024

@brief   CW305 wrapper class to use with picoscope digital oscilloscope
"""

import chipwhisperer as cw
from chipwhisperer.common.traces import Trace
import numpy as np
import time

class CW305Wrapper:
    """Class to manage the Chipwhisperer CW305 board.
    
    #. Attach the board to the computer

    #. Program the board using::
            
            from CW305_api import CW305Wrapper

            CW305 = CW305Wrapper(scope, bitstream="\path\to\bitstream\file")
    
    #. Write encryption key to the CW305
            
            CW305.set_key(key)
        
    #. Capture a trace using::
            
            data = CW305.capture_trace(pt, project_file)
    
    #. Disconnect the board using::
            
            CW305.dis()
    
    """

    def __init__(self, scope, bitstream=None, force=True):
        self.scope = scope
        if bitstream is None:
            # Programming the target with default AES128_8bit bitstream
            self.CW305 = cw.target(None, cw.targets.CW305, fpga_id='100t', force = force)
        else:
            self.CW305 = cw.target(scope, cw.targets.CW305, bsfile=bitstream, force=force)
            print(self.CW305.fpga.isFPGAProgrammed())
        
        if not self.check_target():
            raise Exception("CW305 not programmed.")
        else:
            self.CW305.vccint_set(1.0)
            self.CW305.pll.pll_enable_set(True)             # enable PLL chip
            self.CW305.pll.pll_outenable_set(False, 0)      # disable PLL 0
            self.CW305.pll.pll_outenable_set(True, 1)       # enable PLL 1
            self.CW305.pll.pll_outenable_set(False, 2)      # disable PLL 2
            self.CW305.pll.pll_outfreq_set(10E6, 1)         # PLL1 frequency set to 10 MHz
            # Disable usb_clock. Optional, but reduces power trace noise
            self.CW305.clkusbautooff = True
            # 1 ms is plenty idling time 
            self.CW305.clksleeptime = 1 
        pass


    def check_target(self):
        if not self.CW305.fpga.isFPGAProgrammed():
            print("Error : CW305 not programmed.")
            return False
        else:
            return True

    def set_frequency(self, freq):
        """
        freq (int): The desired output frequency of the PLL. Must be in range [630kHz, 167MHz]
        """
        self.CW305.pll.pll_outfreq_set(freq, 1)
    
    def set_vccint(self, vccint):
        """
        vccint (float): The desired VCCINT voltage. Must be in range [0.85, 1.15]
        """
        self.CW305.vccint_set(vccint)
    
    def set_key(self, key):
        """
        key (bytes): The key to use for encryption

        Note: The key is reversed before being written to the target
        """
        self.key = key
        self.CW305.fpga_write(self.CW305.REG_CRYPT_KEY, key[::-1])

    def set_nonce(self, nonce):
        """
        key (bytes): The key to use for encryption

        Note: The key is reversed before being written to the target
        """
        self.nonce = nonce
        self.CW305.fpga_write(0x0d, nonce[::-1])
        
    def write_fpga(self, add, data):
        """
        key (bytes): The key to use for encryption

        Note: The key is reversed before being written to the target
        """
        self.data = data
        self.CW305.fpga_write(add, data[::-1])
        
    def read_fpga(self, add, len):
        """
        key (bytes): The key to use for encryption

        Note: The key is reversed before being written to the target
        """
        data = self.CW305.fpga_read(add, len)
        
        return data[::-1]
    
    def capture_trace(self, pt, project_file, wait_time=0.05, dummy=False):
        """
        pt (bytes): The plaintext to encrypt
        key (bytes): The key to use for encryption
        project_file (str): The path to the project file to save the traces
        """
        # Write plaintext to target. Endianess is reversed
        self.CW305.fpga_write(self.CW305.REG_CRYPT_TEXTIN, pt[::-1])
        # Run the target        
        self.scope.runBlock()
        time.sleep(wait_time)
        self.CW305.fpga_write(self.CW305.REG_USER_LED, [0x01])
        self.CW305.usb_trigger_toggle()
        self.scope.waitReady()
        # Get captured trace 
        data = self.scope.getDataV()
        # Store captured data in project file
        response = self.CW305.fpga_read(self.CW305.REG_CRYPT_CIPHEROUT, 16)
        response = response[::-1]
        trace = Trace(np.array(data), pt, response, self.key)
        if not dummy:
            project_file.traces.append(trace)
        
        return response
    
    def capture_trace_1_round(self, project_file, pt, wait_time=0.05, dummy=False):
        """
        project_file (str): The path to the project file to save the traces
        """
        # Write nonce to target. Endianess is reversed
        self.set_nonce(pt)
        # Run the target        
        self.scope.runBlock()
        time.sleep(wait_time)
        self.CW305.fpga_write(self.CW305.REG_USER_LED, [0x01])
        self.CW305.usb_trigger_toggle()
        self.scope.waitReady()
        # Get captured trace 
        data = self.scope.getDataV()
        # Store captured data in project file
        response = self.CW305.fpga_read(0x0e, 40)
        response = response[::-1]
        trace = Trace(np.array(data), self.nonce, 0x0, self.key)
        if not dummy:
            project_file.traces.append(trace)
        
        return response
    
    def TVLA_capture_trace(self, project_file, key, nonce, wait_time=0.05):
        """
        project_file (str): The path to the project file to save the traces
        """

        #Write key to target
        self.set_key(key)
        # Write nonce to target. Endianess is reversed
        self.set_nonce(nonce)

        # Run the target        
        self.scope.runBlock()
        time.sleep(wait_time)
        self.CW305.fpga_write(self.CW305.REG_USER_LED, [0x01])
        self.CW305.usb_trigger_toggle()
        self.scope.waitReady()

        # Get captured trace 
        data = self.scope.getDataV()
        # Store captured data in project file
        response = self.CW305.fpga_read(0x0e, 40)
        response = response[::-1]
        trace = Trace(np.array(data), self.nonce, 0x0, self.key)
        project_file.traces.append(trace)
        
        return response

    def dis(self):
        self.CW305.dis()