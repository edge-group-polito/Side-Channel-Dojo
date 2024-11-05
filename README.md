# AES side channel resistance implementation 
The AES standard Substituion-Box (S-Box), known as Rijndael S-Box, is vulnerable against power analysis attacks. Tested new power-resistant S-Box. 
The modified AES HW accelerator can be tested on the Chipwhisperer CW305 board, which integrates the Artix-7 FPGA. 
The AES accelerator is memory mapped and the control and status registers are driven through USB by a python API. An example could be found in `sw/sca_jupyter/sca_test.ipynb` 

## Getting started
### Prerequisites 
1. Rely on open source [Verilator](https://opentitan.org/guides/getting_started/setup_verilator.html) to simulate the design 
2. Rely on [Fusesoc](https://github.com/olofk/fusesoc) as dependecy manager and to run tools 
3. Rely on open source [Verible](https://opentitan.org/guides/getting_started/index.html#step-7a-install-verible-optional) to format files 
4. Rely on Vivado to synthetisize desing on FPGA
5. The SCA attacks are run on the chipwhisperer board CW305 while the power traces are captured with picoscope 5000a 
   Chipwhisperer python virtual envirnoment requirements can be found in `sw` directory
### Building RTL simulation platform 
To run the RTL simulation on Verilator 
```
make verilator-build
make verilator-sim
```
To build and program the bitstream for the CW305 board
```
make vivado-fpga
```
More information in Makefile
## Repository folder structure 
|Folder                         | Description
|------ | -----------
|hw                           | **HDL source files, fpga specific files and already generated bitstream**
|  ├── AES_scr                | Verilog source files AES            
|  └── fpga                   | Artix-7 fpga specific files 
        └── bitstream          | Bitstream generated for all S-Box variants
|pics                         | **Block diagrams**
|scripts                      | **Utility scripts**   
|sw                           | **Golden AES software model, sca-attack jupyter notebook, python sca-functions**
|  ├── AES_python             | Golden AES software model                   
|  └── validation_test           | Validation KAT test                  
|  ├── notebook               | SCA-attack jupyter notebook              
|  └── sca_python             | Setup API, utility functions for plot, sca-attack functions                        
|tb                           | Testbench top level *aes_core*, supported modelsim and verilator 




## TODO: 
- [ ] Make sbox selection configurable in *aes_core.v* 
- [ ] Complete verilator simulation ( input/output from/to file, use as golden model the *AES.py* )
- [ ] Add Makefile command and fusesoc target for the Questasim simulation
- [ ] Readme in `AES_python/validation_test/` which explain the KAT tests used for AES  
- [ ] Finish python library for the interesting plots 
- [ ] Simulate and synthesize the AES pipeline version
- [ ] Fix instruction readme file to recreate venv in sw directory
- [ ] Fix aes core configuration as it is done with ascon 
- [ ] Add ascon rtl and all from Mattia Castagno repo
- [ ] add the python version of the notebook in the folder "sw/sca_python/tests/aes/"

*Optional :*
- [ ] Makefile command which run python script to capture power traces
- [ ] Makefile command which run python script to perform CPA attack  
- [ ] Pyevn with activation file instead of recreating it (docker kind of?)
- [ ] Define the best way to organize to python repo, should be scalable (easy to add new attacks and targets) and intuitive  

## Ascon integration
1. Create directory in hw/ascon to contain all hdl files and associate .core files
2. Create fpga wrapper and relative register associate files, put them inside custom directory in hw/fpga
3. Create fileset and target of added files in aes_scr.core 

to check : 
[?] a lot of registers in cw305_reg_ascon.sv are unused and semms uselessù
to do (asap):
- fix core files organization 
  - add in core file of each crypto target the target to run simulation and synthesis 
- if wanted configurable simulation needed crypto_target as top module name.. boh
- comunque aggiungere la roba di ascon di mattia castagno
- Chiedere a gigi se apprezza il core file opppure asosulatemente no