source /eda/scripts/init_vivado_2019.2

mkdir ./aes_single_round_$sbox_type

vivado -mode batch -source ./sin_vivado_aes_single_round.tcl -log ./log_aes_single_round_$sbox_type.log

mv *.log ./aes_single_round_$sbox_type
mv *.jou ./aes_single_round_$sbox_type

