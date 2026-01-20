#!/usr/bin/env python3
"""
Generic ASCON SCA setup + basic leakage-model sanity check.

Loads traces from HDF5, prints key/IV/nonce info, and runs the
generic leakage model once on a chosen (state, bit).
"""

import sys
import os
import time
from pathlib import Path
import matplotlib.pyplot as plt  # kept in case you extend the script
import numpy as np
from tqdm import tqdm
import logging
import json
import h5py

# ---------------------------------------------------------------------------
# Basic configuration
# ---------------------------------------------------------------------------

sbox_type   = "lut_lu_5"   
tested_sbox = sbox_type     # alias used later in the printout
n_trc       = 150_000       # total number of traces used for the attack 
verbose     = True   # Verbose output during key recovery

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def find_project_root(start: Path, markers=("fusesoc.conf", ".dojo_root")) -> Path:
    """
    Walk upwards from 'start' until a directory containing one of 'markers'
    is found. That directory is treated as DOJO_ROOT.
    """
    current = start
    while current != current.parent:
        if any((current / m).exists() for m in markers):
            return current
        current = current.parent

    raise RuntimeError(
        f"Could not find project root (looked for markers: {markers}). "
        "Please ensure you are inside the Side-Channel-Dojo repository."
    )


def _yn(flag: bool) -> str:
    """Return 'yes' or 'no' for a boolean flag."""
    return "yes" if flag else "no"

