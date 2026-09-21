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
def _get_equivalent_component_tables(sbox_type):
    """
    Return the equivalent nonce-varying equation for every S-box output.

    For fixed ``iv``, ``k0``, and ``k1``, each Boolean output is represented as:

        y = d + n0*n1*A + n0*B + n1*C

    where ``A``, ``B``, ``C``, and ``d`` are Boolean functions of
    ``(iv, k0, k1)``. The coefficients are derived from the S-box truth table;
    this is equivalent to evaluating the expressions in
    equivalent_ascon_sboxes.txt, without coupling runtime CPA to a doc file.

    Returns
    -------
    np.ndarray:
        shape (5, 8, 4), indexed by:
          [output y0..y4, (iv << 2) | (k0 << 1) | k1, (d, A, B, C)]
    """
    lut = _get_sbox_lut(sbox_type)
    tables = np.zeros((5, 8, 4), dtype=np.uint8)

    for output_index in range(5):
        output_shift = 4 - output_index
        for iv in (0, 1):
            for k0 in (0, 1):
                for k1 in (0, 1):
                    coefficient_index = (iv << 2) | (k0 << 1) | k1

                    def full_component(n1, n0):
                        sbox_input = (
                            (iv << 4)
                            | (k0 << 3)
                            | (k1 << 2)
                            | (n1 << 1)
                            | n0
                        )
                        return (int(lut[sbox_input]) >> output_shift) & 1

                    d = full_component(0, 0)
                    b = full_component(0, 1) ^ d
                    c = full_component(1, 0) ^ d
                    a = full_component(1, 1) ^ d ^ b ^ c
                    tables[output_index, coefficient_index] = (d, a, b, c)

    return tables


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


def _dependency_kind_from_dependencies(dependencies):
    dependencies = tuple(dependencies)
    if dependencies == ("k0",):
        return "k0"
    if dependencies == ("k1",):
        return "k1"
    if set(dependencies) == {"k0", "k1"}:
        return "mixed"
    if not dependencies:
        return "none"
    raise ValueError(f"Unsupported key dependency set: {dependencies!r}")


def _dependency_count(dependency_kind):
    dependency_kind = str(dependency_kind)
    if dependency_kind in {"k0", "k1"}:
        return 8
    if dependency_kind == "mixed":
        return 64
    if dependency_kind == "none":
        return 0
    raise ValueError(f"Unsupported dependency kind: {dependency_kind!r}")


def _coefficient_dependencies_for_iv(coefficients, iv_bit):
    """
    Return which key words affect the nonce-varying coefficients at fixed IV.

    ``coefficients`` has shape ``(8, 3)`` and contains the ``A``, ``B``, and
    ``C`` coefficients indexed by ``(iv << 2) | (k0 << 1) | k1``. The constant
    term ``d`` is intentionally ignored because it is not modulated by nonce.
    """
    iv_bit = int(iv_bit) & 0x01
    dependencies = []

    k0_depends = False
    for k1 in (0, 1):
        index0 = (iv_bit << 2) | (0 << 1) | k1
        index1 = (iv_bit << 2) | (1 << 1) | k1
        if not np.array_equal(coefficients[index0], coefficients[index1]):
            k0_depends = True
            break
    if k0_depends:
        dependencies.append("k0")

    k1_depends = False
    for k0 in (0, 1):
        index0 = (iv_bit << 2) | (k0 << 1) | 0
        index1 = (iv_bit << 2) | (k0 << 1) | 1
        if not np.array_equal(coefficients[index0], coefficients[index1]):
            k1_depends = True
            break
    if k1_depends:
        dependencies.append("k1")

    return tuple(dependencies)


