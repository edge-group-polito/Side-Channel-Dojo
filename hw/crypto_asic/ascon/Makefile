####################
# ----- INFO ----- #
####################
# Makefile to generate the ASCON files and build the design with fusesoc


#############################
# ----- CONFIGURATION ----- #
#############################

# General configuration
MAKE                       = make
BUILD_DIR	   	?= $(realpath .)/build

# Get the absolute path
mkfile_path := $(shell dirname "$(realpath $(firstword $(MAKEFILE_LIST)))")
$(info $$You are executing from: $(mkfile_path))

## ASCON RTL configurations
ASCON_ARCH 				?= ascon_init				# set to "ascon_asip" to use the ascon asip implementations	
ASCON_SBOX_MODE			?= lut						# set to "comb" to use the HW-based (combinational) Sbox
ASCON_SBOX 				?= standard					# set to one of the possible supported sboxes (e.g. allouzi)
# Remove the trailing whitespaces	
ASCON_ARCH := $(strip $(ASCON_ARCH))
ASCON_SBOX_MODE := $(strip $(ASCON_SBOX_MODE))
ASCON_SBOX := $(strip $(ASCON_SBOX))

# Verilog defines passed as flags to fusesoc 
ascon_arch_flag			?= --flag=$(ASCON_ARCH)  			
ascon_sbox_mode_flag	?= --flag=ascon_$(ASCON_SBOX_MODE)	
ascon_sub_layer_flag	?= --flag=sbox_$(ASCON_SBOX)

# ---------
# RTL simulation files
SIM_CORE_FILES 	:= $(shell find . -type f -name "*.core")
SIM_HDL_FILES 	:= $(shell find rtl -type f -name "*.v" -o -name "*.sv" -o -name "*.svh")

#######################
# ----- TARGETS ----- #
#######################

# Vivado synthesis
# ----------------
## Builds (synthesis and implementation) the bitstream of ASCON for the FPGA version using Vivado
.PHONY: vivado-fpga-ascon
vivado-fpga-ascon: | .check-fusesoc .check-vivado $(BUILD_DIR)/
	fusesoc --cores-root . run --no-export --target=cw305-ascon $(ascon_arch_flag) $(ascon_sbox_mode_flag) $(ascon_sub_layer_flag) $(FUSESOC_FLAGS) --build vlsi:polito:ascon:0.1.0

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
	@echo "ASCON SIM_HDL_FILES: $(SIM_HDL_FILES)"
	@echo "ASCON SIM_CPP_FILES: $(SIM_CPP_FILES)"