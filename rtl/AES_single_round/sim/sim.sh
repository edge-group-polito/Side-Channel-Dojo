#!/bin/bash

clear

chmod +x ./sim_aes.sh
chmod +x ./sim_freyre_1.sh
chmod +x ./sim_freyre_2.sh
chmod +x ./sim_freyre_3.sh
chmod +x ./sim_hussain_6.sh
chmod +x ./sim_ozkaynak_1.sh

./sim_aes.sh
cd ../../../tb/common
mv output_data.txt output_data_aes.txt
cd ../../rtl/AES_single_round/sim

./sim_freyre_1.sh
cd ../../../tb/common
mv output_data.txt output_data_freyre_1.txt
cd ../../rtl/AES_single_round/sim

./sim_freyre_2.sh
cd ../../../tb/common
mv output_data.txt output_data_freyre_2.txt
cd ../../rtl/AES_single_round/sim

./sim_freyre_3.sh
cd ../../../tb/common
mv output_data.txt output_data_freyre_3.txt
cd ../../rtl/AES_single_round/sim

./sim_hussain_6.sh
cd ../../../tb/common
mv output_data.txt output_data_hussain_6.txt
cd ../../rtl/AES_single_round/sim

./sim_ozkaynak_1.sh
cd ../../../tb/common
mv output_data.txt output_data_ozkaynak_1.txt
cd ../../rtl/AES_single_round/sim