def get_target_key_dependencies(init_vect, attacked_state_reg, attacked_bit, sbox_type):
    """
    Describe the key information available from one attacked output bit.

    Returns a dictionary with:
      - ``key_dependencies``: ``()``, ``("k0",)``, ``("k1",)``, or
        ``("k0", "k1")``
      - ``dependency_kind``: ``none``, ``k0``, ``k1``, or ``mixed``
      - ``n_hypotheses``: 0, 8, or 64

    The decision is made on the three shifted columns feeding the attacked
    linear-layer bit, using the actual IV bit of each column.
    """
    _, output_bit_pos, shifts = _get_target_description(
        attacked_state_reg,
        attacked_bit,
    )
    output_index = 4 - output_bit_pos
    coefficients = _get_equivalent_component_tables(sbox_type)[output_index, :, 1:]

    local_dependencies = []
    dependency_union = set()
    for local_pos, shift in enumerate(shifts):
        iv_bit = (int(init_vect) >> int(shift)) & 0x01
        dependencies = _coefficient_dependencies_for_iv(coefficients, iv_bit)
        local_dependencies.append(
            {
                "local_pos": int(local_pos),
                "shift": int(shift),
                "iv_bit": int(iv_bit),
                "key_dependencies": dependencies,
            }
        )
        dependency_union.update(dependencies)

    key_dependencies = tuple(
        key_name for key_name in ("k0", "k1") if key_name in dependency_union
    )
    dependency_kind = _dependency_kind_from_dependencies(key_dependencies)

    return {
        "output_register": attacked_state_reg,
        "output_index": int(output_index),
        "output_bit_pos": int(output_bit_pos),
        "shifts": tuple(map(int, shifts)),
        "key_dependencies": key_dependencies,
        "dependency_kind": dependency_kind,
        "n_hypotheses": _dependency_count(dependency_kind),
        "local_dependencies": local_dependencies,
    }


def selected_hypothesis_indices_for_dependency_kind(dependency_kind):
    """
    Return full 64-hypothesis columns needed for the selected dependency kind.

    For k0-only targets, columns 0..7 are enough because k1 is irrelevant.
    For k1-only targets, columns 0, 8, ..., 56 are enough because k0 is
    irrelevant and the reduced column index is the local k1 triplet.
    """
    dependency_kind = str(dependency_kind)
    if dependency_kind == "k0":
        return np.arange(8, dtype=np.int64)
    if dependency_kind == "k1":
        return (np.arange(8, dtype=np.int64) << 3)
    if dependency_kind == "mixed":
        return np.arange(64, dtype=np.int64)
    if dependency_kind == "none":
        return np.empty(0, dtype=np.int64)
    raise ValueError(f"Unsupported dependency kind: {dependency_kind!r}")


def reduce_full_hypotheses(hypotheses, dependency_kind):
    """
    Convert full 6-bit hypotheses into the reduced local hypothesis space.

    This is useful when a CPA has only 8 columns but existing known-bit
    constraints are still expressed as full 64-hypothesis assignments.
    """
    hypotheses = list(map(int, hypotheses))
    dependency_kind = str(dependency_kind)

    if dependency_kind == "k0":
        return sorted({hypothesis & 0b111 for hypothesis in hypotheses})

    if dependency_kind == "k1":
        return sorted({(hypothesis >> 3) & 0b111 for hypothesis in hypotheses})

    if dependency_kind == "mixed":
        return sorted(set(hypotheses))

    if dependency_kind == "none":
        return []

    raise ValueError(f"Unsupported dependency kind: {dependency_kind!r}")


