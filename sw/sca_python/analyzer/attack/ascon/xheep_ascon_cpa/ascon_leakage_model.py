# This file contains the leakage model for the ASCON cipher, 
# specifically for the first round permutation.

import numpy as np

def ascon_leakage_model(nonce_MSB, state_register_index, bit_index, debug=False):
    nonce_MSB_j = (int(nonce_MSB) >> (bit_index % 64)) & 1

    # Initialize the leakage model as an empty numpy array
    leakage_model = np.empty(2, dtype=np.uint8)

    for i in range(2): # Loop over 2 possible values (0 and 1)
        if state_register_index == 3:
            leakage_model[i] = (nonce_MSB_j ^ i)

    return leakage_model
