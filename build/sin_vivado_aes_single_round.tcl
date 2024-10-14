# Typical usage "vivado -mode batch -source ./sin_vivado_aes_single_round.tcl"

#
# STEP#0: define output directory area. 
#
set SBOX_TYPE $::env(sbox_type)

set outputDir ./aes_single_round_$SBOX_TYPE
file mkdir $outputDir

#
# STEP#1: setup design sources and constraints
#
read_verilog ../hw/AES_single_round/aes_sbox_lut_rijandael.v
read_verilog ../hw/AES_single_round/aes_sbox_lut_freyre_1.v
read_verilog ../hw/AES_single_round/aes_sbox_lut_freyre_2.v 
read_verilog ../hw/AES_single_round/aes_sbox_lut_freyre_3.v 
read_verilog ../hw/AES_single_round/aes_sbox_lut_hussain_6.v 
read_verilog ../hw/AES_single_round/aes_sbox_lut_ozkaynak_1.v 
read_verilog ../hw/AES_single_round/aes_sbox_lut_azam_1.v 
read_verilog ../hw/AES_single_round/aes_sbox_lut_azam_2.v 
read_verilog ../hw/AES_single_round/aes_sbox_lut_azam_3.v 
read_verilog ../hw/AES_single_round/aes_ks.v 
read_verilog ../hw/AES_single_round/aes_core.v 

read_verilog ../hw/fpga/cdc_pulse.v 
read_verilog ../hw/fpga/clocks.v 
read_verilog ../hw/fpga/cw305_aes_defines.v 
read_verilog ../hw/fpga/cw305_reg_aes.v 
read_verilog ../hw/fpga/cw305_usb_reg_fe.v
read_verilog ../hw/fpga/cw305_top.v

read_xdc ../hw/fpga/cw305.xdc

#
# STEP#2: run synthesis, report utilization and timing estimates, write checkpoint design
#
synth_design -top cw305_top -part xc7a100tftg256-2 -verilog_define $SBOX_TYPE=True
write_checkpoint -force $outputDir/post_synth
report_timing_summary -file $outputDir/post_synth_timing_summary.rpt
report_power -file $outputDir/post_synth_power.rpt

#
# STEP#3: run placement and logic optimization, report utilization and timing estimates, write checkpoint design
#
opt_design
place_design
phys_opt_design
write_checkpoint -force $outputDir/post_place
report_timing_summary -file $outputDir/post_place_timing_summary.rpt

#
# STEP#4: run router, report actual utilization and timing, write checkpoint design, run drc, write verilog and xdc out
#
route_design
write_checkpoint -force $outputDir/post_route
report_timing_summary -file $outputDir/post_route_timing_summary.rpt
report_timing -sort_by group -max_paths 100 -path_type summary -file $outputDir/post_route_timing.rpt
report_clock_utilization -file $outputDir/clock_util.rpt
report_utilization -file $outputDir/post_route_util.rpt
report_power -file $outputDir/post_route_power.rpt
report_drc -file $outputDir/post_imp_drc.rpt
write_verilog -force $outputDir/bft_impl_netlist.v
write_xdc -no_fixed_only -force $outputDir/bft_impl.xdc

#
# STEP#5: generate a bitstream
#
write_bitstream -force $outputDir/cw305_top_aes_single_round_$SBOX_TYPE.bit