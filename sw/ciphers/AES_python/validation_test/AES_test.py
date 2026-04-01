""" 
    Testbench for the AES python model encryption and decryption 
    Tested all the sboxes
 """

import os
import sys
# Add AES_python directory to the path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..', 'AES_python'))
from AES_golden import AES_golden_model 

sbox_type = ["sbox_rijandael",
             "sbox_freyre_1",
             "sbox_freyre_2",
             "sbox_freyre_3",
             "sbox_hussain_6",
             "sbox_ozkaynak_1",
             "sbox_azam_1",
             "sbox_azam_2",
             "sbox_azam_3"]

for i in range(0,6):
    file_name = "./results/ciphertext_" + sbox_type[i] + "_results" + ".txt"
    file_name_2 = "./results/ciphertext_" + sbox_type[i] + ".txt"
    cipher_golden = AES_golden_model()
    
    with open(file_name,'w') as ciphertext_file:
        with open(file_name_2, 'w') as questa_file:
            with open('./KAT_AES/ECBKeySbox128e.txt', 'r') as file:
                file_line = "KEY                             " + " " + "PLAINTEXT                       " + " " + "CIPHERTEXT                      " 
                if(sbox_type[i] == "sbox_aes"):
                    file_line = file_line + " " + "Encryption    " + " " + "Decryption   "
                else:
                    file_line = file_line + " " + "Decryption   "
                print(file_line, file=ciphertext_file)
                lines = []
                for line in file:
                    lines.append(line)
                    if len(lines) == 5:
                        file_line = ""
                        count = lines[0].split(' = ')
                        key_matrix = lines[1].split(' = ')
                        plaintext_matrix = lines[2].split(' = ')
                        ciphertext_matrix = lines[3].split(' = ')

                        # Formatting the value for the key
                        key = key_matrix[1].replace('\n', '')
                        file_line += key

                        # Formatting the value for the ciphertext
                        plaintext_initial = plaintext_matrix[1].replace('\n', '')
                        file_line = file_line + " " + plaintext_initial
                        plaintext = [plaintext_initial[i:i+2] for i in range(0, len(plaintext_initial), 2)]
                        plaintext = ['0x' + element for element in plaintext]
                        plaintext = [int(s, 16) for s in plaintext]

                        # Formatting the value for the expected ciphertext(only for sbox_aes)
                        ciphertext = ciphertext_matrix[1].replace('\n', '')

                        # Encrypting the plaintext
                        ciphertext_sbox_aes = cipher_golden.encrypt(key,plaintext,sbox_type[i])
                        # Decrypting the ciphertext obtained by the encryption
                        plaintext_sbox_aes = cipher_golden.decrypt(key,ciphertext_sbox_aes,sbox_type[i])

                        # Formatting the ciphertext obtained from the encryption in a more readable format
                        ciphertext_sbox_aes = [hex(i) for i in ciphertext_sbox_aes]
                        ciphertext_sbox_aes = [s.replace('0x', '') for s in ciphertext_sbox_aes]
                        ciphertext_sbox_aes = [s.zfill(2) for s in ciphertext_sbox_aes]
                        ciphertext_sbox_aes = ''.join(ciphertext_sbox_aes)
                        file_line = file_line + " " + ciphertext_sbox_aes

                        # Formatting the plaintext obtained from the dencryption in a more readable format
                        plaintext_sbox_aes = [hex(i) for i in plaintext_sbox_aes]
                        plaintext_sbox_aes = [s.replace('0x', '') for s in plaintext_sbox_aes]
                        plaintext_sbox_aes = [s.zfill(2) for s in plaintext_sbox_aes]
                        plaintext_sbox_aes = ''.join(plaintext_sbox_aes)

                        # Print the result on the output file for a future comparison
                        print(file_line, file=questa_file)

                        # Comparison between the ciphertext obtained and the expected one(in the sbox_aes case)
                        if(sbox_type[i] == "sbox_aes"):
                            if ciphertext_sbox_aes != ciphertext:
                                file_line = file_line + " " + "Wrong         "
                                print(file_line)
                            else:
                                file_line = file_line + " " + "OK            "

                        # Comparison between the original plaintext and the one obtained from decryption
                        if plaintext_sbox_aes != plaintext_initial:
                            file_line = file_line + " " + "Wrong         "
                            print(file_line)
                        else:
                            file_line = file_line + " " + "OK            "

                        # Print the outputs on a file to see the results
                        print(file_line, file=ciphertext_file)

                        lines = []
