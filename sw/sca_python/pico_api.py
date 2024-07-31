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

@brief   picoscope 5000a series api wrapper
"""

from picoscope import ps5000a
import chipwhisperer as cw
import time
from picosdk.discover import find_all_units


class PS5000aWrapper:
    """Class to manage the PicoScope 5000a series digital oscilloscope.
    
    #. Attach the picoscope to the computer

    #. Coonect to scope using::
            
            from pico_api import PS5000aWrapper

            ps = PS5000aWrapper()
            ps.scope_setup(obs_time, nSamples)
    
    #. Capture a trace using::
        
            data = ps.capture()
    
    #. Disconnect the picoscope using::
            
            ps.dis()
    
    """

    def __init__(self):
        if not self.check_connection():
            raise Exception("No Picoscope connected.")
        else:
            self.ps = ps5000a.PS5000a()
        pass

    def check_connection(self):
        """ Check if the Picoscope is connected """
        scopes = find_all_units()
        if not scopes:
            print("No Picoscope connected.")
            return False
        else:
            for scope in scopes:
                scope.close()
            return True
    
    def get_unitInfo(self):
        """ Get the unit info of the connected picoscope """
        print("Found the following picoscope:")
        print(self.ps.getAllUnitInfo())

    def scope_setup(self, obs_time=3.225E-6, nSamples=1260):
        """Set the picoscope parameters."""
        self.obs_time = obs_time
        self.nSamples = nSamples
        # Configure timebase
        (self.sample_interval, self.nSamples, self.maxSamples) = self.ps.setSamplingInterval(self.obs_time/self.nSamples, self.obs_time)
        # Set up channel A with 50mV range, AC coupled, 20 MHz BW limit
        self.ps.setChannel('A', 'AC', 0.05, 0.0, enabled=True, BWLimited=True)
        self.channelASettings = "Channel A: Range = 50mV, AC coupling, 20 MHz BW limit"
        # Channel B is trigger
        self.ps.setChannel('B', 'DC', 10.0, 0.0, enabled=True)
        self.ps.setSimpleTrigger('B', 2.0, 'Rising', timeout_ms=2000, enabled=True)
        self.channelBSettings = "Channel B: Range = 10V, DC coupling, trigger"
    
    def get_scopeSettings(self):
        """Get the current scope settings."""
        print("Nsamples : ", self.nSamples)
        print("Sampling interval = %f us", self.sample_interval)
        print("Channel A settings: ", self.channelASettings)
        print("Channel B settings: ", self.channelBSettings)
    
    def get_samplingInterval(self):
        """Get the sampling interval."""
        return self.sample_interval

    def runBlock(self):
        """Run the picoscope."""
        self.ps.runBlock()
    
    def waitReady(self):
        """Wait for the picoscope to be ready."""
        self.ps.waitReady()
    
    def getDataV(self, returnOverflow=False):
        """Get the data from the picoscope.
        Channel A is the one used to cpature the trace."""
        data = self.ps.getDataV('A', self.nSamples, returnOverflow)
        return data
        
    def dis(self):
        """Disconnect the picoscope."""
        self.ps.close()
