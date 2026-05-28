# This file contains the leakage model for the ASCON cipher,
# specifically for the first round permutation.

from functools import lru_cache
import os
import numpy as np

from .. import ascon_funcs as ascon

try:
    import cupy as cp
except Exception:
    cp = None


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------

def _gpu_available():
    if cp is None:
        return False
    try:
        return cp.cuda.runtime.getDeviceCount() > 0
    except Exception:
        return False


def _select_array_backend(backend="cpu"):
    """
    Select NumPy or CuPy backend.

    backend:
      cpu  -> NumPy
      gpu  -> CuPy if available, otherwise NumPy
      auto -> CuPy if available, otherwise NumPy

    Environment fallback:
      ASCON_LEAKAGE_DEVICE=cpu|gpu|auto
    """
    if backend is None:
        backend = os.environ.get("ASCON_LEAKAGE_DEVICE", "cpu")

    backend = str(backend).strip().lower()

    if backend == "cpu":
        return np

    if backend == "gpu":
        return cp if _gpu_available() else np

    if backend == "auto":
        return cp if _gpu_available() else np

    raise ValueError("backend must be one of: cpu, gpu, auto")


# ---------------------------------------------------------------------------
# Cached constants
# ---------------------------------------------------------------------------

@lru_cache(maxsize=None)
def _get_sbox_lut(sbox_type):
    """
    Return ASCON S-box LUT for the selected implementation.

    Shape:
        (32,)
    """
    return np.array([ascon.sbox(sbox_type, i) for i in range(32)], dtype=np.uint8)


@lru_cache(maxsize=None)
def _get_key_hypothesis_bits():
    """
    Return the 6-bit key hypotheses split into local k0 and k1 bits.

    Hypothesis index:
        hyp = [k1_2 k1_1 k1_0 k0_2 k0_1 k0_0]

    Returns
    -------
    key_guess_0:
        shape (64, 3)

    key_guess_1:
        shape (64, 3)
    """
    guesses = np.arange(64, dtype=np.uint8)

    key_guess_0 = (
        (guesses[:, None] >> np.array([2, 1, 0], dtype=np.uint8)) & 0x01
    ).astype(np.uint8)

    key_guess_1 = (
        (guesses[:, None] >> np.array([5, 4, 3], dtype=np.uint8)) & 0x01
    ).astype(np.uint8)

    return key_guess_0, key_guess_1


@lru_cache(maxsize=None)
def _get_target_description(attacked_state_reg, attacked_bit):
    """
    Return target-specific row shifts and output-bit position.

    The three shifted bit positions define which key-bit triplet contributes
    to the selected target bit.
    """
    row_shift_map = {
        "x0": ((0, 19, 28), 4),
        "x1": ((0, 61, 39), 3),
        "x2": ((0, 1, 6), 2),
        "x3": ((0, 10, 17), 1),
        "x4": ((0, 7, 41), 0),
    }

    if attacked_state_reg not in row_shift_map:
        raise ValueError(
            'Invalid attacked_state_reg. Must be one of {"x0", "x1", "x2", "x3", "x4"}.'
        )

    attacked_bit = int(attacked_bit)

    if not (0 <= attacked_bit < 64):
        raise ValueError("Invalid bit index for the attack. Must be between 0 and 63.")

    row_shift_vec, output_bit_pos = row_shift_map[attacked_state_reg]
    shifts = tuple((attacked_bit + rs) % 64 for rs in row_shift_vec)

    return row_shift_vec, output_bit_pos, shifts


# ---------------------------------------------------------------------------
# Core leakage matrix implementation
# ---------------------------------------------------------------------------