def print_key_bits(label: str, bits: np.ndarray) -> None:
    assert bits.shape[0] == 64
    def _print_block(hi: int, lo: int) -> None:
        idxs = list(range(hi, lo - 1, -1))
        # Build strings with fixed-width tokens
        idx_line = "idx: " + " ".join(f"{i:2d}" for i in idxs)
        val_line = "val: " + " ".join(f"{int(bits[i]):2d}" for i in idxs)  # width-2 too
        # Insert byte separators (every 8 bits) for readability
        # (spaces already included by join, so we rebuild with separators)
        def _with_seps(tokens):
            out = []
            for j, t in enumerate(tokens):
                out.append(t)
                if (j + 1) % 8 == 0 and (j + 1) != len(tokens):
                    out.append("|")
            return " ".join(out)
        idx_tokens = [f"{i:2d}" for i in idxs]
        val_tokens = [f"{int(bits[i]):2d}" for i in idxs]
        idx_line = "idx: " + _with_seps(idx_tokens)
        val_line = "val: " + _with_seps(val_tokens)
        print(idx_line)
        print(val_line)
    print(f"\n[INFO] {label} bits (bit63 = LSB ... bit0 = MSB)")
    print("      Byte separators every 8 bits (|)\n")
    _print_block(63, 32)
    print("-" * 106)
    _print_block(31, 0)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    # In a script, __file__ exists; in a notebook it does not.
    try:
        script_dir = Path(__file__).resolve().parent
    except NameError:
        script_dir = Path.cwd()

    DOJO_ROOT = find_project_root(script_dir)

    # ---------------------------------------------------------------------------
    # Paths
    # ---------------------------------------------------------------------------
    ASCON_PY_DIR = DOJO_ROOT / "sw" / "ciphers" / "ASCON_init_python"
    SCA_DIR      = DOJO_ROOT / "sw" / "sca_scripts"

    # Base dirs for ASCON SW SCA
    BASE_PLOT_DIR  = DOJO_ROOT / "sw" / "sca_scripts" / "ASCON" / "sw" / "plot"
    BASE_CACHE_DIR = DOJO_ROOT / "sw" / "sca_scripts" / "ASCON" / "sw" / "cache"

    # Traceset (HDF5) for ASCON SW
    TRACESET_DIR  = DOJO_ROOT / "sw" / "traceset" / "ASCON" / "sw"
    TRACESET_FILE = TRACESET_DIR / f"ascon_opt32_{sbox_type}_{n_trc // 1000}k.h5"

    # Per-S-box dirs / files
    PLOT_DIR        = BASE_PLOT_DIR / sbox_type
    CACHE_DIR       = BASE_CACHE_DIR / sbox_type
    SNR_FILE    = CACHE_DIR / "snr_ranked.h5"
    CPA_CACHE_FILE  = CACHE_DIR / f"CPA_results_{sbox_type}.json"

    # Ensure directories exist
    BASE_PLOT_DIR.mkdir(parents=True, exist_ok=True)
    BASE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    PLOT_DIR.mkdir(parents=True, exist_ok=True)
    TRACESET_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    CPA_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)


    # Import local modules
    sys.path.insert(0, str(ASCON_PY_DIR))
    sys.path.insert(0, str(SCA_DIR))

    from analyzer.attack.ascon.xheep_ascon_cpa.ascon_generic_leakage_model import (
        ascon_generic_leakage_model,
    )
    from analyzer.attack.ascon.xheep_ascon_cpa.ascon_cpa import ascon_cpa

    # -----------------------------------------------------------------------
    # Flow flags
    # -----------------------------------------------------------------------
    # CPA / analysis cache control
    load_attack_results      = False  # Load CPA cache if available
    save_attack_results      = True   # Save CPA results to cache after the run

    # Plot control
    key_rank_plot            = True   # Plot PGE vs traces
    traces_correlation_plot  = True   # Plot correlation vs traces

    # Output control
    save_plots               = True   # Save plots to disk
    save_results             = True   # Save analysis results (JSON, etc.) to disk

    # -----------------------------------------------------------------------
    # Configuration printout
    # -----------------------------------------------------------------------
    print("\n================= CONFIGURATION =================")
    print(f"DOJO_ROOT           : {DOJO_ROOT}")
    print()
    print("Target")
    print(f"  Notebook scope            : CPA attack to ASCON SW with generic S-box")
    print(f"  S-box used                : {tested_sbox}")
    print(f"  Number of used traces     : {n_trc:,}")
    print()
    print("Paths")
    print(f"  Traceset file             : {TRACESET_FILE}")
    print(f"  SNR file of attacked bits : {SNR_FILE}")
    print(f"  Plot dir                  : {PLOT_DIR}")
    print(f"  CPA cache file            : {CPA_CACHE_FILE}")
    print()
    print("Analysis Configuration")
    print(f"  Save plots                : {_yn(save_plots)}")
    print(f"  Save results              : {_yn(save_results)}")
    print(f"  Load CPA results (cache)  : {_yn(load_attack_results)}")
    print(f"  Save CPA results (cache)  : {_yn(save_attack_results)}")
    print()
    print(f"  Key rank plot             : {_yn(key_rank_plot)}")
    print(f"  Correlation plot          : {_yn(traces_correlation_plot)}")
    print("=================================================\n")

    # -----------------------------------------------------------------------
    # Load traces & metadata
    # -----------------------------------------------------------------------
    try:
        with h5py.File(TRACESET_FILE, "r") as f_read_traces:
            # Basic sanity: check that required datasets exist
            if "traces" not in f_read_traces or "nonces" not in f_read_traces:
                raise KeyError(
                    "HDF5 file is missing required datasets 'traces' and/or 'nonces'."
                )

            traces_ds = f_read_traces["traces"]
            nonces_ds = f_read_traces["nonces"]

            total_traces = traces_ds.shape[0]
            n_samples    = traces_ds.shape[1]

            # Load metadata attributes (if present)
            sampling_interval = f_read_traces.attrs.get("sampling_interval", None)
            n_samples         = f_read_traces.attrs.get("n_samples", n_samples)
            key_hex           = f_read_traces.attrs.get("key_hex", None)
            iv_hex            = f_read_traces.attrs.get("iv_hex", None)

            # Use at most n_trc traces, but do not exceed what's in the file
            n_used = min(n_trc, total_traces)

            # Use slicing so data are actually loaded into RAM
            traces = traces_ds[:n_used]
            nonces = nonces_ds[:n_used]

        # Sanity check: traces and nonces should have the same number of rows
        if traces.shape[0] != nonces.shape[0]:
            raise ValueError(
                f"Number of traces ({traces.shape[0]}) and nonces ({nonces.shape[0]}) "
                "do not match. Check the traces file."
            )

        # Optional sanity checks vs metadata
        if n_trc != total_traces:
            print(
                f"[WARN] Wanted n_trc={n_trc} "
                f"differs from dataset length={total_traces}"
            )
        
        # Rebuild the first nonce in big-endian hex (undo byte reversal)
        nonce_msb = int(nonces[0, 0])  # 0x0F0E0D0C0B0A0908
        nonce_lsb = int(nonces[0, 1])  # 0x0706050403020100
        nonce_stored_int = (nonce_msb << 64) | nonce_lsb
        nonce_original_bytes = nonce_stored_int.to_bytes(16, byteorder="big")[::-1]
        nonce_original_hex = nonce_original_bytes.hex().upper()

        print(f"[INFO] Loaded {traces.shape[0]} traces from {TRACESET_FILE}")
        print(f"[INFO] Sampling interval      : {sampling_interval}")
        print(f"[INFO] Samples per trace      : {n_samples}")
        if key_hex is not None:
            print(f"[INFO] Key                    : 0x{key_hex}")
        else:
            print("[WARN] Key hex attribute 'key_hex' not found in HDF5 file.")
        if iv_hex is not None:
            print(f"[INFO] IV                     : 0x{iv_hex}")
        else:
            print("[WARN] IV hex attribute 'iv_hex' not found in HDF5 file.")
        print(f"[INFO] Initial nonce          : 0x{nonce_original_hex}")

    except FileNotFoundError:
        print(
            f"[ERROR] Traces file {TRACESET_FILE} not found. "
            "Please run the trace acquisition phase first."
        )
        return
    except Exception as e:
        print(f"[ERROR] Could not read traces file {TRACESET_FILE}: {e}")
        return

    if key_hex is None or iv_hex is None:
        print("[ERROR] Missing key_hex or iv_hex in attributes, cannot proceed.")
        return

    # -----------------------------------------------------------------------
    # Decode key/IV and pretty-print expected halves
    # -----------------------------------------------------------------------

    # IV as integer (already in correct endianness)
    iv_int = int(iv_hex, 16)

    key_b = bytes.fromhex(key_hex)
    # Matching how the the C code loads k_0->s[1], k_1->s[2] (little endian)
    k0_int = int.from_bytes(key_b[0:8],  byteorder="little")  # 07 06 05 04 03 02 01 00
    k1_int = int.from_bytes(key_b[8:16], byteorder="little")  # 0F 0E 0D 0C 0B 0A 09 08

    # Expected bits, LSB at index 0
    k0_bits = np.array([(k0_int >> i) & 1 for i in range(64)], dtype=np.uint8)
    k1_bits = np.array([(k1_int >> i) & 1 for i in range(64)], dtype=np.uint8)

    # Pretty-print bytes explicitly as stored in Little-Endian (LSB byte -> MSB byte)
    k0_bytes_le = [f"{b:02X}" for b in k0_int.to_bytes(8, "little")]
    k1_bytes_le = [f"{b:02X}" for b in k1_int.to_bytes(8, "little")]

    # Pretty-printed table by byte
    label_width = 12
    byte_indices = list(range(7, -1, -1))

    print("\n[INFO] Key halves by byte (big-endian)")
    print(f"{'':<{label_width}}" + "  " + "  ".join(f"{b:>2}" for b in byte_indices))
    print(f"{'k0':<{label_width}}" + "  " + "  ".join(f"{b:>2}" for b in k0_bytes_le))
    print(f"{'k1':<{label_width}}" + "  " + "  ".join(f"{b:>2}" for b in k1_bytes_le))
    if verbose:
        print_key_bits("k0", k0_bits)
        print_key_bits("k1", k1_bits)

    # -----------------------------------------------------------------------
    # Simple leakage-model sanity check on one attacked bit
    # -----------------------------------------------------------------------
    H = np.empty((n_trc, 64), dtype=np.uint8)

    # -------------------------------------------------------------------
    # Containers for recovered key bits
    # -------------------------------------------------------------------
    k0_rec_bits      = np.zeros(64, dtype=np.uint8)   # most significant 64 bits
    k0_rec = np.zeros(64, dtype=bool)
    k1_rec_bits      = np.zeros(64, dtype=np.uint8)   # least significant 64 bits
    k1_rec = np.zeros(64, dtype=bool)
    k0_xor_k1_rec_bits = np.zeros(64, dtype=np.uint8)
    k0_xor_k1_rec = np.zeros(64, dtype=bool)
    
    tic = time.perf_counter()
    print("\n=== Recovering k0 and k1 (generic 6-bit leakage model) ===\n")

    if not os.path.exists(SNR_FILE):
        raise FileNotFoundError(f"Attacked bits file not found: {SNR_FILE}")

    try:
        with h5py.File(SNR_FILE, "r") as f:
            regs = f["ranked/register"][:].astype(str)
            bits = f["ranked/bit"][:].astype(int)
    except Exception as e:
        print(f"[ERROR] Could not read SNR file {SNR_FILE}: {e}")
        raise
    attacked_targets = list(zip(regs.tolist(), bits.tolist()))
    print(f"[INFO] Loaded {len(attacked_targets)} attacked targets from {SNR_FILE}")
    if verbose : 
        print(f"[INFO] Top-5 targets: {[(attacked_targets[i][0], attacked_targets[i][1]) for i in range(min(5,len(attacked_targets)))]}")

    # -----------------------------------------------------------------------
    # Attack loop
    # -----------------------------------------------------------------------
    full_key_recovered = False
    for attacked_state_reg, attacked_bit in attacked_targets:
        if full_key_recovered:
            break

        # Compute the indices constrained by this attack
        j = attacked_bit % 64
        if attacked_state_reg == "x0":
            k_idx = np.array([j, (j + 19) % 64, (j + 28) % 64], dtype=int)
        elif attacked_state_reg == "x1":
            k_idx = np.array([j, (j + 61) % 64, (j + 39) % 64], dtype=int)
        elif attacked_state_reg == "x2":
            k_idx = np.array([j, (j + 1) % 64, (j + 6) % 64], dtype=int)
        elif attacked_state_reg == "x3":
            k_idx = np.array([j, (j + 10) % 64, (j + 17) % 64], dtype=int)
        elif attacked_state_reg == "x4":
            k_idx = np.array([j, (j + 7) % 64, (j + 41) % 64], dtype=int)
        else:
            raise ValueError(f"Invalid attacked_state_register: {attacked_state_reg}")

        # -------------------------------------------------------------------
        # Skip if this target cannot add new info
        #
        # We consider an index "done" if:
        #   - both k0 and k1 are known, OR
        #   - xor is known and one side is known (because the other can be derived)
        # -------------------------------------------------------------------
        useful = False
        for idx in k_idx:
            idx_done = (k0_rec[idx] and k1_rec[idx]) \
                       or (k0_xor_k1_rec[idx] and (k0_rec[idx] or k1_rec[idx]))
            if not idx_done:
                useful = True
                break

        if not useful:
            if verbose:
                print(f"\n[INFO] Skipping {attacked_state_reg}[{attacked_bit}] (no new bits expected)")
            continue

        print(f"\n[INFO] Attacking state register {attacked_state_reg}, bit {attacked_bit}")
        print(f"[INFO] This attack constrains key bit indices: {k_idx.tolist()}")
        
        # ---------------------------------------------------------------
        # 2) Build full leakage matrix H for this (state, bit)
        #    H has shape (n_traces, 64):
        #      - rows    = traces / nonces
        #      - columns = 6-bit key hypotheses [k1_2 k1_1 k1_0 k0_2 k0_1 k0_0]
        # ---------------------------------------------------------------

        for i in range(n_trc):
            nonce_lsb0 = int(nonces[i, 0])  # LSB 64 bits
            nonce_msb0 = int(nonces[i, 1])  # MSB 64 bits

            H[i] = ascon_generic_leakage_model(
                iv_int,
                nonce_msb0,
                nonce_lsb0,
                attacked_state_reg,
                attacked_bit,
                sbox_type,
            )

        # ---------------------------------------------------------------
        # 3) Group hypotheses that produce the same leakage pattern
        #    up to bitwise complement:
        #
        #    Let H be shape (n_traces, 64), columns = leakage vectors
        #    for each 6-bit key hypothesis k = 0..63.
        #
        #    Two hypotheses k and k' are placed in the same group iff:
        #        H[:, k] == H[:, k']       (identical),  OR
        #        H[:, k] == 1 - H[:, k']   (bitwise complement).
        #
        #    Reason: corr(traces, y) and corr(traces, 1-y) have the
        #    same absolute value, so such hypotheses cannot be
        #    distinguished by |correlation|.
        #
        #    We build:
        #      - key_hyp_groups: list of groups, each group is a list
        #        of original hypothesis indices.
        #      - H_group: shape (n_traces, num_groups), one
        #        representative leakage column per group (any member).
        # ---------------------------------------------------------------
        _ , n_hyp = H.shape

        # Map "canonical" leakage pattern (identical up to complement) -> group index.
        # Canonical representation is chosen as the lexicographically smaller
        # between the pattern and its complement, encoded as bytes.
        canonical_to_group = {}
        key_hyp_groups = []        # list[list[int]]: members (original hyp indices) per group
        group_leakage_cols = []    # one representative leakage column per group (shape (n_traces,))

        if verbose : print(f"[DEBUG] Grouping the {n_hyp} hypotheses by leakage patterns...")
        for k_guess in range(n_hyp):
            # k_guess is 6 bits: [k1_2 k1_1 k1_0 k0_2 k0_1 k0_0]
            col = H[:, k_guess].astype(np.uint8)  # shape (n_traces,), values in {0,1}
            compl = 1 - col                        # bitwise complement in {0,1}

            # Encode both as bytes for stable comparison / hashing
            col_bytes  = col.tobytes()
            compl_bytes = compl.tobytes()

            # Canonical key: identical patterns and their complements
            # share the same canonical_bytes
            canonical_bytes = col_bytes if col_bytes <= compl_bytes else compl_bytes
            if canonical_bytes in canonical_to_group:
                # Already have a group for this canonical pattern
                g_idx = canonical_to_group[canonical_bytes]
                key_hyp_groups[g_idx].append(k_guess)
            else:
                # New group: register mapping, store first member and its leakage
                g_idx = len(key_hyp_groups)
                canonical_to_group[canonical_bytes] = g_idx
                key_hyp_groups.append([k_guess])
                group_leakage_cols.append(col)   # representative; comp would work as well

        # Build H_group with one representative leakage vector per group
        H_group = np.column_stack(group_leakage_cols)   # shape (n_traces, num_groups)
        num_groups = H_group.shape[1]


        # ---------------------------------------------------------------
        # 4) Run CPA once per *grouped* hypothesis
        #    ascon_cpa expects:
        #      - traces: shape (N, M)
        #      - hypothetical_values: shape (N, K)
        #    Here K = num_groups.
        # ---------------------------------------------------------------
        R_group   = ascon_cpa(traces[:n_trc], H_group)         # shape (num_groups, n_samples)
        corr_group = np.max(np.abs(R_group), axis=1)   # got |corr| per each group

        best_group_idx = int(np.argmax(corr_group))
        best_key_group   = key_hyp_groups[best_group_idx]   

        if verbose:
            print(f"\nTotal number of groups: {num_groups}")
            print(f"Best group index: {best_group_idx}\n")
            print("group   hyp   k1    k0")
            print("------------------------")
            # Print only the group with highest correlation
            if 0 <= best_group_idx < len(key_hyp_groups):
                members = key_hyp_groups[best_group_idx]
                if not members:
                    print(f"{best_group_idx:5d}  <empty group>")
                else:
                    for line_idx, hyp_idx in enumerate(members):
                        # 6-bit hypothesis index: [k1_2 k1_1 k1_0 k0_2 k0_1 k0_0]
                        k1_loc = (hyp_idx >> 3) & 0b111  # upper 3 bits
                        k0_loc = hyp_idx        & 0b111  # lower 3 bits
                        group_label = f"{best_group_idx:5d}" if line_idx == 0 else " " * 5
                        print(f"{group_label}  {hyp_idx:3d}  {k1_loc:03b}  {k0_loc:03b}")
            else:
                print(f"[WARN] best_group_idx={best_group_idx} out of range (num_groups={num_groups})")
            print()

        # ---------------------------------------------------------------
        # 5) Decode local key bits for each hypothesis in the winning group
        #
        #    Grouping means multiple (k0,k1) pairs produce the same leakage
        #    prediction (up to complement), so CPA cannot distinguish them.
        #
        #    Two common causes:
        #      A) Single-key influence: only k0 or only k1 affects the attacked
        #         intermediate => the influencing key bit(s) become constant
        #         across the group and can be directly recovered.
        #
        #      B) XOR-only influence: the intermediate depends on (k0 ⊕ k1)
        #         => for each local bit position i, (k0[i] ⊕ k1[i]) is constant.
        #         If this holds for ALL 3 local columns, we recover (k0 ⊕ k1).
        #
        #    Hypothesis bits (h in 0..63): h = (b5 b4 b3 b2 b1 b0)_2
        #      - local k1 bits = [b5, b4, b3]
        #      - local k0 bits = [b2, b1, b0]
        # ---------------------------------------------------------------
        #    IMPORTANT:
        #    - Only check Scenario A/B if the winning group has >1 hypothesis.
        #    - If the winning group has exactly 1 hypothesis, then this iteration
        #      uniquely identifies the 6 local key bits (3 k0 + 3 k1).
        # ---------------------------------------------------------------

        group_size = len(best_key_group)

        if group_size == 1:
            # No grouping ambiguity: recover all 6 bits directly from the winning hypothesis
            hyp = int(best_key_group[0])

            # local k0 bits: [b2, b1, b0]
            k0_local = np.array([(hyp >> (2 - b)) & 1 for b in range(3)], dtype=np.uint8)
            # local k1 bits: [b5, b4, b3]
            k1_local = np.array([(hyp >> (5 - b)) & 1 for b in range(3)], dtype=np.uint8)

            for local_pos, idx in enumerate(k_idx):
                val0 = int(k0_local[local_pos])
                val1 = int(k1_local[local_pos])

                # Commit k0 bit (write-once, warn on conflict)
                if not k0_rec[idx]:
                    k0_rec_bits[idx] = val0
                    k0_rec[idx] = True
                    if verbose:
                        print(f"[INFO] Recovered k0[{idx}]={val0}")
                        print(f"[WARN] Expected k0[{idx}]={k0_bits[idx]} but got {val0}") if val0 != k0_bits[idx] else None
                elif k0_rec_bits[idx] != val0 and verbose:
                    print(f"[WARN] Conflicting recovery for k0 bit {idx}: existing={k0_rec_bits[idx]}, new={val0} (ignored)")

                # Commit k1 bit (write-once, warn on conflict)
                if not k1_rec[idx]:
                    k1_rec_bits[idx] = val1
                    k1_rec[idx] = True
                    if verbose:
                        print(f"[INFO] Recovered k1[{idx}]={val1}")
                        print(f"[WARN] Expected k1[{idx}]={k1_bits[idx]} but got {val1}") if val1 != k1_bits[idx] else None
                elif k1_rec_bits[idx] != val1 and verbose:
                    print(f"[WARN] Conflicting recovery for k1 bit {idx}: existing={k1_rec_bits[idx]}, new={val1} (ignored)")

                # If xor known, check consistency with known k0/k1 bits
                if k0_xor_k1_rec[idx]:
                    xb = int(k0_xor_k1_rec_bits[idx])
                    xb_comp = int(k0_rec[idx] ^ k1_rec[idx])

                    if xb != xb_comp and verbose:
                        print(f"[WARN] Conflicting recovery for (k0^k1)[{idx}]: stored={xb}, computed={xb_comp} (ignored)")

        else:
            # Grouping ambiguity exists: run Scenario A and Scenario B
            k0_local_list = []
            k1_local_list = []
            for hyp in best_key_group:
                hyp = int(hyp)
                k0_local = np.array([(hyp >> (2 - b)) & 1 for b in range(3)], dtype=np.uint8)
                k1_local = np.array([(hyp >> (5 - b)) & 1 for b in range(3)], dtype=np.uint8)
                k0_local_list.append(k0_local)
                k1_local_list.append(k1_local)

            k0_local_all = np.vstack(k0_local_list).astype(np.uint8)  # (group_size, 3)
            k1_local_all = np.vstack(k1_local_list).astype(np.uint8)  # (group_size, 3)

            # -----------------------------------
            # Scenario A: single-key influence
            # (recover constants across the group)
            # -----------------------------------
            k0_const = np.all(k0_local_all == k0_local_all[0:1, :], axis=0)  # (3,)
            k1_const = np.all(k1_local_all == k1_local_all[0:1, :], axis=0)  # (3,)

            for local_pos, idx in enumerate(k_idx):
                if k0_const[local_pos]:
                    val0 = int(k0_local_all[0, local_pos])
                    if not k0_rec[idx]:
                        k0_rec_bits[idx] = val0
                        k0_rec[idx] = True
                        if verbose:
                            print(f"[INFO] Recovered k0[{idx}]={val0}")
                            print(f"[WARN] Expected k0[{idx}]={k0_bits[idx]} but got {val0}") if val0 != k0_bits[idx] else None
                    elif k0_rec_bits[idx] != val0 and verbose:
                        print(f"[WARN] Conflicting recovery for k0 bit {idx}: existing={k0_rec_bits[idx]}, new={val0} (ignored)")

                if k1_const[local_pos]:
                    val1 = int(k1_local_all[0, local_pos])
                    if not k1_rec[idx]:
                        k1_rec_bits[idx] = val1
                        k1_rec[idx] = True
                        if verbose:
                            print(f"[INFO] Recovered k1[{idx}]={val1}")
                            print(f"[WARN] Expected k1[{idx}]={k1_bits[idx]} but got {val1}") if val1 != k1_bits[idx] else None
                    elif k1_rec_bits[idx] != val1 and verbose:
                        print(f"[WARN] Conflicting recovery for k1 bit {idx}: existing={k1_rec_bits[idx]}, new={val1} (ignored)")

                # Propagate if xor already known
                if k0_xor_k1_rec[idx]:
                    xb = int(k0_xor_k1_rec_bits[idx])

                    if k0_rec[idx] and not k1_rec[idx] and verbose:
                        k1_rec_bits[idx] = int(k0_rec_bits[idx] ^ xb)
                        k1_rec[idx] = True
                        print(f"[INFO] Recovered k1[{idx}]={k1_rec_bits[idx]} using k0[{idx}] and k0^k1[{idx}]")
                        print(f"[WARN] Expected k1[{idx}]={k1_bits[idx]} but got {k1_rec_bits[idx]}") if k1_rec_bits[idx] != k1_bits[idx] else None

                    if k1_rec[idx] and not k0_rec[idx] and verbose:
                        k0_rec_bits[idx] = int(k1_rec_bits[idx] ^ xb)
                        k0_rec[idx] = True
                        print(f"[INFO] Recovered k0[{idx}]={k0_rec_bits[idx]} using k1[{idx}] and k0^k1[{idx}]")
                        print(f"[WARN] Expected k0[{idx}]={k0_bits[idx]} but got {k0_rec_bits[idx]}") if k0_rec_bits[idx] != k0_bits[idx] else None

            # ------------------------------
            # Scenario B: XOR-only influence
            # ------------------------------
            xor_mat = k0_local_all ^ k1_local_all          # (group_size, 3)
            xor_val = xor_mat[0]                           # candidate (3,)
            all_cols_ok = bool(np.all(xor_mat == xor_val[None, :]))  # must hold for ALL columns

            if all_cols_ok:
                for local_pos, idx in enumerate(k_idx):
                    xor_bit = int(xor_val[local_pos])

                    if not k0_xor_k1_rec[idx]:
                        k0_xor_k1_rec_bits[idx] = xor_bit
                        k0_xor_k1_rec[idx] = True
                        # Immediately try to derive the missing side if possible
                        if k0_rec[idx] and not k1_rec[idx] and verbose:
                            k1_rec_bits[idx] = int(k0_rec_bits[idx] ^ xor_bit)
                            k1_rec[idx] = True
                            print(f"[INFO] Recovered k1[{idx}]={k1_rec_bits[idx]} using k0[{idx}] and k0^k1[{idx}]")
                            print(f"[WARN] Expected k1[{idx}]={k1_bits[idx]} but got {k1_rec_bits[idx]}") if k1_rec_bits[idx] != k1_bits[idx] else None

                        if k1_rec[idx] and not k0_rec[idx] and verbose:
                            k0_rec_bits[idx] = int(k1_rec_bits[idx] ^ xor_bit)
                            k0_rec[idx] = True
                            print(f"[INFO] Recovered k0[{idx}]={k0_rec_bits[idx]} using k1[{idx}] and k0^k1[{idx}]")
                            print(f"[WARN] Expected k0[{idx}]={k0_bits[idx]} but got {k0_rec_bits[idx]}") if k0_rec_bits[idx] != k0_bits[idx] else None

                    elif k0_xor_k1_rec_bits[idx] != xor_bit and verbose:
                        print(f"[WARN] Conflicting recovery for (k0^k1) bit {idx}: "
                              f"existing={k0_xor_k1_rec_bits[idx]}, new={xor_bit} (ignored)")
                    
        # -------------------------------------------------------------------
        # Update termination condition
        # -------------------------------------------------------------------
        full_key_recovered = bool(np.all(k0_rec) and np.all(k1_rec))
        print(f"[INFO] Progress: k0={np.sum(k0_rec)}/64, k1={np.sum(k1_rec)}/64, k0_xor_k1={np.sum(k0_xor_k1_rec)}/64")

        if (full_key_recovered):
            break
    toc = time.perf_counter()
    print(f"\n key recovery attack completed in {(toc - tic)/60:.2f} minutes.") 
    # -------------------------------------------------------------------
    # After the attack: build recovered ints and compare to expected key
    # Assumes you already have:
    #   - expected: k0_int, k1_int (uint64 values)
    #   - expected bits: k0_rec_bits_exp, k1_bits_exp (0/1 arrays)   <-- rename to avoid clash
    #   - recovered bits arrays + masks: k0_rec_bits, k1_rec_bits, k0_rec, k1_rec
    # -------------------------------------------------------------------
    
    def bits_to_u64(bits_lsb0: np.ndarray) -> int:
        """bits_lsb0[i] is bit i (LSB at index 0)."""
        x = 0
        for i in range(64):
            x |= (int(bits_lsb0[i]) & 1) << i
        return x
    
    # Build recovered ints (unknown bits are currently 0 in your arrays)
    k0_rec_int = bits_to_u64(k0_rec_bits)
    k1_rec_int = bits_to_u64(k1_rec_bits)
    
    print("\n================= KEY CHECK =================")
    print(f"[INFO] Expected k0 : 0x{k0_int:016X}")
    print(f"[INFO] Recovered k0: 0x{k0_rec_int:016X}  ({np.sum(k0_rec)}/64 bits recovered)")
    
    print(f"[INFO] Expected k1 : 0x{k1_int:016X}")
    print(f"[INFO] Recovered k1: 0x{k1_rec_int:016X}  ({np.sum(k1_rec)}/64 bits recovered)")
    
    # Count correct bits (only count positions you actually recovered)
    #k0_correct = int(np.sum((k0_rec_bits == np.array([(k0_int >> i) & 1 for i in range(64)], dtype=np.uint8)) & k0_rec))
    #k1_correct = int(np.sum((k1_rec_bits == np.array([(k1_int >> i) & 1 for i in range(64)], dtype=np.uint8)) & k1_rec))
    k0_correct = int(np.sum((k0_rec_bits == k0_bits) & k0_rec))
    k1_correct = int(np.sum((k1_rec_bits == k1_rec_bits) & k1_rec))


    print(f"[INFO] Correct recovered bits:")
    print(f"       k0: {k0_correct}/{int(np.sum(k0_rec))} correct (among recovered)")
    print(f"       k1: {k1_correct}/{int(np.sum(k1_rec))} correct (among recovered)")
    
    # Optional: strict full-key check (only meaningful if fully recovered)
    if np.all(k0_rec) and np.all(k1_rec):
        ok = (k0_rec_int == k0_int) and (k1_rec_int == k1_int)
        print(f"[INFO] Full key match: {'YES' if ok else 'NO'}")
    else:
        print("[INFO] Full key match: N/A (not all bits recovered)")
    print("=============================================\n")


    ## Pretty-print H values for k1={0,0,0} and all k0 combinations
    #print(f"\n[INFO] Leakage values H for first 5 traces:\n")
    #print("k1       k0       k      H values (trace 0..4)")
    #print("-------  -------  ------ --------------------")
    #
    #k1_target = 1  # k1 = {0,0,0}
    #
    #for k0_guess in range(8):
    #    # Encode as 6-bit hypothesis: k0 in lower 3 bits, k1 in upper 3 bits
    #    k_guess = (k1_target << 3) | k0_guess
    #    
    #    # Convert to binary strings for display
    #    k1_bits = f"{k1_target:03b}"
    #    k0_bits = f"{k0_guess:03b}"
    #    
    #    # Get the H values for this hypothesis across all traces
    #    h_values = H[:, k_guess]
    #    h_str = ",".join(str(int(h)) for h in h_values)
    #    
    #    print(f"{k1_bits}      {k0_bits}      {k_guess}      [{h_values}]")


    print()
    print("--- DEBUG LOGS BELOW (if any) ---")


if __name__ == "__main__":
    main()
