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

    REG_CLKSETTINGS              = 0x00
    REG_USER_LED                = 0x01
    REG_CRYPT_TYPE              = 0x02
    REG_CRYPT_REV               = 0x03
    REG_IDENTIFY                = 0x04
    REG_CRYPT_GO                = 0x05
    REG_CRYPT_TEXTIN            = 0x06
    REG_CRYPT_CIPHERIN          = 0x07
    REG_CRYPT_TEXTOUT           = 0x08
    REG_CRYPT_CIPHEROUT         = 0x09
    REG_CRYPT_KEY               = 0x0A
    REG_BUILDTIME               = 0x0B
    REG_CRYPT_TAGOUT            = 0x0C
    REG_CRYPT_NONCEIN           = 0x0D
    REG_CRYPT_STATEOUT          = 0x0E
    REG_CONTROL                 = 0x0F
    REG_VALID_BYTES_AD          = 0x10
    REG_VALID_BYTES_MSG         = 0x11  # 1 byte, numero di byte validi in input
    REG_CRYPT_TEXTIN_BUFFER_MSG = 0x12
    REG_CRYPT_STATUS            = 0x13  
    REG_CRYPT_FIFO_DATA         = 0x14 
    REG_CRYPT_FIFO_CNT          = 0x15



    def __init__(self, scope, bitstream=None, force=True, standalone=False):
        self.scope = scope
        self.standalone = standalone
        if bitstream is None:
            # Programming the target with default AES128_8bit bitstream
            self.CW305 = cw.target(None, cw.targets.CW305, fpga_id='100t', force = force)
        else:
            self.CW305 = cw.target(
                scope,
                cw.targets.CW305,
                bsfile=bitstream,
                force=force,
                slurp=not standalone,
            )
            print(self.CW305.fpga.isFPGAProgrammed())

        if standalone:
            # Standalone crypto cores use 7 low USB address bits as byte index.
            # Override the site-package setting so it can remain configured for
            # X-HEEP, which uses bytecount_size=2.
            self.CW305.bytecount_size = 7
        
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
        Set the encryption key on the target.

        Args:
            key (bytes): The key to use for encryption.

        Note: The key is reversed before being written to the target.
        """
        self.key = key
        data = key[::-1] if self.standalone else key
        self.CW305.fpga_write(self.REG_CRYPT_KEY, data)

    def set_nonce(self, nonce):
        """
        Set the nonce on the target.

        Args:
            nonce (bytes): The nonce to use for encryption.

        Note: The nonce is reversed before being written to the target.
        """
        self.nonce = nonce
        data = nonce[::-1] if self.standalone else nonce
        self.CW305.fpga_write(self.REG_CRYPT_NONCEIN, data)

    #funzione aggiuntiva nico:
    def set_initial_data(self, ad, msg):

        ad_rev = ad[::-1]
        msg_rev = msg[::-1]

        self.CW305.fpga_write(self.REG_CRYPT_TEXTIN, ad_rev)
        #print(f"[WRITE] AD = {ad.hex()}")
        self.CW305.fpga_write(self.REG_CRYPT_TEXTIN_BUFFER_MSG, msg_rev)
        #print(f"[WRITE] MSG = {msg.hex()}")

        ad_len = len(ad)
        msg_len = len(msg)

        #print(f"Nota bene: AD e MSG hanno endianess invertito, perchè il core fa il reverse")
        self.CW305.fpga_write(self.REG_VALID_BYTES_AD, bytes([ad_len]))
        #print(f"[WRITE] Valid AD Bytes = {ad_len}")

        self.CW305.fpga_write(self.REG_VALID_BYTES_MSG, bytes([msg_len]))
        #print(f"[WRITE] Valid MSG Bytes = {msg_len}")

        # Readback for verification:
        ad_back = self.CW305.fpga_read(self.REG_CRYPT_TEXTIN, len(ad))
        vbytes_ad = self.CW305.fpga_read(self.REG_VALID_BYTES_AD, 1)
        #print(f"[READBACK] AD: {ad_back.hex()}")
        #print(f"[READBACK] Valid Bytes AD: {vbytes_ad[0]}")

        msg_back = self.CW305.fpga_read(self.REG_CRYPT_TEXTIN_BUFFER_MSG, len(msg))
        vbytes_msg = self.CW305.fpga_read(self.REG_VALID_BYTES_MSG, 1)
        #print(f"[READBACK] MSG: {msg_back.hex()}")
        #print(f"[READBACK] Valid Bytes MSG: {vbytes_msg[0]}")



    def set_control(self, control):
        self.CW305.fpga_write(self.REG_CONTROL, bytes([control]))
        ctrl_readback = self.CW305.fpga_read(self.REG_CONTROL, 1)
        print(f"[READBACK] Control register: {ctrl_readback[0]:#04x}")   

    #funzione di handshake agiunta da nico:
    def wait_until_ready(self):
        already_written = False

        while True:
            status = self.read_fpga(self.REG_CRYPT_STATUS, 1)[0]
            core_read_data = (status >> 1) & 0x01
            if core_read_data:
                break

    #funzione per leggere i risultati nico:
    def read_results(self, timeout_s: float = 1.0, wait_tag: bool = False):
        #print("🔍 Inizio read_results...")

        t0 = time.time()
        i = 0
        while True:
            status = self.read_fpga(self.REG_CRYPT_STATUS, 1)[0]
            done = (status >> 4) & 1
            #print(f"[{i:02}] STATUS={status:08b}")
            if done:
                break
            if time.time() - t0 > timeout_s:
                raise TimeoutError("read_results(): timeout in attesa di done=1")
            time.sleep(5e-4); i += 1

            if done:
                break
            if time.time() - t0 > timeout_s:
                raise TimeoutError("read_results(): timeout in attesa di done=1")
            time.sleep(5e-4)
            i += 1

         # ⚠️ Leggi RAW dai registri (senza usare read_fpga che già inverte)
        ct_le  = bytes(self.CW305.fpga_read(self.REG_CRYPT_CIPHEROUT, 16))
        tag_le = bytes(self.CW305.fpga_read(self.REG_CRYPT_TAGOUT,   16))


        #print(f"🧾 REG_CRYPT_CIPHEROUT: {ct_le.hex()}")
        #print(f"🔏 REG_CRYPT_TAGOUT   : {tag_le.hex()}")

        # niente reverse: read_fpga() ha già gestito l'endianness
        return ct_le, tag_le
        

        
    def write_fpga(self, addr, data):
        """
        Write data to the FPGA at the specified address.

        Args:
            addr (int): The address to write to.
            data (bytes): The data to write.

        Note: The data is reversed before being written to the target.
        """
        self.data = data
        self.CW305.fpga_write(addr, data[::-1]) #no  reverse data[::-1]
        
    def read_fpga(self, addr, length):
        """Side-Channel-Dojo
        Read data from the FPGA at the specified address.

        Args:
            addr (int): The address to read from.
            length (int): The number of bytes to read.

        Returns:
            bytes: The data read from the FPGA, reversed.
        """
        data = self.CW305.fpga_read(addr, length)
        return data[::-1]
    
    #funzione aggiuntiva:
    def capture_ascon_trace_project(self, project_file, wait_time=5e-6, dummy=False, keep_float=True):
        """
        Acquisisce una traccia durante l'inizializzazione di ASCON.

        Args:
            project_file: progetto CW in cui salvare la traccia
            wait_time: piccolo margine prima del trigger (~5us)
            dummy: se True, non salva la traccia
            keep_float: se True, salva la waveform in Volt nei metadata (extras)
            save_i16_extra: se True, salva ANCHE una copia int16 negli extras (scaling locale)

        Returns:
            data_v (np.ndarray float): traccia in Volt, senza alcuno scaling.
        """

        # 1) Arma lo scope
        self.scope.runBlock()
        if wait_time and wait_time > 0:
            time.sleep(wait_time)

        # 2) (opzionale) LED debug
        self.CW305.fpga_write(self.REG_USER_LED, [0x01])

        # 3) Avvia algoritmo (genera trigger HW su CH-B)
        self.CW305.fpga_write(self.REG_CRYPT_GO, [0x01])

        # 4) Attendi fine acquisizione
        self.scope.waitReady()

        # 5) Waveform in Volt (float) — NESSUNO scaling qui
        data_v = np.asarray(self.scope.getDataV(), dtype=float)

        # 6) Crea la Trace CW con i dati REALI (float in Volt)
        fake_ct  = b'\x00' * 16
        fake_key = getattr(self, "key", b'\x00' * 16)
        trace = Trace(data_v, self.nonce, fake_ct, fake_key)

        # 7) Salva nel progetto
        if not dummy:
            project_file.traces.append(trace)

        return data_v

    def capture_ascon_trace(self, wait_time=5e-6):
        """
        Acquires a power trace during ASCON execution without saving to a CW project.

        Args:
            wait_time (float, optional): Small margin before the trigger (~5us). Default is 5e-6.

        Returns:
            trace (np.ndarray): The captured power trace in Volts (float).
        """
        # 1) Arm the scope
        self.scope.runBlock()
        
        if wait_time and wait_time > 0:
            time.sleep(wait_time)

        # 2) (Optional) LED debug toggle
        self.CW305.fpga_write(self.REG_USER_LED, [0x01])

        # 3) Start the ASCON algorithm (Generates HW trigger on CH-B)
        self.CW305.fpga_write(self.REG_CRYPT_GO, [0x01])

        # 4) Wait for the scope to finish acquiring the trace
        self.scope.waitReady()

        # 5) Retrieve the waveform in Volts and convert directly to a float array
        trace = np.asarray(self.scope.getDataV(), dtype=float)

        return trace


    def reset_ascon_core(self):
        self.write_fpga(self.REG_CONTROL, bytes([0xFF]))  # assert resetn_sw
        time.sleep(0.01)
        self.write_fpga(self.REG_CONTROL, bytes([0x00]))  # deassert resetn_sw


    
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

