#!/bin/bash

clear

cd ../sw/AES_python

python3 main.py

cd ../../hw/AES_single_round/sim

chmod +x sim.sh
./sim.sh

cd ../../../sw

python3 difference_aes_single_round.py