def expand_reduced_hypotheses(hypotheses, dependency_kind):
    """
    Expand reduced CPA hypotheses back into full 6-bit hypothesis assignments.

    For k0-only or k1-only leakage, the absent key word is intentionally varied
    over all 8 values so downstream constraint propagation does not learn false
    facts from a key word that was not present in the nonce-varying leakage.
    """
    hypotheses = list(map(int, hypotheses))
    dependency_kind = str(dependency_kind)

    if dependency_kind == "k0":
        k0_candidates = {hypothesis & 0b111 for hypothesis in hypotheses}
        return sorted(
            k0_candidate | (k1_candidate << 3)
            for k0_candidate in k0_candidates
            for k1_candidate in range(8)
        )

    if dependency_kind == "k1":
        k1_candidates = {hypothesis & 0b111 for hypothesis in hypotheses}
        return sorted(
            k0_candidate | (k1_candidate << 3)
            for k0_candidate in range(8)
            for k1_candidate in k1_candidates
        )

    if dependency_kind == "mixed":
        return sorted(set(hypotheses))

    if dependency_kind == "none":
        return []

    raise ValueError(f"Unsupported dependency kind: {dependency_kind!r}")


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
    hypothesis_mode="reduced",
):
    """
    Vectorized leakage computation.

    Returns
    -------
    leakage:
        ``False`` if the target has no nonce-varying key dependency;
        otherwise shape ``(N, 8)`` for k0-only/k1-only targets or
        ``(N, 64)`` for mixed k0/k1 targets when ``hypothesis_mode`` is
        ``"reduced"``. ``hypothesis_mode="full"`` always returns ``(N, 64)``.
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

    leakage = np.asarray(leakage, dtype=np.uint8)
    hypothesis_mode = str(hypothesis_mode).strip().lower()

    if hypothesis_mode == "full":
        return leakage

    if hypothesis_mode not in {"reduced", "auto"}:
        raise ValueError("hypothesis_mode must be one of: reduced, auto, full")

    target_info = get_target_key_dependencies(
        init_vect,
        attacked_state_reg,
        attacked_bit,
        sbox_type,
    )
    columns = selected_hypothesis_indices_for_dependency_kind(
        target_info["dependency_kind"]
    )

    if columns.size == 0:
        return False

    return leakage[:, columns].astype(np.uint8, copy=False)


def _compute_equivalent_leakage_matrix_impl(
    init_vect,
    nonce_MSB,
    nonce_LSB,
    attacked_state_reg,
    attacked_bit,
    sbox_type,
    backend="cpu",
):
    """
    Evaluate the selected S-box's explicit equivalent ANF decomposition.

    Unlike the LUT implementation, this computes the selected output equation
    directly as ``d + n0*n1*A + n0*B + n1*C`` for each of the three columns
    entering the attacked linear-layer bit.
    """
    xp = _select_array_backend(backend)
    _, output_bit_pos, shifts = _get_target_description(attacked_state_reg, attacked_bit)
    output_index = 4 - output_bit_pos

    key_guess_0, key_guess_1 = _get_key_hypothesis_bits()
    key0 = xp.asarray(key_guess_0, dtype=xp.uint8)
    key1 = xp.asarray(key_guess_1, dtype=xp.uint8)
    tables = xp.asarray(_get_equivalent_component_tables(sbox_type), dtype=xp.uint8)

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
    n1_bits = (
        (nonce_MSB[:, None].astype(xp.uint64) >> shifts_arr) & xp.uint64(1)
    ).astype(xp.uint8)
    n0_bits = (
        (nonce_LSB[:, None].astype(xp.uint64) >> shifts_arr) & xp.uint64(1)
    ).astype(xp.uint8)

    z = xp.zeros((nonce_MSB.shape[0], 64), dtype=xp.uint8)

    for local_pos, shift in enumerate(shifts):
        iv_bit = (int(init_vect) >> int(shift)) & 1
        round_constant_bit = (0xF0 >> int(shift)) & 1
        effective_k1 = key1[:, local_pos] ^ round_constant_bit
        coefficient_index = (
            (iv_bit << 2)
            | (key0[:, local_pos] << 1)
            | effective_k1
        )

        d = tables[output_index, coefficient_index, 0][None, :]
        a = tables[output_index, coefficient_index, 1][None, :]
        b = tables[output_index, coefficient_index, 2][None, :]
        c = tables[output_index, coefficient_index, 3][None, :]
        n1 = n1_bits[:, local_pos][:, None]
        n0 = n0_bits[:, local_pos][:, None]

        z ^= d ^ ((n0 & n1) & a) ^ (n0 & b) ^ (n1 & c)

    if xp is cp:
        z = cp.asnumpy(z)
    return z.astype(np.uint8)


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
    hypothesis_mode="reduced",
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

    hypothesis_mode:
        reduced | auto | full. In reduced/auto mode, the returned matrix is
        target-dependent: ``False`` for no key information, ``(N, 8)`` for
        k0-only/k1-only leakage, and ``(N, 64)`` for mixed k0/k1 leakage.

    Returns
    -------
    np.ndarray or bool:
        ``False`` or a uint8 matrix with shape ``(N, 8)`` or ``(N, 64)``.
    """
    return _compute_leakage_matrix_impl(
        init_vect,
        nonce_MSB,
        nonce_LSB,
        attacked_state_reg,
        attacked_bit,
        sbox_type,
        backend=backend,
        hypothesis_mode=hypothesis_mode,
    )


