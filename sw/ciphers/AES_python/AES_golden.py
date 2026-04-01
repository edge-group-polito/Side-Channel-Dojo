"""
AES_golden_model.py

This module implements a software "golden model" of AES-128 encryption and
decryption, used as a functional reference for hardware implementations

Main features:
    - Block-level AES-128 encrypt/decrypt (single 16-byte block)
    - Streaming encrypt/decrypt over arbitrary-length data (split into 16-byte blocks)
    - Pluggable S-box implementation via the `sbox_type` argument, to match
      different AES S-box variants used in hardware
    - Optional debug tracing controlled by DEBUG_LEVEL:
        DEBUG_LEVEL = 0 : no debug output
        DEBUG_LEVEL = 1 : round-level state and key information (hex)
        DEBUG_LEVEL > 1 : additional SubBytes-level state (hex)

Typical usage example (ChipWhisperer context):

    cipher = AES_golden_model()
    formatted_key = "".join(f"{b:02x}" for b in key_bytes)  # 16-byte key → 32 hex chars
    formatted_pt  = (f"{b:02x}" for b in pt_bytes)
    text          = [int(x, 16) for x in formatted_pt]

    ct = cipher.encrypt(formatted_key, text, sbox_type="sbox_rijandael", DEBUG_LEVEL=1)
"""

from AES_operation import (
    SubBytes,
    InvSubBytes,
    ShiftRows,
    InvShiftRows,
    MixColumns,
    InvMixColumns,
    AddRoundKey,
    KeyExpansion,
    bytes2matrix,
    matrix2bytes,
    split_blocks,
)
import copy


def format_matrix_hex(mat):
    """Return a pretty hex string representation of a 4x4 AES state/round key."""
    lines = []
    for row in mat:
        line = "[ " + " ".join(f"{b:02x}" for b in row) + " ]"
        lines.append(line)
    return "\n".join(lines)


