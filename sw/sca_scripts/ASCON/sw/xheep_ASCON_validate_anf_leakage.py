#!/usr/bin/env python3
"""
Validate ANF equations against the ASCON S-box LUTs and leakage model.

This script checks two things:
  1. The ANF equations in doc/anf_ascon_sboxes.txt reproduce each 5-bit LUT.
  2. The ANF-derived S-box evaluation gives the same leakage matrix as the
     current generic LUT-based leakage model.
"""

import argparse
import re
import sys
from pathlib import Path

import numpy as np


def find_project_root(start: Path, markers=("fusesoc.conf", ".dojo_root")) -> Path:
    current = start
    while current != current.parent:
        if any((current / marker).exists() for marker in markers):
            return current
        current = current.parent
    raise RuntimeError(f"Could not find project root from {start}")


SCRIPT_DIR = Path(__file__).resolve().parent
DOJO_ROOT = find_project_root(SCRIPT_DIR)
SCA_DIR = DOJO_ROOT / "sw" / "sca_scripts"
DEFAULT_ANF_FILE = SCRIPT_DIR / "doc" / "anf_ascon_sboxes.txt"

sys.path.insert(0, str(SCA_DIR))

from analyzer.attack.ascon import ascon_funcs as ascon  # noqa: E402
from analyzer.attack.ascon.xheep_ascon_cpa.ascon_generic_leakage_model import (  # noqa: E402
    ascon_generic_leakage_matrix,
)


SBOX_NAME_MAP = {
    "sbox_ascon": "lut_ascon",
    "sbox_bilgin": "lut_bilgin",
    "sbox_allouzi": "lut_allouzi",
    "sbox_lu_4": "lut_lu_4",
    "sbox_lu_5": "lut_lu_5",
    "sbox_lu_6": "lut_lu_6",
    "sbox_lu_7": "lut_lu_7",
}

TARGETS = {
    "x0": ((0, 19, 28), 4),
    "x1": ((0, 61, 39), 3),
    "x2": ((0, 1, 6), 2),
    "x3": ((0, 10, 17), 1),
    "x4": ((0, 7, 41), 0),
}


def parse_term(term: str):
    term = term.strip()
    if term == "1":
        return ()

    variables = []
    for factor in term.split("*"):
        factor = factor.strip()
        match = re.fullmatch(r"x_(\d+)", factor)
        if not match:
            raise ValueError(f"Unsupported ANF factor: {factor!r}")
        idx = int(match.group(1))
        if not (0 <= idx <= 4):
            raise ValueError(f"Variable index out of range: x_{idx}")
        variables.append(idx)
    return tuple(variables)


def parse_expression(expr: str):
    return [parse_term(term) for term in expr.split("+") if term.strip()]


def parse_anf_file(path: Path):
    text = path.read_text(encoding="utf-8")
    blocks = re.split(r"=== Explicit ANF for ", text)[1:]
    parsed = {}

    for block in blocks:
        header = block.split("===", 1)[0].strip()
        source_name = header.split(" S-box", 1)[0].strip()
        sbox_type = SBOX_NAME_MAP.get(source_name)
        if sbox_type is None:
            raise ValueError(f"Unknown S-box name in ANF file: {source_name}")

        equations = {}
        for line in block.splitlines():
            match = re.match(r"\s*y_(\d+)\s*=\s*(.*?)\s*$", line)
            if match:
                out_idx = int(match.group(1))
                equations[out_idx] = parse_expression(match.group(2))

        if sorted(equations) != [0, 1, 2, 3, 4]:
            raise ValueError(f"Incomplete ANF equations for {sbox_type}: {sorted(equations)}")

        parsed[sbox_type] = [equations[i] for i in range(5)]

    return parsed


def eval_component(terms, variables):
    value = 0
    for term in terms:
        if not term:
            term_value = 1
        else:
            term_value = 1
            for idx in term:
                term_value &= int(variables[idx])
        value ^= term_value
    return value


def anf_sbox_value(equations, input_value: int) -> int:
    # ANF variables use ASCON notation: x_0 is the MSB and x_4 is the LSB.
    variables = [(int(input_value) >> (4 - idx)) & 1 for idx in range(5)]
    y = [eval_component(equations[idx], variables) for idx in range(5)]
    return sum(int(y[idx]) << (4 - idx) for idx in range(5))


def build_anf_luts(anf_models):
    return {
        sbox_type: np.asarray(
            [anf_sbox_value(equations, value) for value in range(32)],
            dtype=np.uint8,
        )
        for sbox_type, equations in anf_models.items()
    }