def ascon_generic_leakage_model(
    init_vect,
    nonce_MSB,
    nonce_LSB,
    attacked_state_reg,
    attacked_bit,
    sbox_type,
    hypothesis_mode="reduced",
):
    """
    Single-nonce leakage model.

    Returns
    -------
    np.ndarray or bool:
        ``False`` or a uint8 vector with length 8 or 64.
    """
    matrix = _compute_leakage_matrix_impl(
        init_vect,
        nonce_MSB,
        nonce_LSB,
        attacked_state_reg,
        attacked_bit,
        sbox_type,
        backend="cpu",
        hypothesis_mode=hypothesis_mode,
    )
    if matrix is False:
        return False
    return matrix[0]


def ascon_equivalent_leakage_matrix(
    init_vect,
    nonce_MSB,
    nonce_LSB,
    attacked_state_reg,
    attacked_bit,
    sbox_type,
    backend="cpu",
):
    """
    Batch leakage model evaluated from the selected S-box's equivalent equation.

    Returns an ``(N, 64)`` matrix exactly equivalent to the LUT model.
    """
    return _compute_equivalent_leakage_matrix_impl(
        init_vect,
        nonce_MSB,
        nonce_LSB,
        attacked_state_reg,
        attacked_bit,
        sbox_type,
        backend=backend,
    )


def ascon_equivalent_leakage_model(
    init_vect,
    nonce_MSB,
    nonce_LSB,
    attacked_state_reg,
    attacked_bit,
    sbox_type,
):
    """Single-nonce version of :func:`ascon_equivalent_leakage_matrix`."""
    return _compute_equivalent_leakage_matrix_impl(
        init_vect,
        nonce_MSB,
        nonce_LSB,
        attacked_state_reg,
        attacked_bit,
        sbox_type,
        backend="cpu",
    )[0]


def get_equivalent_key_dependencies(sbox_type, attacked_state_reg):
    """
    Return key words present in a register's nonce-varying equation.

    The result is one of ``()``, ``("k0",)``, ``("k1",)``, or
    ``("k0", "k1")`` and corresponds to the dependency labels in
    equivalent_ascon_sboxes.txt. This is a register-wide summary over both IV
    values; use :func:`get_target_key_dependencies` for the exact attacked bit.
    """
    _, output_bit_pos, _ = _get_target_description(attacked_state_reg, 0)
    output_index = 4 - output_bit_pos
    # Exclude d because the equivalent-expression report intentionally lists
    # only the nonce-varying A/B/C coefficients.
    coefficients = _get_equivalent_component_tables(sbox_type)[output_index, :, 1:]

    dependencies = []
    for key_name, key_shift in (("k0", 1), ("k1", 0)):
        depends = False
        for iv in (0, 1):
            for other_key in (0, 1):
                if key_name == "k0":
                    index0 = (iv << 2) | (0 << key_shift) | other_key
                    index1 = (iv << 2) | (1 << key_shift) | other_key
                else:
                    index0 = (iv << 2) | (other_key << 1) | 0
                    index1 = (iv << 2) | (other_key << 1) | 1
                if not np.array_equal(coefficients[index0], coefficients[index1]):
                    depends = True
                    break
            if depends:
                break
        if depends:
            dependencies.append(key_name)

    return tuple(dependencies)