class AES_golden_model:
    def __init__(self):
        pass

    @staticmethod
    def encrypt_block(key, plaintext, sbox_type, DEBUG_LEVEL=0):
        """Perform AES encryption on a single 16-byte block.

        Args:
            key (str): Encryption key as hex string (32 hex chars for AES-128).
            plaintext (list[int]): Plaintext block (16 bytes: list of ints 0..255).
            sbox_type (str): Type of S-box to use.
            DEBUG_LEVEL (int): Verbosity level for debug prints.

        Returns:
            list[int]: Encrypted block (16 bytes as list of ints).
        """
        plain_state = bytes2matrix(plaintext)
        round_keys = KeyExpansion(sbox_type, key)

        if DEBUG_LEVEL > 0:
            print("=== AES ENCRYPT BLOCK ===")
            print("S-box type:", sbox_type)
            print("Round 0 key (hex):")
            print(format_matrix_hex(round_keys[0]))
            print("Initial state (hex):")
            print(format_matrix_hex(plain_state))

        # Initial round
        AddRoundKey(plain_state, round_keys[0])
        if DEBUG_LEVEL > 0:
            print("\nAfter initial AddRoundKey (hex):")
            print(format_matrix_hex(plain_state))

        # Intermediate rounds 1..9
        for i in range(1, 10):
            SubBytes(sbox_type, plain_state)
            if DEBUG_LEVEL > 1:
                print(f"\nAfter SubBytes (round {i}) (hex):")
                print(format_matrix_hex(plain_state))

            plain_state = ShiftRows(plain_state)
            plain_state = MixColumns(plain_state)
            AddRoundKey(plain_state, round_keys[i])

            if DEBUG_LEVEL > 0:
                print(f"\nAfter round {i} (hex):")
                print(format_matrix_hex(plain_state))

        # Final round (no MixColumns)
        SubBytes(sbox_type, plain_state)
        plain_state = ShiftRows(plain_state)
        AddRoundKey(plain_state, round_keys[10])

        if DEBUG_LEVEL > 0:
            print("\nAfter final round (hex):")
            print(format_matrix_hex(plain_state))
            print("=== END ENCRYPT BLOCK ===\n")

        return matrix2bytes(plain_state)

    @staticmethod
    def decrypt_block(key, ciphertext, sbox_type, DEBUG_LEVEL=0):
        """Perform AES decryption on a single 16-byte block.

        Args:
            key (str): Encryption key as hex string (32 hex chars for AES-128).
            ciphertext (list[int]): Ciphertext block (16 bytes: list of ints 0..255).
            sbox_type (str): Type of S-box to use.
            DEBUG_LEVEL (int): Verbosity level for debug prints.

        Returns:
            list[int]: Decrypted block (16 bytes as list of ints).
        """
        cipher_state = bytes2matrix(ciphertext)
        round_keys = KeyExpansion(sbox_type, key)

        if DEBUG_LEVEL > 0:
            print("=== AES DECRYPT BLOCK ===")
            print("S-box type:", sbox_type)
            print("Initial cipher state (hex):")
            print(format_matrix_hex(cipher_state))
            print("Round 10 key (hex):")
            print(format_matrix_hex(round_keys[10]))

        # Initial inverse round (round 10)
        AddRoundKey(cipher_state, round_keys[10])
        cipher_state = InvShiftRows(cipher_state)
        InvSubBytes(sbox_type, cipher_state)

        if DEBUG_LEVEL > 0:
            print("\nAfter initial inverse round (10) (hex):")
            print(format_matrix_hex(cipher_state))

        # Intermediate rounds 9..1
        for i in range(9, 0, -1):
            AddRoundKey(cipher_state, round_keys[i])
            cipher_state = InvMixColumns(cipher_state)
            cipher_state = InvShiftRows(cipher_state)
            InvSubBytes(sbox_type, cipher_state)

            if DEBUG_LEVEL > 0:
                print(f"\nAfter inverse round {i} (hex):")
                print(format_matrix_hex(cipher_state))

        # Final inverse AddRoundKey (round 0)
        AddRoundKey(cipher_state, round_keys[0])

        if DEBUG_LEVEL > 0:
            print("\nAfter final AddRoundKey (round 0) (hex):")
            print(format_matrix_hex(cipher_state))
            print("=== END DECRYPT BLOCK ===\n")

        return matrix2bytes(cipher_state)

    def encrypt(self, key, plaintext, sbox_type, DEBUG_LEVEL=0):
        """Perform AES encryption on arbitrary-length plaintext.

        Args:
            key (str): Encryption key as hex string (32 hex chars for AES-128).
            plaintext (list[int]): Plaintext to encrypt as list of bytes.
            sbox_type (str): Type of S-box to use.
            DEBUG_LEVEL (int): Verbosity level for debug prints.

        Returns:
            list[int]: Encrypted data as flat list of bytes.
        """
        blocks = []

        for block_idx, plaintext_block in enumerate(split_blocks(plaintext)):
            if DEBUG_LEVEL > 0:
                print(f"\n>>> Encrypting block {block_idx}")
            block = AES_golden_model.encrypt_block(
                key, plaintext_block, sbox_type, DEBUG_LEVEL=DEBUG_LEVEL
            )
            blocks.append(block)

        return [element for row in blocks for element in row]

    def decrypt(self, key, ciphertext, sbox_type, DEBUG_LEVEL=0):
        """Perform AES decryption on arbitrary-length ciphertext.

        Args:
            key (str): Encryption key as hex string (32 hex chars for AES-128).
            ciphertext (list[int]): Ciphertext to decrypt as list of bytes.
            sbox_type (str): Type of S-box to use.
            DEBUG_LEVEL (int): Verbosity level for debug prints.

        Returns:
            list[int]: Decrypted data as flat list of bytes.
        """
        blocks = []

        for block_idx, ciphertext_block in enumerate(split_blocks(ciphertext)):
            if DEBUG_LEVEL > 0:
                print(f"\n>>> Decrypting block {block_idx}")
            block = AES_golden_model.decrypt_block(
                key, ciphertext_block, sbox_type, DEBUG_LEVEL=DEBUG_LEVEL
            )
            blocks.append(block)

        return [element for row in blocks for element in row]
