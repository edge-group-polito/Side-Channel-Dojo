#!/bin/bash

source /eda/scripts/init_questa

rm -rf work
mkdir work

vlib work
vlog -work ./work +define+FREYRE_1 ../aes_ks.v
vlog -work ./work ../../cryptosource/aes_sbox_lut_freyre_1.v
vlog -work ./work +define+FREYRE_1 ../aes_core.v

vlog -work ./work ../../../tb/modelsim/clock_gen.sv

vlog -work ./work ../../../tb/modelsim/tb_aes.sv

vsim -t 1ns work.tb_aes -voptargs=+acc -c -do run.do



