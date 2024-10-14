#!/bin/bash

source /eda/scripts/init_questa

rm -rf work
mkdir work

vlib work
vlog -work ./work ../../cryptosource/aes_sbox_lut_hussain_6.v
vlog -work ./work +define+HUSSAIN_6 ../../cryptosource/aes_ks.v
vlog -work ./work +define+HUSSAIN_6 ../aes_round.v
vlog -work ./work ../aes_pipeline_top.v

vlog -work ./work ../../../tb/modelsim/clock_gen.sv

vlog -work ./work ../../../tb/modelsim/tb_aes_pipeline.sv

vsim -t 1ns work.tb_aes -voptargs=+acc -c -do run.do



