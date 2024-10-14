clear

chmod +x ./sin.sh

export sbox_type=RIJANDAEL

./sin.sh

cp ./aes_single_round_$sbox_type/cw305_top_aes_single_round_$sbox_type.bit ../hw/fpga/bitstream/cw305_top_aes_single_round_$sbox_type.bit

export sbox_type=FREYRE_1

./sin.sh

cp ./aes_single_round_$sbox_type/cw305_top_aes_single_round_$sbox_type.bit ../hw/fpga/bitstream/cw305_top_aes_single_round_$sbox_type.bit

export sbox_type=FREYRE_2

./sin.sh

cp ./aes_single_round_$sbox_type/cw305_top_aes_single_round_$sbox_type.bit ../hw/fpga/bitstream/cw305_top_aes_single_round_$sbox_type.bit

export sbox_type=FREYRE_3

./sin.sh

cp ./aes_single_round_$sbox_type/cw305_top_aes_single_round_$sbox_type.bit ../hw/fpga/bitstream/cw305_top_aes_single_round_$sbox_type.bit

export sbox_type=HUSSAIN_6

./sin.sh

cp ./aes_single_round_$sbox_type/cw305_top_aes_single_round_$sbox_type.bit ../hw/fpga/bitstream/cw305_top_aes_single_round_$sbox_type.bit

export sbox_type=OZKAYNAK_1

./sin.sh

cp ./aes_single_round_$sbox_type/cw305_top_aes_single_round_$sbox_type.bit ../hw/fpga/bitstream/cw305_top_aes_single_round_$sbox_type.bit

export sbox_type=AZAM_1

./sin.sh

cp ./aes_single_round_$sbox_type/cw305_top_aes_single_round_$sbox_type.bit ../hw/fpga/bitstream/cw305_top_aes_single_round_$sbox_type.bit

export sbox_type=AZAM_2

./sin.sh

cp ./aes_single_round_$sbox_type/cw305_top_aes_single_round_$sbox_type.bit ../hw/fpga/bitstream/cw305_top_aes_single_round_$sbox_type.bit

export sbox_type=AZAM_3

./sin.sh

cp ./aes_single_round_$sbox_type/cw305_top_aes_single_round_$sbox_type.bit ../hw/fpga/bitstream/cw305_top_aes_single_round_$sbox_type.bit