def expand_hypotheses_for_key_dependencies(hypotheses, dependencies):
    """
    Remove false constraints on key words absent from the varying leakage.

    Signed correlation can distinguish hypotheses that differ only by a
    trace-constant term. Such a distinction is not key information when the
    nonce-varying equation does not depend on that key word. Expand the
    candidate set over every assignment of each absent key word.
    """
    hypotheses = list(map(int, hypotheses))
    dependencies = tuple(dependencies)

    if dependencies == ("k0",):
        k0_candidates = {hypothesis & 0b111 for hypothesis in hypotheses}
        return sorted(
            k0_candidate | (k1_candidate << 3)
            for k0_candidate in k0_candidates
            for k1_candidate in range(8)
        )

    if dependencies == ("k1",):
        k1_candidates = {(hypothesis >> 3) & 0b111 for hypothesis in hypotheses}
        return sorted(
            k0_candidate | (k1_candidate << 3)
            for k0_candidate in range(8)
            for k1_candidate in k1_candidates
        )

    if not dependencies:
        return list(range(64))

    return sorted(set(hypotheses))


def prioritize_targets_by_equivalent_dependencies(targets, sbox_type):
    """
    Stable-sort targets according to the selected S-box's equations.

    Single-key outputs are attacked first, followed by mixed-key outputs and
    finally outputs whose nonce-varying equation has no key dependency.
    Existing SNR order is preserved inside each category.
    """
    def priority(target):
        dependencies = get_equivalent_key_dependencies(sbox_type, target[0])
        if len(dependencies) == 1:
            return 0
        if len(dependencies) == 2:
            return 1
        return 2

    return sorted(targets, key=priority)


# ---------------------------------------------------------------------------
# Generic hypothesis interpretation helpers
# ---------------------------------------------------------------------------

def hypothesis_to_local_bits(hypothesis):
    """
    Decode one 6-bit hypothesis into the three local k0 and k1 bits.

    Hypothesis layout:
        [k1_2 k1_1 k1_0 k0_2 k0_1 k0_0]
    """
    hypothesis = int(hypothesis)
    k0_local = np.array(
        [(hypothesis >> (2 - position)) & 1 for position in range(3)],
        dtype=np.uint8,
    )
    k1_local = np.array(
        [(hypothesis >> (5 - position)) & 1 for position in range(3)],
        dtype=np.uint8,
    )
    return k0_local, k1_local


def group_hypotheses_by_leakage(leakage_matrix):
    """
    Group hypotheses whose leakage vectors are identical up to complement.

    Returns
    -------
    representative_indices:
        One hypothesis index per group.

    groups:
        For every representative, members are split into ``same`` and
        ``complement`` orientations. Absolute CPA cannot distinguish these
        orientations, but signed correlation plus a measured leakage-polarity
        convention can.
    """
    leakage_matrix = np.asarray(leakage_matrix, dtype=np.uint8)
    if leakage_matrix.ndim != 2:
        raise ValueError("leakage_matrix must be a 2D array")
    if np.any((leakage_matrix != 0) & (leakage_matrix != 1)):
        raise ValueError("leakage_matrix must contain only binary values")

    canonical_to_group = {}
    groups = []
    representative_indices = []

    for hypothesis in range(leakage_matrix.shape[1]):
        column = leakage_matrix[:, hypothesis]
        column_bytes = column.tobytes()
        complement_bytes = (1 - column).astype(np.uint8, copy=False).tobytes()
        canonical = min(column_bytes, complement_bytes)

        if canonical not in canonical_to_group:
            canonical_to_group[canonical] = len(groups)
            representative_indices.append(hypothesis)
            groups.append({"same": [], "complement": [], "all": []})

        group = groups[canonical_to_group[canonical]]
        representative = representative_indices[canonical_to_group[canonical]]
        representative_column = leakage_matrix[:, representative]

        if np.array_equal(column, representative_column):
            group["same"].append(hypothesis)
        elif np.array_equal(column, 1 - representative_column):
            group["complement"].append(hypothesis)
        else:
            raise RuntimeError("Invalid complement-equivalence group")
        group["all"].append(hypothesis)

    return np.asarray(representative_indices, dtype=np.int64), groups


