from AES_operation import SubBytes, InvSubBytes, ShiftRows, InvShiftRows, MixColumns, InvMixColumns, AddRoundKey, KeyExpansion, bytes2matrix, matrix2bytes, split_blocks    
class AES_golden_model:

    def __init__(self):
        pass

    def encrypt_block(key,plaintext,sbox_type):
        """Perform AES encryption on a single block of data.

        Args:
            key (str): Key used for the encryption, size of 16 bytes.
            plaintext (int): Plaintext block to encrypt, size of 16 bytes.
            sbox_type (str): Type of Sbox to use.

        Returns:
            int: Encrypted block of data.
        """
        plain_state = bytes2matrix(plaintext)
        round_keys = KeyExpansion(sbox_type,key)

        #Initial round
        AddRoundKey(plain_state, round_keys[0])

        #Intermediate rounds
        for i in range(1,10):
            SubBytes(sbox_type,plain_state)
            plain_state = ShiftRows(plain_state)
            plain_state = MixColumns(plain_state)
            AddRoundKey(plain_state,round_keys[i])

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
    
    def encrypt(self, key, plaintext, sbox_type):
        """Perform AES encryption 
        Args:
            key (str): Key used for the encryption, size of 16 bytes.
            plaintext (int): Plaintext to encrypt as list of bytes.
            sbox_type (str): Type of Sbox to use.

        Returns:
            int: Encrypted data returned as list of bytes.
        """
        blocks = []

        for plaintext_block in split_blocks(plaintext):
            block = AES_golden_model.encrypt_block(key,plaintext_block,sbox_type)
            blocks.append(block)

        return [element for row in blocks for element in row]
    
    def decrypt(self, key, ciphertext, sbox_type):
        """Perform AES decryption

        Args:
            key (str): Key used for the encryption, size of 16 bytes.
            ciphertext (int): Ciphertext to decrypt as list of bytes.
            sbox_type (str): Type of Sbox to use.

        Returns:
            int: Decrypted data returned as list of bytes.
        """
        blocks = []

        for ciphertext_block in split_blocks(ciphertext):
            block = AES_golden_model.decrypt_block(key,ciphertext_block,sbox_type)
            blocks.append(block)

        return [element for row in blocks for element in row]  
