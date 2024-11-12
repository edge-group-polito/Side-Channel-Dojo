####################
# ----- INFO ----- #
####################
# Root Makefile of the side channel DOJO project

#############################
# ----- CONFIGURATION ----- #
#############################

# General configuration
MAKE           	?= make
BUILD_DIR	   	?= $(realpath .)/build

## AES RTL configurations
AES_SBOX 				?= rijandael				#todo : use to select AES sbox
AES_ARCH 				?= single_round				#todo : only implementation available is single round
# remove the trailing whitespaces
aes_sbox_strip		 	:= $(strip $(AES_SBOX))
aes_arch_strip		 	:= $(strip $(AES_ARCH))
# AES bitstream path
AES_bitstream_path 		?= hw/crypto_asic/aes/build/vlsi_polito_aes_0.1.0/cw305-aes-vivado/vlsi_polito_aes_0.1.0.bit

## ASCON RTL configurations
ASCON_ARCH 				?= ascon_init			# set to "ascon_asip" to use the ascon asip implementations	
ASCON_SBOX_MODE			?= lut					# set to "comb" to use the HW-based (combinational) Sbox
ASCON_SBOX 				?= standard				# set to one of the possible supported sboxes
# Remove the trailing whitespaces	
ASCON_ARCH := $(strip $(ASCON_ARCH))
ASCON_SBOX_MODE := $(strip $(ASCON_SBOX_MODE))
ASCON_SBOX := $(strip $(ASCON_SBOX))
# ASCON bitstream path
#ASCON_bitstream_path 	?= hw/crypto_asic/ascon/build/vlsi_polito_ascon_0.1.0/cw305-ascon-vivado/vlsi:polito:ascon:0.1.0.runs/impl_1/vlsi_polito_ascon_0.1.0.bit 
ASCON_bitstream_path 	?= hw/crypto_asic/ascon/build/vlsi_polito_ascon_0.1.0/cw305-ascon-vivado/vlsi_polito_ascon_0.1.0.bit
# RTL simulation configs
MAX_CYCLES		?= 100000
LOG_LEVEL		?= LOG_MEDIUM
DUMP_TRACE		?= true
DUMP_WAVES		?= true

# ---------
# RTL simulation files
SIM_CORE_FILES 	:= $(shell find . -type f -name "*.core")
SIM_HDL_FILES 	:= $(shell find hw -type f -name "*.v" -o -name "*.sv" -o -name "*.svh")
SIM_HDL_FILES 	+= $(shell find tb -type f -name "*.v" -o -name "*.sv" -o -name "*.svh")
SIM_CPP_FILES	:= $(shell find tb/verilator -type f -name "*.cpp" -o -name "*.hh")

#######################
# ----- TARGETS ----- #
#######################
# HDL source
# ----------
# Format code
.PHONY: format
format: | .check-fusesoc
	@echo "\e[1;37;44m## Formatting RTL code...\e[0m"
	fusesoc run --no-export --target format vlsi:polito:crypto_targets:0.1.0

# Static analysis
.PHONY: lint
lint: | .check-fusesoc
	@echo "\e[1;37;44m## Running static analysis...\e[0m"
	fusesoc run --no-export --target lint vlsi:polito:crypto_targets:0.1.0

# Vivado synthesis
# ----------------
.PHONY: vivado-fpga-aes
vivado-fpga-aes: ./hw/fpga/bitstream/aes/$(aes_arch_strip)/
	$(MAKE) -C hw/crypto_asic/aes vivado-fpga-aes AES_SBOX=$(AES_SBOX)
	cp $(AES_bitstream_path) hw/fpga/bitstream/aes/cw305_top_$(aes_sbox_strip).bit	

