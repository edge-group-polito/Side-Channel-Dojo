#!/bin/bash

source /eda/scripts/init_questa

rm -rf work
mkdir work

vlib work
vlog -work ./work ../aes_ks.v
vlog -work ./work ../../cryptosource/aes_sbox_lut_rijandael.v
vlog -work ./work ../aes_core.v

vlog -work ./work ../../../tb/modelsim/clock_gen.sv

vlog -work ./work ../../../tb/modelsim/tb_aes.sv

vsim -t 1ns work.tb_aes -voptargs=+acc -c -do run.do



