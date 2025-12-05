# This file contains the leakage model for the ASCON cipher, 
# specifically for the first round permutation.
from .. import ascon_funcs as ascon
import numpy as np

def ascon_generic_leakage_model(init_vect,
                                nonce_MSB,
                                nonce_LSB,
                                attacked_state_reg,
                                attacked_bit,
                                sbox_type):
    """
    Compute the leakage model for ASCON in the first round permutation.
    The attack point is the activity of one output bit of the linear
    diffusion layer (after the S-box + linear layer), modeled as its
    Hamming weight (0 or 1).

    The model assumes 6 key bits influence the targeted bit
    (3 from the MS half, 3 from the LS half), so it evaluates all
    2^6 = 64 key hypotheses and returns a 64-entry vector.

    Inputs:
        init_vect (int): Initialization vector (register x0 at start).
        nonce_MSB (int): Most significant half of the nonce (register x3).
        nonce_LSB (int): Least significant half of the nonce (register x4).
        attacked_state_reg (str): Attacked ASCON state register:
            "x0", "x1", "x2", "x3", or "x4".
        attacked_bit (int): Bit index of the attacked state bit (0..63).
        sbox_type (str): Identifier of the S-box implementation.

    Returns:
        leakage_model (np.ndarray): Shape (64,), leakage_model[k] ∈ {0,1}
        is the predicted bit/Hamming weight of the attacked output bit
        for key hypothesis k (0..63).
    """

    def ascon_substitution_layer(x0, x1, x2, x3, x4,
                                 round_constant,
                                 row_shift,
                                 bitindex,
                                 sbox_type):
        """
        Compute the 5-bit S-box output for a single "row" (bit position).
        """
        # Extract the target bit from each register. Round constant is
        # added on x2 in this bit-slice formulation.
        shift = (bitindex + row_shift) % 64

        x0_bit = (int(x0) >> shift) & 0x01
        x1_bit = x1
        x2_bit = x2 ^ ((round_constant >> shift) & 0x01)
        x3_bit = (int(x3) >> shift) & 0x01
        x4_bit = (int(x4) >> shift) & 0x01

        # Build the 5-bit S-box input vector
        sbox_input = (
            (x0_bit << 4) |
            (x1_bit << 3) |
            (x2_bit << 2) |
            (x3_bit << 1) |
            x4_bit
        )

        return ascon.sbox(sbox_type, sbox_input)

    def ascon_shift_layer(init_vect,
                          key_0,
                          key_1,
                          nonce_0,
                          nonce_1,
                          round_constant,
                          row_shift,
                          bitindex,
                          sbox_type):
        """
        Compute the 5-bit output of the ASCON linear shift layer.
        """
        S0 = ascon_substitution_layer(init_vect, key_0[0], key_1[0], nonce_0, nonce_1, round_constant, row_shift[0], bitindex, sbox_type) ^ \
             ascon_substitution_layer(init_vect, key_0[1], key_1[1], nonce_0, nonce_1, round_constant, row_shift[1], bitindex, sbox_type) ^ \
             ascon_substitution_layer(init_vect, key_0[2], key_1[2], nonce_0, nonce_1, round_constant, row_shift[2], bitindex, sbox_type)

        return S0

    def split_6bit_to_lists(value):
        """
        Split a 6-bit integer into a list of 6 bits [b5, b4, b3, b2, b1, b0].
        """
        bits = f"{value:06b}"
        return [int(b) for b in bits]

    # ------------------------------------------------------------------
    # Sanity checks
    # ------------------------------------------------------------------
    if attacked_state_reg not in ("x0", "x1", "x2", "x3", "x4"):
        raise ValueError(
            "Invalid attacked_state_reg. Must be one of "
            '{"x0", "x1", "x2", "x3", "x4"}.'
        )

    if not (0 <= attacked_bit < 64):
        raise ValueError(
            "Invalid bit index for the attack. Must be between 0 and 63."
        )

    # ------------------------------------------------------------------
    # Row shifts and output-bit selection per attacked register
    # ------------------------------------------------------------------
    # Row shift values for the ASCON cipher
    row_shift_0 = [0, 19, 28]   # x0
    row_shift_1 = [0, 61, 39]   # x1
    row_shift_2 = [0, 1, 6]     # x2
    row_shift_3 = [0, 10, 17]   # x3
    row_shift_4 = [0, 7, 41]    # x4

    if attacked_state_reg == "x0":
        row_shift_vec = row_shift_0
        output_bit_pos = 4
    elif attacked_state_reg == "x1":
        row_shift_vec = row_shift_1
        output_bit_pos = 3
    elif attacked_state_reg == "x2":
        row_shift_vec = row_shift_2
        output_bit_pos = 2
    elif attacked_state_reg == "x3":
        row_shift_vec = row_shift_3
        output_bit_pos = 1
    elif attacked_state_reg == "x4":
        row_shift_vec = row_shift_4
        output_bit_pos = 0
    else :
        raise ValueError("Invalid attacked_state_reg value.")

    # ------------------------------------------------------------------
    # Leakage model over all 2^6 = 64 key hypotheses
    # ------------------------------------------------------------------
    leakage_model = np.empty(64, dtype=np.uint8)

    # Round constant for the first permutation round
    round_constant = 0xF0

    # Loop through all possible key guesses (0..63).
    # Each key guess is a 6-bit value: 3 bits for key_0, 3 bits for key_1.
    for key_guess in range(64):
        key_guess_list = split_6bit_to_lists(key_guess)
        key_guess_0 = key_guess_list[:3]   # 3 bits from MS half
        key_guess_1 = key_guess_list[3:]   # 3 bits from LS half

        # Compute the 5-bit output of the diffusion layer
        Z = ascon_shift_layer(
            init_vect,
            key_guess_0,
            key_guess_1,
            nonce_MSB,
            nonce_LSB,
            round_constant,
            row_shift_vec,
            attacked_bit,
            sbox_type,
        )

        # Extract the attacked output bit (as Hamming weight 0/1)
        Z_hw = (Z >> output_bit_pos) & 0x01
        leakage_model[key_guess] = Z_hw

    return leakage_model
