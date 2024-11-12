####################
# ----- INFO ----- #
####################
# Makefile to generate the AES files and build the design with fusesoc


#############################
# ----- CONFIGURATION ----- #
#############################

# General configuration
MAKE                       = make
BUILD_DIR	   	?= $(realpath .)/build

# Get the absolute path
mkfile_path := $(shell dirname "$(realpath $(firstword $(MAKEFILE_LIST)))")
$(info $$You are executing from: $(mkfile_path))

## AES RTL configurations
AES_SBOX 				?= rijandael					#todo : use to select AES sbox
AES_ARCH 				?= aes_single_round				#todo : only implementation available is single round
# ---------
# RTL simulation files
SIM_CORE_FILES 	:= $(shell find . -type f -name "*.core")
SIM_HDL_FILES 	:= $(shell find rtl -type f -name "*.v" -o -name "*.sv" -o -name "*.svh")

#######################
# ----- TARGETS ----- #
#######################

# Vivado synthesis
# ----------------
## Builds (synthesis and implementation) the bitstream of AES for the FPGA version using Vivado
.PHONY: vivado-fpga-aes
vivado-fpga-aes: | .check-fusesoc .check-vivado $(BUILD_DIR)/
	fusesoc --cores-root . run --no-export --target=cw305-aes $(FUSESOC_FLAGS) --build vlsi:polito:aes:0.1.0

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
	@echo "AES SIM_HDL_FILES: $(SIM_HDL_FILES)"
	@echo "AES SIM_CPP_FILES: $(SIM_CPP_FILES)"