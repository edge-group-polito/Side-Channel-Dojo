from AES_operation import SubBytes as SubBytes # type: ignore
from AES_operation import InvSubBytes as InvSubBytes # type: ignore
from AES_operation import ShiftRows as ShiftRows # type: ignore
from AES_operation import InvShiftRows as InvShiftRows # type: ignore
from AES_operation import MixColumns as MixColumns # type: ignore
from AES_operation import InvMixColumns as InvMixColumns # type: ignore
from AES_operation import AddRoundKey as AddRoundKey # type: ignore
from AES_operation import KeyExpansion as KeyExpansion # type: ignore
from AES_operation import bytes2matrix as bytes2matrix # type: ignore
from AES_operation import matrix2bytes as matrix2bytes # type: ignore
from AES_operation import split_blocks as split_blocks # type: ignore
from AES_operation import print_hex as print_hex # type: ignore

class AES:

    def encrypt_block(key,plaintext,sbox_type):

        plain_state = bytes2matrix(plaintext)
        round_keys = KeyExpansion(sbox_type,key)

        #print("Keys:\n")
        #for key in round_keys:
        #    key_new = matrix2bytes(key)
        #    key_new = [hex(i) for i in key_new]
        #    key_new = [s.replace('0x', '') for s in key_new]
        #    key_new = [s.zfill(2) for s in key_new]
        #    key_new = ''.join(key_new)
        #    
        #    print(key_new)
        #print("\n")

        #Initial round
        AddRoundKey(plain_state, round_keys[0])

        #Intermediate rounds
        for i in range(1,10):
            #print("Round " + str(i))
            SubBytes(sbox_type,plain_state)
            plain_state = ShiftRows(plain_state)
            plain_state = MixColumns(plain_state)
            AddRoundKey(plain_state,round_keys[i])
            #print()

        #Final round
        SubBytes(sbox_type,plain_state)
        plain_state = ShiftRows(plain_state)
        AddRoundKey(plain_state,round_keys[10])

        return matrix2bytes(plain_state)
    
    def decrypt_block(key,ciphertext,sbox_type):

        cipher_state = bytes2matrix(ciphertext)
        round_keys = KeyExpansion(sbox_type,key)

        AddRoundKey(cipher_state,round_keys[10])
        cipher_state = InvShiftRows(cipher_state)
        InvSubBytes(sbox_type,cipher_state)

        for i in range(9,0,-1):
            AddRoundKey(cipher_state,round_keys[i])
            cipher_state = InvMixColumns(cipher_state)
            cipher_state = InvShiftRows(cipher_state)
            InvSubBytes(sbox_type,cipher_state)

        AddRoundKey(cipher_state, round_keys[0])

        return matrix2bytes(cipher_state)
    
    def encrypt(key, plaintext, sbox_type):

        blocks = []

        for plaintext_block in split_blocks(plaintext):
            block = AES.encrypt_block(key,plaintext_block,sbox_type)
            blocks.append(block)

        return [element for row in blocks for element in row]
    
    def decrypt(key, ciphertext, sbox_type):

        blocks = []

        for ciphertext_block in split_blocks(ciphertext):
            block = AES.decrypt_block(key,ciphertext_block,sbox_type)
            blocks.append(block)

        return [element for row in blocks for element in row]  
