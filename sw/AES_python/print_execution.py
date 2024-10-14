from AES import AES as AES # type: ignore
import numpy as np

plaintext_initial = "0ac658e10c0bfac72d7c5870bd8ad78f"
key       = "2b7e151628aed2a6abf7158809cf4f3c"

plaintext = [plaintext_initial[i:i+2] for i in range(0, len(plaintext_initial), 2)]
plaintext = ['0x' + element for element in plaintext]
plaintext = [int(s, 16) for s in plaintext]

ciphertext = AES.encrypt(key, plaintext, "sbox_ozkaynak_1", False)