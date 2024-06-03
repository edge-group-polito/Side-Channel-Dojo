#!/bin/bash

clear

source /eda/scripts/init_questa

rm -rf work
mkdir work

vlib work
vlog -work ./work ../src/aes_ks.v
vlog -work ./work ../src/aes_sbox.v
vlog -work ./work ../src/aes_sbox_lut.v
vlog -work ./work ../src/aes_core.v

vlog -work ./work ../tb/clock_generator.sv

vlog -work ./work ../tb/tb_aes.sv

vsim -t 1ns work.tb_aes -voptargs=+acc