def validate_sbox_luts(anf_luts):
    failures = []
    for sbox_type, anf_lut in sorted(anf_luts.items()):
        expected = np.asarray([ascon.sbox(sbox_type, value) for value in range(32)], dtype=np.uint8)
        if not np.array_equal(anf_lut, expected):
            bad = np.nonzero(anf_lut != expected)[0]
            failures.append((sbox_type, bad[:8].tolist()))

    if failures:
        for sbox_type, examples in failures:
            print(f"[FAIL] {sbox_type}: ANF/LUT mismatch at inputs {examples}")
        raise SystemExit(1)

    print(f"[PASS] ANF equations reproduce all {len(anf_luts)} S-box LUTs exactly.")


def hypothesis_bits():
    guesses = np.arange(64, dtype=np.uint8)
    k0 = ((guesses[:, None] >> np.array([2, 1, 0], dtype=np.uint8)) & 1).astype(np.uint8)
    k1 = ((guesses[:, None] >> np.array([5, 4, 3], dtype=np.uint8)) & 1).astype(np.uint8)
    return k0, k1


def anf_leakage_matrix(init_vect, nonce_msb, nonce_lsb, reg, bit, anf_lut):
    shifts, output_bit_pos = TARGETS[reg]
    columns = tuple((int(bit) + shift) % 64 for shift in shifts)
    k0_guess, k1_guess = hypothesis_bits()

    nonce_msb = np.asarray(nonce_msb, dtype=np.uint64)
    nonce_lsb = np.asarray(nonce_lsb, dtype=np.uint64)
    z = np.zeros((nonce_msb.shape[0], 64), dtype=np.uint8)

    for local_pos, col in enumerate(columns):
        x0 = (int(init_vect) >> col) & 1
        rc = (0xF0 >> col) & 1
        x3 = ((nonce_msb >> np.uint64(col)) & np.uint64(1)).astype(np.uint8)
        x4 = ((nonce_lsb >> np.uint64(col)) & np.uint64(1)).astype(np.uint8)

        sbox_input = (
            (x0 << 4)
            | (k0_guess[:, local_pos][None, :] << 3)
            | ((k1_guess[:, local_pos][None, :] ^ rc) << 2)
            | (x3[:, None] << 1)
            | x4[:, None]
        )
        z ^= anf_lut[sbox_input]

    return ((z >> output_bit_pos) & 1).astype(np.uint8)


def validate_leakage_models(anf_luts, init_vect: int, num_nonces: int, seed: int):
    rng = np.random.default_rng(seed)
    nonce_msb = rng.integers(0, 1 << 64, size=num_nonces, dtype=np.uint64)
    nonce_lsb = rng.integers(0, 1 << 64, size=num_nonces, dtype=np.uint64)

    for sbox_type, anf_lut in sorted(anf_luts.items()):
        for reg in TARGETS:
            for bit in range(64):
                h_lut = ascon_generic_leakage_matrix(
                    init_vect,
                    nonce_msb,
                    nonce_lsb,
                    reg,
                    bit,
                    sbox_type,
                    backend="cpu",
                )
                h_anf = anf_leakage_matrix(
                    init_vect,
                    nonce_msb,
                    nonce_lsb,
                    reg,
                    bit,
                    anf_lut,
                )
                if not np.array_equal(h_lut, h_anf):
                    mismatch = np.argwhere(h_lut != h_anf)[0]
                    raise SystemExit(
                        "[FAIL] Leakage mismatch: "
                        f"sbox={sbox_type}, target={reg}[{bit}], "
                        f"nonce_row={int(mismatch[0])}, hypothesis={int(mismatch[1])}"
                    )

        print(f"[PASS] {sbox_type}: ANF-derived leakage equals generic LUT leakage.")


def main():
    parser = argparse.ArgumentParser(
        description="Validate ASCON ANF equations against LUT and leakage model.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--anf-file", type=Path, default=DEFAULT_ANF_FILE)
    parser.add_argument("--iv", default="00001000808C0001")
    parser.add_argument("--num-nonces", type=int, default=64)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--skip-leakage", action="store_true")
    args = parser.parse_args()

    anf_models = parse_anf_file(args.anf_file)
    anf_luts = build_anf_luts(anf_models)

    validate_sbox_luts(anf_luts)

    if not args.skip_leakage:
        validate_leakage_models(
            anf_luts,
            init_vect=int(str(args.iv), 16),
            num_nonces=int(args.num_nonces),
            seed=int(args.seed),
        )

    print("[PASS] ANF validation completed successfully.")


if __name__ == "__main__":
    main()
