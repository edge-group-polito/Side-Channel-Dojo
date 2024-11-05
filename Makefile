####################
# ----- INFO ----- #
####################
# Makefile to generate the AES files and build the design with fusesoc

#############################
# ----- CONFIGURATION ----- #
#############################

# General configuration
MAKE           	?= make
BUILD_DIR	   	?= $(realpath .)/build

# Crypto target configuration
SBOX 			?= rijandael

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
		--dump_trace=$(DUMP_TRACE) \
		--dump_waves=$(DUMP_WAVES) \
		$(FUSESOC_ARGS)

#todo: add the ascon simulation with verilator makefile command

# Open dumped waveform with GTKWave
.PHONY: verilator-waves
verilator-waves: $(BUILD_DIR)/sim-verilator/logs/waves.fst | .check-gtkwave
	gtkwave -a tb/misc/verilator-waves.gtkw $<

# Vivado synthesis
# ----------------
## Builds (synthesis and implementation) the bitstream for the FPGA version using Vivado

# aes FPGA synthesis
.PHONY: vivado-fpga-aes
vivado-fpga-aes: | .check-fusesoc .check-vivado $(BUILD_DIR)/
	fusesoc run --no-export --target=cw305-aes $(FUSESOC_FLAGS) --build vlsi:polito:crypto_targets:0.1.0
	cp $(BUILD_DIR)/vlsi_polito_crypto_targets_0.1.0/cw305-aes-vivado/vlsi_polito_crypto_targets_0.1.0.runs/impl_1/cw305_top.bit  hw/fpga/bitstream/aes/cw305_top_$(SBOX).bit

.PHONY: vivado-fpga-ascon
vivado-fpga-ascon: | .check-fusesoc .check-vivado $(BUILD_DIR)/
	fusesoc run --no-export --target=cw305-ascon --flag "asip_impl" $(FUSESOC_FLAGS) --build vlsi:polito:crypto_targets:0.1.0
	cp $(BUILD_DIR)/vlsi_polito_crypto_targets_0.1.0/cw305-ascon-vivado/vlsi_polito_crypto_targets_0.1.0.runs/impl_1/cw305_top.bit hw/fpga/bitstream/ascon/cw305_top.bit


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
