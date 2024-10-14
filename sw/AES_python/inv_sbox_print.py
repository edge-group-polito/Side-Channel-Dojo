from AES_operation import printInvSbox

sbox_type = ["sbox_aes",
             "sbox_freyre_1",
             "sbox_freyre_2",
             "sbox_freyre_3",
             "sbox_hussain_6",
             "sbox_ozkaynak_1",
             "sbox_azam_1",
             "sbox_azam_2",
             "sbox_azam_3"]

for i in range(len(sbox_type)):
    printInvSbox(sbox_type[i])