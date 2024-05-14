from AES import AES as AES # type: ignore

sbox_type = ["sbox_aes",
             "sbox_freyre_1",
             "sbox_freyre_2",
             "sbox_freyre_3",
             "sbox_hussain_6",
             "sbox_ozkaynak_1"]

for i in range(0,6):
    file_name = "ciphertext_" + sbox_type[i] + ".txt"
    with open(file_name,'w') as ciphertext_file:
        with open('./KAT_AES/ECBKeySbox128e.txt', 'r') as file:
            file_line = "KEY                             " + " " + "PLAINTEXT                       " + " " + "CIPHERTEXT                      "
            print(file_line, file=ciphertext_file)
            lines = []
            for line in file:
                lines.append(line)
                if len(lines) == 5:
                    file_line = ""
                    count = lines[0].split(' = ')
                    key_matrix = lines[1].split(' = ')
                    plaintext_matrix = lines[2].split(' = ')
                    ciphertext = lines[3].split(' = ')

                    key = key_matrix[1].replace('\n', '')
                    file_line += key
                    key = [key[i:i+2] for i in range(0, len(key), 2)]
                    key = ['0x' + element for element in key]
                    key = [int(s, 16) for s in key]
                    plaintext_initial = plaintext_matrix[1].replace('\n', '')
                    file_line = file_line + " " + plaintext_initial
                    plaintext = [plaintext_initial[i:i+2] for i in range(0, len(plaintext_initial), 2)]
                    plaintext = ['0x' + element for element in plaintext]
                    plaintext = [int(s, 16) for s in plaintext]

                    ciphertext_sbox_aes = AES.encrypt(key,plaintext,sbox_type[i])
                    plaintext_sbox_aes = AES.decrypt(key,ciphertext_sbox_aes,sbox_type[i])

                    ciphertext_sbox_aes = [hex(i) for i in ciphertext_sbox_aes]
                    ciphertext_sbox_aes = [s.replace('0x', '') for s in ciphertext_sbox_aes]
                    ciphertext_sbox_aes = [s.zfill(2) for s in ciphertext_sbox_aes]
                    ciphertext_sbox_aes = ''.join(ciphertext_sbox_aes)
                    file_line = file_line + " " + ciphertext_sbox_aes

                    plaintext_sbox_aes = [hex(i) for i in plaintext_sbox_aes]
                    plaintext_sbox_aes = [s.replace('0x', '') for s in plaintext_sbox_aes]
                    plaintext_sbox_aes = [s.zfill(2) for s in plaintext_sbox_aes]
                    plaintext_sbox_aes = ''.join(plaintext_sbox_aes)

                    if plaintext_sbox_aes != plaintext_initial:
                        file_line = file_line + " " + "Decryption wrong"
                        print(file_line)
                    else:
                        file_line = file_line + " " + "Decryption OK"

                    print(file_line, file=ciphertext_file)

                    lines = []