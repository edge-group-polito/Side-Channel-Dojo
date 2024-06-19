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

# Sbox used
SBOX 			?= rijandael

# RTL simulation 
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
	fusesoc run --no-export --target format polito:aes_scr:aes_scr

# Static analysis
.PHONY: lint
lint: | .check-fusesoc
	@echo "\e[1;37;44m## Running static analysis...\e[0m"
	fusesoc run --no-export --target lint polito:aes_scr:aes_scr

# Software
# -----------------
# Python simulation
.PHONY: aes-py


# RTL simualtion
# --------------
# ModelSim simulation
## Questasim simulation
.PHONY: questasim-sim
questasim-sim: | .check-fusesoc $(BUILD_DIR)/
	fusesoc	run --no-export --target=sim --tool=modelsim $(FUSESOC_FLAGS) --build  polito:aes_scr:aes_scr | tee build/buildsim.log

# Build Verilator model
# Re-run every time the necessary files (.core, RTL, CPP) change
.PHONY: verilator-build
verilator-build: $(BUILD_DIR)/.verilator.lock
$(BUILD_DIR)/.verilator.lock: $(SIM_CORE_FILES) $(SIM_HDL_FILES) $(SIM_CPP_FILES) | .check-fusesoc $(BUILD_DIR)/
	@echo "\e[1;37;44m## Building simulation model with Verilator...\e[0m"
	fusesoc run --no-export --target sim --tool verilator $(FUSESOC_FLAGS) --build polito:aes_scr:aes_scr
	touch $@

# Run Verilator simulation
.PHONY: verilator-sim
verilator-sim: $(BUILD_DIR)/.verilator.lock | .check-fusesoc
	fusesoc run --no-export --target sim --tool verilator --run $(FUSESOC_FLAGS) polito:aes_scr:aes_scr \
		--log_level=$(LOG_LEVEL) \
		--max_cycles=$(MAX_CYCLES) \
		--dump_trace=$(DUMP_TRACE) \
		--dump_waves=$(DUMP_WAVES) \
		$(FUSESOC_ARGS)

# Open dumped waveform with GTKWave
.PHONY: verilator-waves
verilator-waves: $(BUILD_DIR)/sim-verilator/logs/waves.fst | .check-gtkwave
	gtkwave -a tb/misc/verilator-waves.gtkw $<

## Builds (synthesis and implementation) the bitstream for the FPGA version using Vivado
# FPGA synthesis
.PHONY: vivado-fpga
vivado-fpga: | .check-fusesoc .check-vivado $(BUILD_DIR)/
	fusesoc run --no-export --target=cw305 $(FUSESOC_FLAGS) --build polito:aes_scr:aes_scr
	cp $(BUILD_DIR)/polito_aes_scr_aes_scr_0.1.0/cw305-vivado/polito_aes_scr_aes_scr_0.1.0.runs/impl_1/cw305_top.bit hw/fpga/bitstream/cw305_top_$(SBOX).bit

# Vivado synthesis
# ----------------

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
