# Side Channel Dojo
This repository provides an environment to facilitate the testing of cryptographic implementations against power-based side-channel attacks. 
The environment supports the use of the Chipwhisperer CW305 testing board and the Picoscope 5000a for capturing power traces.
## Getting started
### Prerequisites 
1. Rely on open source [Verilator](https://opentitan.org/guides/getting_started/setup_verilator.html) to simulate the design 
2. Rely on [Fusesoc](https://github.com/olofk/fusesoc) as dependecy manager and to run tools 
3. Rely on open source [Verible](https://opentitan.org/guides/getting_started/index.html#step-7a-install-verible-optional) to format files 
4. Rely on Vivado to synthetisize desing on FPGA
5. The SCA attacks are run on the chipwhisperer CW305 board (mounts Artix-7 FPGA) while the power traces are captured with picoscope 5000a. 

Once installed all the prerequisites the tutorial to create the python virtual environment to conduct the attacks can be found in `sw` directory
## Examples of Cryptographic module 
The repository provides two examples, both demonstrating the use of a cryptographic module implemented as an ASIC. This module is controlled via memory mapping, with its status and control registers accessible for reading and writing through USB using a Python API.
#### The Advanced Encryption Standard (AES)
The AES standard Substitution-Box (S-Box), known as the Rijndael S-Box, is vulnerable to power analysis attacks. This repository contains a power-resistant S-Boxes that can be easily tested against such attacks.

##### Makefile configuration for AES
- **AES_SBOX** : defualt value is "rijandael". The whole list of supported Sbox can be found in `hw/aes/rtl/AES_common/Sbox`
- **AES_ARCH** : defualt value is "single_round". Select the AES architectue to use, supported only the single round implementation 
---
Missing the support to configure the implementation with an arbitrary length of rounds per clock 

---

Therefore if wanted to synthesize the AES single round implementation with the `azam_1` Sbox (LUT implementation)
```shell
make vivado-fpga-aes AES_ARCH=single_round AES_SBOX=azam_1
```
The bitstream is saved into the `fpga/bitstream` directory
#### ASCON
The repository provides two ASCON designs: one generated with ASIP and another that includes only the first round of ASCON, which is sufficient to perform power side-channel attacks.
##### Makefile configuration for ASCON
**ASCON_ARCH** : default value is "ascon_init". Select which architecture of ASCON to use, at the moment supported "ascon_init" which implements only the first round of Ascon and "ascon_asip" which is the architecture of Ascon generated with ASIP designer (https://www.synopsys.com/dw/ipdir.php?ds=asip-designer).  			
If selected `ASCON_ARCH=ascon_init` then the rtl can be configured with:
**ASCON_SBOX_MODE** : default value is "lut". Select the implementation of the SBox to use, if the "lut" implemntation or the "comb" one. If selected combinational Sbox the only supported one is the standard. 
**ASCON_SBOX** : default value is "sbox_standard". The whole list of supported Sbox (only lut implementation) can be found in `hw/aes/rtl/AES_common/Sbox` and how the verilog defines are use in `sub_layer_lut.sv`

Therefore if wanted to synthesize the ASCON first round implementation with the `allouzi` Sbox (LUT implementation)

```shell
make vivado-fpga-aes ASCON_ARCH=ascon_init ASCON_SBOX=allouzi ASCON_SBOX_MODE=lut
```
The bitstream is saved into the `fpga/bitstream` directory
### Building RTL simulation platform 
Taking as example the AES implementation, to run the RTL simulation on Verilator 
```
make aes-verilator-build
make aes-verilator-sim
```
To build and program the bitstream for the CW305 board
```
make vivado-fpga-aes
```
More information in Makefile

### Run the attack
An example could be found in `sw/sca_jupyter/sca_test.ipynb` 
## Repository folder structure 
|Folder                         | Description
|------                         | -----------
|hw                             | **HDL source files, fpga specific files and already generated bitstream**
|  ├── crypto_asic              | **Verilog source files of crypto ASIC** 
| │   └── aes              | Source files and targets for AES Asic implementation
 │└── ascon               | Source files and targets for Ascon Asic implementation
|  └── fpga                     | Artix-7 fpga specific files 
        └── bitstream           | Bitstream generated 
|pics                           | **Block diagrams**
|scripts                        | **Utility scripts**   
|sw                             | **Golden AES software model, sca-attack jupyter notebook, python sca-functions**
|  ├── AES_python               | Golden AES software model                   
|  └── validation_test          | Validation KAT test                  
|  ├── notebook                 | SCA-attack jupyter notebook              
|  └── sca_python               | Setup API, utility functions for plot, sca-attack functions                        
|tb                             | Testbench top level *aes_core*, supported modelsim and verilator 




## TODO: 
- [ ] Finiah verilator simulation ( input/output from/to file, use as golden model the *AES_golden.py* )
- [ ] Add support for the Questasim simulation
- [ ] Readme missing in `AES_python/validation_test/` which explain the KAT tests used for AES  
- [ ] Library for common plots in `sw/sca_python/analyzer/utils`
- [ ] Simulate and synthesize the AES pipeline version
- [ ] Test readme file in `sw` to recreate the environment
- [ ] Python version of the notebook in the folder "sw/sca_python/tests/aes/"

*Optional :*
- [ ] Makefile command which run python script to capture power traces
- [ ] Makefile command which run python script to perform CPA attack  
- [ ] Docker of the environment

## TO CHECK: 
- a lot of registers in cw305_reg_ascon.sv are unused and can be removed (to do asap)