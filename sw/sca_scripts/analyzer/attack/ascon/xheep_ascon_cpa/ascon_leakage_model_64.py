# This file contains the leakage model for the ASCON cipher, 
# specifically for the first round permutation.
from .. import ascon_funcs as ascon
import numpy as np

# TODO: FIX the function descriptions. Remove key_0 parameter if not needed anymore.

def ascon_leakage_model(init_vect, nonce_MSB, nonce_LSB, state_register_index, bit_index, sbox_type, key_0=None):
    """
    This function computes the leakage model for the ASCON cipher.
    The attack point is the activity of the register at the 
    linear diffusion layer output (not at the S-box output).
    Since 3 bits of the key are leaked, the leakage model returns
    8 possible key guesses for the given nonce, as numpy array.

    Inputs:
        init_vect (int): The initialization vector used for the ASCON cipher, 
        in hexadecimal format, correspondig to the initial value of the register x0.

        nonce_MSB (int): The most significant half of the nonce used for the ASCON cipher, 
        in hexadecimal format, correspondig to the initial value of the register x3.
        
        nonce_LSB (int): The least significant half of the nonce used for the ASCON cipher, 
        in hexadecimal format, correspondig to the initial value of the register x4.

        state_register_index (int): The ASCON state register attacked (0 or 1).
        
        bit_index (int): The index of the output register bit to be attacked (0 to 63).

        sbox_type (str): The type of S-Box to be used.

        key_0 (int): The most significand half of the key. Used when attacking the state 
        register x1, since it has already been recovered from the state register x0.
    Returns:
        leakage_model (numpy array): The leakage model for the ASCON cipher.
    """

    def ascon_substitution_layer(x0, x1, x2, x3, x4, round_constant, row_shift,  bitindex, sbox_type):
        """
            This function computes the 5-bit S-Box output for the ASCON chipher.
            Inputs:
                x0 (int): The register X0 of the ASCON state. It corresponds to the initialization vector.
                x1 (int): The register X1 of the ASCON state. It corresponds to the most significand half of the key.
                x2 (int): The register X2 of the ASCON state. It corresponds to the least significand half of the key.
                x3 (int): The register X3 of the ASCON state. It corresponds to the most significand half of the nonce.
                x4 (int): The register X4 of the ASCON state. It corresponds to the least significand half of the nonce.
                round_constant (int): The round constant for the ASCON cipher.
                row_shift (list): The row shift values for the ASCON cipher.
                bitindex (int): The bit index to be processed.
                sbox_type (str): The type of S-Box to be used.
            Returns:
                int: The 5-bit S-Box output.
        """
        sbox_input = 0x00

        # The target bit is extracted from each register. Note that the round constant addition is 
        # performed here on the register x2.
        x0_bit = (int(x0) >> ((bitindex + row_shift) % 64)) & 0x01
        x1_bit = x1
        x2_bit = x2 ^ (round_constant >> ((bitindex + row_shift) % 64)) & 0x01
        x3_bit = (int(x3) >> ((bitindex + row_shift) % 64)) & 0x01
        x4_bit = (int(x4) >> ((bitindex + row_shift) % 64)) & 0x01

        # Build the 5-bit S-Box input vector
        sbox_input = (x0_bit << 4) | (x1_bit << 3) | (x2_bit << 2) | (x3_bit << 1) | x4_bit

        return ascon.sbox(sbox_type, sbox_input)

    def ascon_shift_layer(init_vect, key_0, key_1, nonce_0, nonce_1, round_constant, row_shift, bitindex, sbox_type):
        """
            This function computes the 5-bit output of the ASCON linear shift layer.
            Inputs:
                init_vect (int): The initialization vector (IV) for the ASCON cipher.
                key_0 (list): 3 bits of the most significant half of the key (as a list of 3 integers).
                key_1 (list): 3 bits of the least significant half of the key (as a list of 3 integers).
                nonce_0 (int): The most significant half of the nonce.
                nonce_1 (int): The least significant half of the nonce.
                round_constant (int): The round constant for the ASCON cipher.
                row_shift (list): The row shift values for the ASCON cipher.
                bitindex (int): The bit index to be processed.
                sbox_type (str): The type of S-Box to be used.
            Returns:
                int: The 5-bit output of the ASCON linear shift layer.
        """
        S0 = ascon_substitution_layer(init_vect, key_0[0], key_1[0], nonce_0, nonce_1, round_constant, row_shift[0], bitindex, sbox_type) ^ \
             ascon_substitution_layer(init_vect, key_0[1], key_1[1], nonce_0, nonce_1, round_constant, row_shift[1], bitindex, sbox_type) ^ \
             ascon_substitution_layer(init_vect, key_0[2], key_1[2], nonce_0, nonce_1, round_constant, row_shift[2], bitindex, sbox_type)

        return S0
       
    def split_6bit_to_lists(value):
        """
            This function splits a 6-bit integer into a list of 6 elements.
        """
        # Convert to 6-bit binary string
        bits = f"{value:06b}"
        # Convert each half to a list of integers
        return [int(b) for b in bits]

    # Check if the state register is valid for the attack
    if state_register_index not in [0, 1]:
        raise ValueError("Invalid state register for the attack. " \
        "Must be register 0 or 1.")
    
    # Check if the bit index is valid (0 to 63)
    if not (0 <= bit_index < 64):
        raise ValueError("Invalid bit index for the attack. " \
        "Must be between 0 and 63.")

    # Initialize the leakage model as an empty numpy array
    leakage_model = np.empty(64, dtype=np.uint8)

    # Round constant for the first permutation round
    round_constant = 0xf0

    # Row shift values for the ASCON cipher
    row_shift_0 = [0, 19, 28]
    row_shift_1 = [0, 61, 39]

    # Loop through all possible key guesses (from 0 to 63).
    # Each key guess is represented by a 6-bit binary number (e.g 0 -> 000000, 1 -> 000001, 2 -> 000010...)
    for key_guess in range(64):

        key_guess_list = split_6bit_to_lists(key_guess)
        key_guess_0 = key_guess_list[:3]
        key_guess_1 = key_guess_list[3:]

        # Compute the output of the linear diffusion layer (5 bits)
        Z = ascon_shift_layer(init_vect, key_guess_0, key_guess_1, nonce_MSB, nonce_LSB, round_constant, row_shift_0, bit_index, sbox_type)
        Z_0 = (Z >> 4) & 0x01

        leakage_model[key_guess] = Z_0

    return leakage_model