.PHONY: vivado-fpga-ascon
vivado-fpga-ascon: ./hw/fpga/bitstream/ascon/$(ASCON_ARCH)/
	$(MAKE) -C hw/crypto_asic/ascon vivado-fpga-ascon ASCON_ARCH=$(ASCON_ARCH) ASCON_SBOX_MODE=$(ASCON_SBOX_MODE) ASCON_SBOX=$(ASCON_SBOX)
	@if [ "$(ASCON_ARCH)" = "ascon_asip" ]; then \
	    echo cp $(ASCON_bitstream_path) hw/fpga/bitstream/ascon/ascon_asip/cw305_top_asip.bit; \
	    cp $(ASCON_bitstream_path) hw/fpga/bitstream/ascon/ascon_asip/cw305_top_asip.bit; \
	else \
	    echo cp $(ASCON_bitstream_path) hw/fpga/bitstream/ascon/ascon_init/cw305_top_$(ASCON_SBOX)_$(ASCON_SBOX_MODE).bit; \
	    cp $(ASCON_bitstream_path) hw/fpga/bitstream/ascon/ascon_init/cw305_top_$(ASCON_SBOX)_$(ASCON_SBOX_MODE).bit; \
	fi	

cp-test: ./hw/fpga/bitstream/ascon/$(ASCON_ARCH)/
	cp $(ASCON_bitstream_path) hw/fpga/bitstream/ascon/ascon_init/cw305_top_$(ASCON_SBOX)_$(ASCON_SBOX_MODE).bit; \

# Software
# -----------------
# Python simulation
.PHONY: aes-py
#todo: add the python simulation makefile command

# RTL simualtion
# --------------
# ModelSim simulation
## Questasim simulation
.PHONY: aes-questasim-sim
aes-questasim-sim: | .check-fusesoc $(BUILD_DIR)/
	fusesoc	run --no-export --target aes-sim --tool=modelsim $(FUSESOC_FLAGS) --build  vlsi:polito:crypto_targets:0.1.0 | tee build/buildsim.log

# Build Verilator model
# Re-run every time the necessary files (.core, RTL, CPP) change
## @param FUSESOC_FLAGS=--flag=<flagname> to set the AES pipeline configuration or not 
.PHONY: aes-verilator-build 
aes-verilator-build: $(BUILD_DIR)/.verilator.lock
$(BUILD_DIR)/.verilator.lock: $(SIM_CORE_FILES) $(SIM_HDL_FILES) $(SIM_CPP_FILES) | .check-fusesoc $(BUILD_DIR)/
	@echo "\e[1;37;44m## Building simulation model with Verilator...\e[0m"
	fusesoc run --no-export --target aes-sim --tool verilator $(FUSESOC_FLAGS) --build vlsi:polito:crypto_targets:0.1.0
	touch $@

# Run Verilator simulation
.PHONY: aes-verilator-sim
aes-verilator-sim: $(BUILD_DIR)/.verilator.lock | .check-fusesoc
	fusesoc run --no-export --target aes-sim --tool verilator --run $(FUSESOC_FLAGS) vlsi:polito:crypto_targets:0.1.0 \
		--log_level=$(LOG_LEVEL) \
		--max_cycles=$(MAX_CYCLES) \
		--dump_trace=$(DUMP_TRACE) \cw305_top_ascon_hw_sbox_ascon .bit
		
# Open dumped waveform with GTKWave
.PHONY: verilator-waves
verilator-waves: $(BUILD_DIR)/sim-verilator/logs/waves.fst | .check-gtkwave
	gtkwave -a tb/misc/verilator-waves.gtkw $<

# Utilities
# ---------
# Check if fusesoc is available
.PHONY: .check-fusesoc
.check-fusesoc:
	@if [ ! `which fusesoc` ]; then \
	printf -- "### ERROR: 'fusesoc' is not in PATH. Is the correct conda environment active?\n" >&2; \
	exit 1; fi

# Check if GTKWave is available
.PHONY: .check-gtkwave
.check-gtkwave:
	@if [ ! `which gtkwave` ]; then \
	printf -- "### ERROR: 'gtkwave' is not in PATH. Is the correct conda environment active?\n" >&2; \
	exit 1; fi

# Check if Vivado is available
.PHONY: .check-vivado
.check-vivado:
	@if [ ! `which vivado` ]; then \
	printf -- "### ERROR: 'vivado' is not in PATH. Is the correct environment active?\n" >&2; \
	exit 1; fi

# Create new directories
%/:
	mkdir -p $@

# Clean-up
.PHONY: clean
clean:
	@rm -rf $(BUILD_DIR)

# Print rtl and simulation files 
.PHONY: .print
.print:
	@echo "SIM_HDL_FILES: $(SIM_HDL_FILES)"
	@echo "SIM_CPP_FILES: $(SIM_CPP_FILES)"
