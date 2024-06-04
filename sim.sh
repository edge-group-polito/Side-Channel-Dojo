#!/bin/bash

clear

cd AES_python

python3 main.py

cd ../AES_verilog_modified/sim

./sim.sh

cd ../..

python3 difference.py