def select_hypotheses_from_cpa(correlation_matrix, groups, polarity="negative"):
    """
    Select the winning equation-equivalent hypothesis set from grouped CPA.

    ``polarity`` describes the measured leakage relative to the predicted bit:
      - ``negative``: inverted measured leakage (repository measurement default)
      - ``positive``: direct measured leakage
      - ``both``: polarity unknown; retain both complement orientations
    """
    polarity = str(polarity).strip().lower()
    if polarity not in {"negative", "positive", "both"}:
        raise ValueError("polarity must be one of: negative, positive, both")

    correlation_matrix = np.asarray(correlation_matrix)
    if correlation_matrix.ndim != 2 or correlation_matrix.shape[0] != len(groups):
        raise ValueError("correlation_matrix rows must match the hypothesis groups")

    absolute = np.abs(correlation_matrix)
    peak_samples = np.argmax(absolute, axis=1)
    peak_abs = absolute[np.arange(len(groups)), peak_samples]
    peak_signed = correlation_matrix[np.arange(len(groups)), peak_samples]
    best_group_index = int(np.argmax(peak_abs))
    best_group = groups[best_group_index]

    if polarity == "both":
        selected = best_group["all"]
    elif polarity == "positive":
        selected = best_group["same"] if peak_signed[best_group_index] > 0 else best_group["complement"]
    else:
        selected = best_group["same"] if peak_signed[best_group_index] < 0 else best_group["complement"]

    # A constant or noisy representative can leave the selected orientation
    # empty. Retaining the whole equivalence group is conservative.
    if not selected:
        selected = best_group["all"]

    return {
        "best_group_index": best_group_index,
        "selected_hypotheses": list(map(int, selected)),
        "best_absolute_correlation": float(peak_abs[best_group_index]),
        "best_signed_correlation": float(peak_signed[best_group_index]),
        "best_sample": int(peak_samples[best_group_index]),
    }


def filter_hypotheses_by_known_bits(
    hypotheses,
    key_indices,
    k0_bits,
    k0_known,
    k1_bits,
    k1_known,
    xor_bits=None,
    xor_known=None,
):
    """
    Keep every local hypothesis compatible with previously recovered facts.

    This does not assume an ANF shape such as k0-only or k0 XOR k1. Therefore
    AND/OR-like and higher-degree S-box relations are handled as complete
    compatible hypothesis sets instead of being misclassified as key bits.
    """
    if xor_bits is None:
        xor_bits = np.zeros(64, dtype=np.uint8)
    if xor_known is None:
        xor_known = np.zeros(64, dtype=bool)

    compatible = []
    for hypothesis in hypotheses:
        k0_local, k1_local = hypothesis_to_local_bits(hypothesis)
        valid = True

        for local_position, key_index in enumerate(key_indices):
            key_index = int(key_index)
            value0 = int(k0_local[local_position])
            value1 = int(k1_local[local_position])

            if k0_known[key_index] and int(k0_bits[key_index]) != value0:
                valid = False
                break
            if k1_known[key_index] and int(k1_bits[key_index]) != value1:
                valid = False
                break
            if xor_known[key_index] and int(xor_bits[key_index]) != (value0 ^ value1):
                valid = False
                break

        if valid:
            compatible.append(int(hypothesis))

    return compatible


