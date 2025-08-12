# This file contains the leakage model for the ASCON cipher, 
# specifically for the first round permutation.

import numpy as np

def ascon_leakage_model(nonce_MSB, nonce_LSB, state_register_index, bit_index):
    """
    This function computes the leakage model for the ASCON cipher.
    The attack point is the activity of the register at the 
    linear diffusion layer output (not at the S-box output).
    Since 3 bits of the key are leaked, the leakage model returns
    8 possible key guesses for the given nonce, as numpy array.
    Each element corresponds to a possible key guess, in the correct order
    (e.g. the triplet (0,0,0) is the element at index 0,
    the triplet (0,0,1) is the element at index 1,
    the triplet (0,1,0) is the element at index 2,
    the triplet (0,1,1) is the element at index 3,
    and so on).
    Each element of the array is actually just a bit, representing the
    expected bit of the linearly diffusion layer output register.

    Inputs:
        nonce_MSB (int): The most significant half of the nonce used for the ASCON cipher, 
        in hexadecimal format, correspondig to the register x3.
        
        nonce_LSB (int): The least significant half of the nonce used for the ASCON cipher, 
        in hexadecimal format, correspondig to the register x4.
        
        state_register_index (int): The ASCON state register attacked (0 or 1).
        
        bit_index (int): The index of the output register bit to be attacked (0 to 63).
        
        debug (bool):   If True, prints the state registers before and after the 
                        first round permutation.
    Returns:
        leakage_model (numpy array): The leakage model for the ASCON cipher.
    """

    # Check if the state register is valid for the attack
    if state_register_index not in [0, 1]:
        raise ValueError("Invalid state register for the attack. " \
        "Must be register 0 or 1.")
    
    # Check if the bit index is valid (0 to 63)
    if not (0 <= bit_index < 64):
        raise ValueError("Invalid bit index for the attack. " \
        "Must be between 0 and 63.")

    # Initialize the leakage model as an empty numpy array
    leakage_model = np.empty(8, dtype=np.uint8)

    # Loop through all possible key guesses (from 0 to 7, which corresponds 
    # to the triplets (0,0,0) to (1,1,1)).
    # Each key guess is represented by a 3-bit binary number:
    # b2 (MSB), b1, and b0 (LSB).
    for key_guess in range(8):
        k_2 = (key_guess >> 2) & 1
        k_1 = (key_guess >> 1) & 1
        k_0 = key_guess & 1

        # Compute the expected value of the linear diffusion layer output
        if state_register_index == 0:
            # Extract the 3 bits of both nonce halves that are relevant for the attack.
            # The bits are extracted from the nonce using bitwise operations (right shift
            # by a modulo-64 "bit_index" amount and then bitwise AND).
            # The notation "nonce_MSB_j" means the j-th bit of the first nonce half,
            # "nonce_MSB_j36" means the (j+36)-th bit of the first nonce half,
            # and "nonce_MSB_j45" means the (j+45)-th bit of the first nonce half.
            # The same applies to the second nonce half

            nonce_MSB_j   = (int(nonce_MSB) >> (bit_index % 64)) & 1
            nonce_MSB_j36 = (int(nonce_MSB) >> ((bit_index + 36) % 64)) & 1
            nonce_MSB_j45 = (int(nonce_MSB) >> ((bit_index + 45) % 64)) & 1

            nonce_LSB_j   = (int(nonce_LSB) >> (bit_index % 64)) & 1
            nonce_LSB_j36 = (int(nonce_LSB) >> ((bit_index + 36) % 64)) & 1
            nonce_LSB_j45 = (int(nonce_LSB) >> ((bit_index + 45) % 64)) & 1
            
            z0_j =  (k_0 & (nonce_LSB_j   ^ 1) ^ nonce_MSB_j)   ^ \
                    (k_1 & (nonce_LSB_j36 ^ 1) ^ nonce_MSB_j36) ^ \
                    (k_2 & (nonce_LSB_j45 ^ 1) ^ nonce_MSB_j45)
            
            leakage_model[key_guess] = z0_j
            
        else:
            # NOTE: For the register 1, the recovered key bits are actually 
            # k01_j = k0_j ^ k1_j, where k0_j is a bit of the key register 0.
            # Since the key register 0 is fully recovered from the previous case,
            # the key bit k1_j can be computed as k1_j = k01_j ^ k0_j.
            nonce_MSB_j   = (int(nonce_MSB) >> (bit_index % 64)) & 1
            nonce_MSB_j3  = (int(nonce_MSB) >> ((bit_index + 3) % 64)) & 1
            nonce_MSB_j25 = (int(nonce_MSB) >> ((bit_index + 25) % 64)) & 1

            nonce_LSB_j   = (int(nonce_LSB) >> (bit_index % 64)) & 1
            nonce_LSB_j3  = (int(nonce_LSB) >> ((bit_index + 3) % 64)) & 1
            nonce_LSB_j25 = (int(nonce_LSB) >> ((bit_index + 25) % 64)) & 1

            z1_j =  (nonce_MSB_j   & (k_0 ^ 1) ^ nonce_LSB_j)  ^ \
                    (nonce_MSB_j3  & (k_1 ^ 1) ^ nonce_LSB_j3) ^ \
                    (nonce_MSB_j25 & (k_2 ^ 1) ^ nonce_LSB_j25)
            
            leakage_model[key_guess] = z1_j

    return leakage_model
