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
from AES_operation import invKeyExpansion as invKeyExpansion

class AES:
    
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
    
    def decrypt(key, ciphertext, sbox_type):

        blocks = []

        for ciphertext_block in split_blocks(ciphertext):
            block = AES.decrypt_block(key,ciphertext_block,sbox_type)
            blocks.append(block)

        return [element for row in blocks for element in row]  
    
    def encrypt_block(key,plaintext,sbox_type, verbose=False):

        plain_state = bytes2matrix(plaintext)
        round_keys = KeyExpansion(sbox_type,key)
        
        if verbose:
            file_name = "./verbose/AES_execution_" + sbox_type + ".txt"
            print_file = open(file_name,'w')
        
            print("Round keys:", file=print_file)
            for key in round_keys:
                line = ""
                for subkey in key:
                    for text in subkey:
                        byte = text
                        line = line + format(byte, "02x")
                print(line, file=print_file)
            print("", file=print_file)

        #Initial round
        AddRoundKey(plain_state, round_keys[0])
        if verbose:
            print("Initial round:", file=print_file)
            line = ""
            for subtext in plain_state:
                for text in subtext:
                    byte = text
                    line = line + format(byte, "02x") 
            print("Add Round Key. Plain state ", line, file=print_file)
            print("", file=print_file)

        #Intermediate rounds
        for i in range(1,10):
            SubBytes(sbox_type,plain_state)
            if verbose:
                print("Round " + str(i), file=print_file)
                line = ""
                for subtext in plain_state:
                    for text in subtext:
                        byte = text
                        line = line + format(byte, "02x") 
                print("Sub Bytes. Plain state ", line, file=print_file)
                print("", file=print_file)
                
            plain_state = ShiftRows(plain_state)
            if verbose:
                line = ""
                for subtext in plain_state:
                    for text in subtext:
                        byte = text
                        line = line + format(byte, "02x") 
                print("Shift Rows. Plain state ", line, file=print_file)
                print("", file=print_file)
            
            plain_state = MixColumns(plain_state)
            if verbose:
                line = ""
                for subtext in plain_state:
                    for text in subtext:
                        byte = text
                        line = line + format(byte, "02x") 
                print("Mix Columns. Plain state ", line, file=print_file)
                print("", file=print_file)
            
            AddRoundKey(plain_state,round_keys[i])
            if verbose:
                line = ""
                for subtext in plain_state:
                    for text in subtext:
                        byte = text
                        line = line + format(byte, "02x") 
                print("Add Round Key. Plain state ", line, file=print_file)
                print("", file=print_file)

        #Final round
        SubBytes(sbox_type,plain_state)
        if verbose:
            print("Round 10", file=print_file)
            line = ""
            for subtext in plain_state:
                for text in subtext:
                    byte = text
                    line = line + format(byte, "02x") 
            print("Sub bytes. Plain state ", line, file=print_file)
            print("", file=print_file)
        
        plain_state = ShiftRows(plain_state)
        if verbose:
            line = ""
            for subtext in plain_state:
                for text in subtext:
                    byte = text
                    line = line + format(byte, "02x") 
            print("Shift Rows. Plain state ", line, file=print_file)
            print("", file=print_file)
        
        AddRoundKey(plain_state,round_keys[10])
        if verbose:
            line = ""
            for subtext in plain_state:
                for text in subtext:
                    byte = text
                    line = line + format(byte, "02x") 
            print("Add Round Key. Plain state ", line, file=print_file)
            print("", file=print_file)

        return matrix2bytes(plain_state)
    
    def encrypt(key, plaintext, sbox_type, verbose=False):

        blocks = []

        for plaintext_block in split_blocks(plaintext):
            block = AES.encrypt_block(key,plaintext_block,sbox_type, verbose)
            blocks.append(block)

        return [element for row in blocks for element in row]
    
    def get_round_key(key, round, sbox_type):
        
        if round < 0 and round > 10:
            print("Unexpected value for round value")
            return
        
        round_keys = KeyExpansion(sbox_type,key)

        return [byte for subbytes in round_keys[round] for byte in subbytes]
    
    def get_initial_key(key, round, sbox_type):  
        initial_key = []
        temp = invKeyExpansion(bytes(key), round, sbox_type)
        for element in temp:
            initial_key.append(element)
        return initial_key

        
