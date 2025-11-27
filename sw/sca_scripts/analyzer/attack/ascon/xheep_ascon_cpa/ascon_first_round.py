# The permutation function is imported from operations_init.py, 
# which is located inside the sw/ciphers/ASCON_init_python directory.
import sys
import os
sys.path.append(os.path.abspath
                (os.path.join
                 (os.path.dirname(__file__), 
                  '../../../../../ciphers/ASCON_init_python')))
from operations_init import permutation



def ascon_first_round(key, nonce, sbox_type, debug=False):
    """
    This function performs the first round permutation using the combinatorial S-box.
    The ASCON state is first initialized with the initialization vector, key, and nonce.
    Then the first round permutation is applied to the state registers.

    Inputs:
        key (int): The key used for the ASCON cipher, in hexadecimal format.
        nonce (int): The nonce used for the ASCON cipher, in hexadecimal format.
        sbox_type (str): The type of S-box to use for the permutation. Options are "lut_ascon", "lut_bilgin", "lut_allouzi", "lut_lu_4", "lut_lu_5", "lut_lu_6", "lut_lu_7".
        debug (bool): If True, prints the state registers before and after the first round permutation.
    Returns:
        S (list): The state registers after the first round permutation.
    """

    # Initialize the ASCON 128A parameters (taken from the ASCON C implementation).
    # ASCON_128A_IV is a constant that represents the initialization vector for ASCON-128a
    ASCON_AEAD_VARIANT = 1
    ASCON_PA_ROUNDS = 12
    ASCON_128A_PB_ROUNDS = 8
    ASCON_TAG_SIZE = 16
    ASCON_128A_RATE = 16

    ASCON_128A_IV = (
        (ASCON_AEAD_VARIANT << 0) |
        (ASCON_PA_ROUNDS << 16) |
        (ASCON_128A_PB_ROUNDS << 20) |
        ((ASCON_TAG_SIZE * 8) << 24) |
        (ASCON_128A_RATE << 40)
    )

    # Initialize the state as a list of 5 registers
    S = [0, 0, 0, 0, 0]

    # Load the state registers
    S[0] = ASCON_128A_IV
    S[1] = key & 0xFFFFFFFFFFFFFFFF           # Most significant 64 bits of the key (little-endian)
    S[2] = (key >> 64) & 0xFFFFFFFFFFFFFFFF   # Least significant 64 bits of the key
    S[3] = nonce & 0xFFFFFFFFFFFFFFFF         # Most significant 64 bits of the nonce
    S[4] = (nonce >> 64) & 0xFFFFFFFFFFFFFFFF # Least significant 64 bits of the nonce

    if debug:
        # DEBUG: Print the state registers after the first round permutation
        print("ASCON initial state registers:")
        print("S[0]: 0x{:016X}".format(S[0]))
        print("S[1]: 0x{:016X}".format(S[1]))
        print("S[2]: 0x{:016X}".format(S[2]))
        print("S[3]: 0x{:016X}".format(S[3]))
        print("S[4]: 0x{:016X}".format(S[4]))

    # Perform the first round permutation using the combinatorial S-box
    permutation(S=S, r=0, mode=sbox_type)

    if debug:
        # DEBUG: Print the state registers after the first round permutation
        print("ASCON first round permutation state registers:")
        print("S[0]: 0x{:016X}".format(S[0]))
        print("S[1]: 0x{:016X}".format(S[1]))
        print("S[2]: 0x{:016X}".format(S[2]))
        print("S[3]: 0x{:016X}".format(S[3]))
        print("S[4]: 0x{:016X}".format(S[4]))

    return S