def _compute_leakage_matrix_impl(
    init_vect,
    nonce_MSB,
    nonce_LSB,
    attacked_state_reg,
    attacked_bit,
    sbox_type,
    backend="cpu",
):
    """
    Vectorized leakage computation.

    Returns
    -------
    leakage:
        shape (N, 64), dtype uint8

    where:
        N  = number of nonces
        64 = number of 6-bit key hypotheses
    """
    xp = _select_array_backend(backend)

    _, output_bit_pos, shifts = _get_target_description(
        attacked_state_reg,
        attacked_bit,
    )

    sbox_lut = _get_sbox_lut(sbox_type)
    key_guess_0, key_guess_1 = _get_key_hypothesis_bits()

    nonce_MSB = xp.asarray(nonce_MSB)
    nonce_LSB = xp.asarray(nonce_LSB)

    if nonce_MSB.ndim == 0:
        nonce_MSB = nonce_MSB[None]

    if nonce_LSB.ndim == 0:
        nonce_LSB = nonce_LSB[None]

    if nonce_MSB.shape[0] != nonce_LSB.shape[0]:
        raise ValueError(
            f"nonce_MSB and nonce_LSB length mismatch: "
            f"{nonce_MSB.shape[0]} vs {nonce_LSB.shape[0]}"
        )

    shifts_arr = xp.asarray(shifts, dtype=xp.uint64)

    x0_bits = xp.asarray(
        [(int(init_vect) >> int(shift)) & 0x01 for shift in shifts],
        dtype=xp.uint8,
    )

    round_constant_bits = xp.asarray(
        [(0xF0 >> int(shift)) & 0x01 for shift in shifts],
        dtype=xp.uint8,
    )

    nonce_msb_bits = (
        (nonce_MSB[:, None].astype(xp.uint64) >> shifts_arr) & xp.uint64(1)
    ).astype(xp.uint8)

    nonce_lsb_bits = (
        (nonce_LSB[:, None].astype(xp.uint64) >> shifts_arr) & xp.uint64(1)
    ).astype(xp.uint8)

    lut = xp.asarray(sbox_lut, dtype=xp.uint8)
    key0 = xp.asarray(key_guess_0, dtype=xp.uint8)
    key1 = xp.asarray(key_guess_1, dtype=xp.uint8)

    n = nonce_MSB.shape[0]

    z = xp.zeros((n, 64), dtype=xp.uint8)

    for local_pos in range(3):
        sbox_input = (
            (x0_bits[local_pos] << 4)
            | (key0[:, local_pos][None, :] << 3)
            | ((key1[:, local_pos][None, :] ^ round_constant_bits[local_pos]) << 2)
            | (nonce_msb_bits[:, local_pos][:, None] << 1)
            | nonce_lsb_bits[:, local_pos][:, None]
        )

        z ^= lut[sbox_input]

    leakage = ((z >> output_bit_pos) & 0x01).astype(xp.uint8)

    if xp is cp:
        leakage = cp.asnumpy(leakage)

    return leakage


# ---------------------------------------------------------------------------
# Public APIs
# ---------------------------------------------------------------------------

def ascon_generic_leakage_matrix(
    init_vect,
    nonce_MSB,
    nonce_LSB,
    attacked_state_reg,
    attacked_bit,
    sbox_type,
    backend="cpu",
):
    """
    Vectorized generic leakage model for a batch of nonces.

    Parameters
    ----------
    init_vect:
        ASCON initialization vector / x0 initial value.

    nonce_MSB:
        array-like, shape (N,)

    nonce_LSB:
        array-like, shape (N,)

    attacked_state_reg:
        "x0", "x1", "x2", "x3", or "x4"

    attacked_bit:
        integer 0..63

    sbox_type:
        selected S-box implementation.

    backend:
        cpu | gpu | auto

    Returns
    -------
    np.ndarray:
        shape (N, 64), dtype uint8
    """
    return _compute_leakage_matrix_impl(
        init_vect,
        nonce_MSB,
        nonce_LSB,
        attacked_state_reg,
        attacked_bit,
        sbox_type,
        backend=backend,
    )


def ascon_generic_leakage_model(
    init_vect,
    nonce_MSB,
    nonce_LSB,
    attacked_state_reg,
    attacked_bit,
    sbox_type,
):
    """
    Single-nonce leakage model.

    Returns
    -------
    np.ndarray:
        shape (64,), dtype uint8
    """
    return _compute_leakage_matrix_impl(
        init_vect,
        nonce_MSB,
        nonce_LSB,
        attacked_state_reg,
        attacked_bit,
        sbox_type,
        backend="cpu",
    )[0]