def _constraint_candidate_assignments(constraint):
    """
    Expand local hypotheses into assignments of global key-bit variables.

    A target normally touches three distinct indices. Rejecting a hypothesis
    that assigns different values to a repeated index keeps this correct for
    any future target mapping with duplicate indices.
    """
    key_indices = tuple(map(int, constraint["key_indices"]))
    hypotheses = tuple(map(int, constraint["hypotheses"]))
    cache_key = (key_indices, hypotheses)
    if constraint.get("_assignment_cache_key") == cache_key:
        return constraint["_assignment_cache"]

    entries = []

    for hypothesis in hypotheses:
        k0_local, k1_local = hypothesis_to_local_bits(hypothesis)
        assignment = {}
        valid = True

        for local_position, key_index in enumerate(key_indices):
            for key_name, value in (
                ("k0", int(k0_local[local_position])),
                ("k1", int(k1_local[local_position])),
            ):
                variable = (key_name, key_index)
                if variable in assignment and assignment[variable] != value:
                    valid = False
                    break
                assignment[variable] = value
            if not valid:
                break

        if valid:
            entries.append((int(hypothesis), assignment))

    constraint["_assignment_cache_key"] = cache_key
    constraint["_assignment_cache"] = entries
    return entries


def _constraint_projection(constraint, shared_key_indices):
    """Group candidate hypotheses by their values at shared global indices."""
    hypotheses = tuple(map(int, constraint["hypotheses"]))
    projection_cache_key = (
        tuple(map(int, constraint["key_indices"])),
        hypotheses,
    )
    if constraint.get("_projection_cache_key") != projection_cache_key:
        constraint["_projection_cache_key"] = projection_cache_key
        constraint["_projection_cache"] = {}

    shared_key_indices = tuple(sorted(map(int, shared_key_indices)))
    cache = constraint["_projection_cache"]
    if shared_key_indices in cache:
        return cache[shared_key_indices]

    shared_variables = tuple(
        (key_name, key_index)
        for key_index in shared_key_indices
        for key_name in ("k0", "k1")
    )
    projection = {}
    for hypothesis, assignment in _constraint_candidate_assignments(constraint):
        signature = tuple(assignment[variable] for variable in shared_variables)
        projection.setdefault(signature, []).append(hypothesis)

    cache[shared_key_indices] = projection
    return projection


def _prune_overlapping_constraint_pair(left, right):
    """
    Enforce pairwise consistency between two overlapping target relations.

    A hypothesis remains only when the other target has at least one
    hypothesis with the same values for every shared global key bit.
    """
    shared_key_indices = set(map(int, left["key_indices"])) & set(
        map(int, right["key_indices"])
    )
    if not shared_key_indices:
        return False, False

    left_projection = _constraint_projection(left, shared_key_indices)
    right_projection = _constraint_projection(right, shared_key_indices)
    supported_signatures = set(left_projection) & set(right_projection)

    # With incompatible noisy CPA results, preserve both relations because
    # there is no principled way to decide which target is wrong.
    if not supported_signatures:
        return False, True

    left_supported = {
        hypothesis
        for signature in supported_signatures
        for hypothesis in left_projection[signature]
    }
    right_supported = {
        hypothesis
        for signature in supported_signatures
        for hypothesis in right_projection[signature]
    }
    left_hypotheses = [
        int(hypothesis)
        for hypothesis in left["hypotheses"]
        if int(hypothesis) in left_supported
    ]
    right_hypotheses = [
        int(hypothesis)
        for hypothesis in right["hypotheses"]
        if int(hypothesis) in right_supported
    ]

    changed = (
        left_hypotheses != list(map(int, left["hypotheses"]))
        or right_hypotheses != list(map(int, right["hypotheses"]))
    )
    left["hypotheses"] = left_hypotheses
    right["hypotheses"] = right_hypotheses
    return changed, False


