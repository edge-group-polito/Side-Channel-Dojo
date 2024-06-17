# AES side channel resistance implementation 
The Substituion-Box (S-Box) is the most vulnerable part to side channel attacks (SCA), the stadnard Rijndael S-box turns out to be very weak against power analysis attacks.
Tested diffent S-Box to see which gives the best resistance against SCA. It is a lightweight countermeasure.
The modified AES HW accelerator can be tested on the Chipwhisperer CW305 board, which integrates an Artix-7 FPGA. The AES accelerator is memory mapped and the control and status registers are driven through USB by a python API. An example could be found in `sca_jupyter/sca_test.ipynb` 

## Getting started
### Prerequisites 
1. Rely on open source [Verilator](https://opentitan.org/guides/getting_started/setup_verilator.html) to simulate the design 
2. Rely on [Fusesoc](https://github.com/olofk/fusesoc) as dependecy manager and to run tools 
3. Rely on open source [Verible](https://opentitan.org/guides/getting_started/index.html#step-7a-install-verible-optional) to format files 
4. Rely on Vivado to synthetisize desing on FPGA
5. The SCA attacks are run on the chipwhisperer board CW305 while the power traces are captured with picoscope 5000a 
   Needed chipwhisperer virtual envirnoment to run the attacks, to recreate the pyenv the requirements can be found in `sca_jupyter` directory
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
```
.
├── hw
│   ├── AES_scr
│   └── fpga
│       └── bitstream
├── sca_jupyter
│   └── sca_test_CW305_data
│       ├── analysis
│       ├── glitchresults
│       └── traces
├── scripts
├── sw
│   └── AES_python
└── tb
    ├── common
    ├── modelsim
    └── verilator
        ├── common
        └── misc
```

## Directories 
- `hw` : design HDL source files, fpga specific files (CW305 board with Artix-7) and already generated bitstream
- `tb` : testbench for the top level *aes_core*, supported modelsim and verilator 
- `sw` : software model of the AES, used as golden module
- `sca_jupyter` : jupyter notebook to run side channel attacks on the synthesized design within the CW305 boarda
- `scripts` : utility scripts 


## TODO: 
- [ ] Make sbox selection configurable in *aes_core.v* and test side-channel attacks 
- [ ] Fix verilator simulation ( input/output from/to file, use as golden model the *AES.py* )
- [ ] Automate side channel attack in Makefile 
- [ ] Pyevn with activation file instead of recreating it 