def propagate_hypothesis_constraints(
    constraints,
    k0_bits,
    k0_known,
    k1_bits,
    k1_known,
    xor_bits,
    xor_known,
    verbose=False,
    minimum_fact_support=1,
):
    """
    Preserve and repeatedly apply arbitrary per-target equation constraints.

    Each constraint is a dictionary containing ``key_indices`` and
    ``hypotheses``. Mixed relations that do not immediately reveal k0, k1, or
    k0 XOR k1 remain in the list. Overlapping target relations directly prune
    one another using shared global key-bit indices, preserving nonlinear and
    higher-degree relationships.
    """
    minimum_fact_support = int(minimum_fact_support)
    if minimum_fact_support < 1:
        raise ValueError("minimum_fact_support must be >= 1")

    new_facts = 0

    while True:
        facts_changed = False

        for constraint in constraints:
            constraint["overlap_conflict"] = False
            candidates = filter_hypotheses_by_known_bits(
                constraint["hypotheses"],
                constraint["key_indices"],
                k0_bits,
                k0_known,
                k1_bits,
                k1_known,
                xor_bits,
                xor_known,
            )

            if not candidates:
                constraint["conflict"] = True
                continue

            constraint["conflict"] = False
            constraint["hypotheses"] = candidates
            entries = _constraint_candidate_assignments(constraint)
            constraint["hypotheses"] = [hypothesis for hypothesis, _ in entries]
            if not constraint["hypotheses"]:
                constraint["conflict"] = True

        # Repeat pairwise pruning to a fixed point so a reduction from one
        # target can flow through every other overlapping target.
        pair_changed = True
        while pair_changed:
            pair_changed = False
            for left_index, left in enumerate(constraints):
                if left.get("conflict", False):
                    continue
                for right in constraints[left_index + 1:]:
                    if right.get("conflict", False):
                        continue
                    changed, overlap_conflict = _prune_overlapping_constraint_pair(
                        left,
                        right,
                    )
                    if overlap_conflict:
                        left["overlap_conflict"] = True
                        right["overlap_conflict"] = True
                    if changed:
                        pair_changed = True

        fact_support = {}

        for constraint_index, constraint in enumerate(constraints):
            if constraint.get("conflict", False) or constraint.get(
                "overlap_conflict",
                False,
            ):
                continue

            candidates = constraint["hypotheses"]
            local_bits = [hypothesis_to_local_bits(hypothesis) for hypothesis in candidates]
            k0_all = np.vstack([bits[0] for bits in local_bits])
            k1_all = np.vstack([bits[1] for bits in local_bits])
            xor_all = k0_all ^ k1_all

            for local_position, key_index in enumerate(constraint["key_indices"]):
                key_index = int(key_index)
                facts = (
                    ("k0", k0_all, k0_bits, k0_known),
                    ("k1", k1_all, k1_bits, k1_known),
                    ("k0^k1", xor_all, xor_bits, xor_known),
                )

                for name, values, stored_bits, known_flags in facts:
                    column = values[:, local_position]
                    if np.all(column == column[0]) and not known_flags[key_index]:
                        fact = (name, key_index, int(column[0]))
                        fact_support.setdefault(fact, set()).add(constraint_index)

        facts = (
            ("k0", k0_bits, k0_known),
            ("k1", k1_bits, k1_known),
            ("k0^k1", xor_bits, xor_known),
        )
        for name, stored_bits, known_flags in facts:
            for key_index in range(len(known_flags)):
                if known_flags[key_index]:
                    continue

                support0 = len(fact_support.get((name, key_index, 0), ()))
                support1 = len(fact_support.get((name, key_index, 1), ()))
                if support0 >= minimum_fact_support and support1 == 0:
                    value = 0
                    support = support0
                elif support1 >= minimum_fact_support and support0 == 0:
                    value = 1
                    support = support1
                else:
                    continue

                stored_bits[key_index] = value
                known_flags[key_index] = True
                facts_changed = True
                new_facts += 1
                if verbose:
                    print(
                        f"[INFO] Equation constraints recovered "
                        f"{name}[{key_index}]={value} "
                        f"from {support} agreeing targets"
                    )

        for key_index in range(len(k0_known)):
            if xor_known[key_index] and k0_known[key_index] and not k1_known[key_index]:
                k1_bits[key_index] = int(k0_bits[key_index] ^ xor_bits[key_index])
                k1_known[key_index] = True
                facts_changed = True
                new_facts += 1
            if xor_known[key_index] and k1_known[key_index] and not k0_known[key_index]:
                k0_bits[key_index] = int(k1_bits[key_index] ^ xor_bits[key_index])
                k0_known[key_index] = True
                facts_changed = True
                new_facts += 1

        if not facts_changed:
            break

    return new_facts
