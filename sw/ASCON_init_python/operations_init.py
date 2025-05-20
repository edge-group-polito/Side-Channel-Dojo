def ascon_init(key, nonce, variant="Ascon-128", mode="hw"): 

    assert variant in ["Ascon-128", "Ascon-128a", "Ascon-80pq"]
    if variant in ["Ascon-128", "Ascon-128a"]: assert(len(key) == 16 and len(nonce) == 16)
    if variant == "Ascon-80pq": assert(len(key) == 20 and len(nonce) == 16)
    S = [0, 0, 0, 0, 0]
    k = len(key) * 8   # bits
    a = 12   # rounds
    b = 8 if variant == "Ascon-128a" else 6   # rounds
    rate = 16 if variant == "Ascon-128a" else 8   # bytes

    state = ascon_initialize(S, k, rate, a, b, key, nonce, mode)

    return state

def ascon_initialize(S, k, rate, a, b, key, nonce, mode):

    state = to_bytes([])
    intermediate_state = to_bytes([])

    iv_zero_key_nonce = to_bytes([k, rate * 8, a, b]) + zero_bytes(20-len(key)) + key + nonce
    S[0], S[1], S[2], S[3], S[4] = bytes_to_state(iv_zero_key_nonce)

    for i in range(0,a):
        permutation(S, i, mode)

    state += int_to_bytes(S[0], 8) + int_to_bytes(S[1], 8) + int_to_bytes(S[2], 8) + int_to_bytes(S[3], 8) + int_to_bytes(S[4], 8) 

    return state


def permutation(S, r, mode="hw"):
    # --- constant addition ---
    S[2] ^= (0xf0 - r*0x10 + r*0x1)

    # --- substitution layer ---
    if mode == "hw" :
        S[0] ^= S[4]
        S[4] ^= S[3]
        S[2] ^= S[1]
        T = [(S[i] ^ 0xFFFFFFFFFFFFFFFF) & S[(i+1)%5] for i in range(5)]
        for i in range(5):
            S[i] ^= T[(i+1)%5]
        S[1] ^= S[0]
        S[0] ^= S[4]
        S[3] ^= S[2]
        S[2] ^= 0XFFFFFFFFFFFFFFFF
    elif mode == "lut_ascon":
        S = substitution_layer(S, "sbox_ascon")
    elif mode == "lut_bilgin":
        S = substitution_layer(S, "sbox_bilgin")
    elif mode == "lut_allouzi":
        S = substitution_layer(S, "sbox_allouzi")
    elif mode == "lut_lu_4":
        S = substitution_layer(S, "sbox_lu_4")
    elif mode == "lut_lu_5":
        S = substitution_layer(S, "sbox_lu_5")
    elif mode == "lut_lu_6":
        S = substitution_layer(S, "sbox_lu_6")
    elif mode == "lut_lu_7":
        S = substitution_layer(S, "sbox_lu_7")
    else:
        print("Error")

    # --- linear diffusion layer ---
    S[0] ^= rotr(S[0], 19) ^ rotr(S[0], 28)
    S[1] ^= rotr(S[1], 61) ^ rotr(S[1], 39)
    S[2] ^= rotr(S[2],  1) ^ rotr(S[2],  6)
    S[3] ^= rotr(S[3], 10) ^ rotr(S[3], 17)
    S[4] ^= rotr(S[4],  7) ^ rotr(S[4], 41)


def substitution_layer(S, sbox_type):
    S0_bin_out = []
    S1_bin_out = []
    S2_bin_out = []
    S3_bin_out = []
    S4_bin_out = []

    S0_bin_in = [int(bit) for bit in bin(S[0])[2:].zfill(64)]
    S1_bin_in = [int(bit) for bit in bin(S[1])[2:].zfill(64)]
    S2_bin_in = [int(bit) for bit in bin(S[2])[2:].zfill(64)]
    S3_bin_in = [int(bit) for bit in bin(S[3])[2:].zfill(64)]
    S4_bin_in = [int(bit) for bit in bin(S[4])[2:].zfill(64)]

    for i in range(0,64):
        Sbox_in = int((S0_bin_in[i] << 4) | (S1_bin_in[i] << 3) | (S2_bin_in[i] << 2) | (S3_bin_in[i] << 1) | S4_bin_in[i])
        Sbox_out = sbox[sbox_type][Sbox_in]
        Sbox_out_bin = [int(bit) for bit in bin(Sbox_out)[2:].zfill(5)]
        S0_bin_out.append(Sbox_out_bin[0])
        S1_bin_out.append(Sbox_out_bin[1])
        S2_bin_out.append(Sbox_out_bin[2])
        S3_bin_out.append(Sbox_out_bin[3])
        S4_bin_out.append(Sbox_out_bin[4])

    S[0] = int(''.join(str(bit) for bit in S0_bin_out),2)
    S[1] = int(''.join(str(bit) for bit in S1_bin_out),2)
    S[2] = int(''.join(str(bit) for bit in S2_bin_out),2)
    S[3] = int(''.join(str(bit) for bit in S3_bin_out),2)
    S[4] = int(''.join(str(bit) for bit in S4_bin_out),2)

    return S

def rotr(val, r):
    return (val >> r) | ((val & (1<<r)-1) << (64-r))

def to_bytes(l): # where l is a list or bytearray or bytes
    return bytes(bytearray(l))

def zero_bytes(n):
    return n * b"\x00"

def int_to_bytes(integer, nbytes):
    return to_bytes([(integer >> ((nbytes - 1 - i) * 8)) % 256 for i in range(nbytes)])

def bytes_to_int(bytes):
    return sum([bi << ((len(bytes) - 1 - i)*8) for i, bi in enumerate(to_bytes(bytes))])

def bytes_to_state(bytes):
    return [bytes_to_int(bytes[8*w:8*(w+1)]) for w in range(5)]

sbox = { "sbox_ascon" : [
0x04, 0x0b, 0x1f, 0x14, 0x1a, 0x15, 0x09, 0x02, 0x1b, 0x05, 0x08, 0x12, 0x1d, 0x03, 0x06, 0x1c,
0x1e, 0x13, 0x07, 0x0e, 0x00, 0x0d, 0x11, 0x18, 0x10, 0x0c, 0x01, 0x19, 0x16, 0x0a, 0x0f, 0x17],
        "sbox_bilgin" : [
0x01, 0x00, 0x19, 0x1a, 0x11, 0x1d, 0x15, 0x1b, 0x14, 0x05, 0x04, 0x17, 0x0e, 0x12, 0x02, 0x1c,
0x0f, 0x08, 0x06, 0x03, 0x0d, 0x07, 0x18, 0x10, 0x1e, 0x09, 0x1f, 0x0a, 0x16, 0x0c, 0x0b, 0x13],
        "sbox_allouzi" : [
0x10, 0x0e, 0x0d, 0x02, 0x0b, 0x11, 0x15, 0x1e, 0x07, 0x18, 0x12, 0x1c, 0x1a, 0x01, 0x0c, 0x06,
0x1f, 0x19, 0x00, 0x17, 0x14, 0x16, 0x08, 0x1b, 0x04, 0x03, 0x13, 0x05, 0x09, 0x0a, 0x1d, 0x0f],
        "sbox_lu_4" : [
0x18, 0x09, 0x1b, 0x06, 0x03, 0x1f, 0x16, 0x01, 0x14, 0x1e, 0x08, 0x05, 0x0a, 0x15, 0x0f, 0x10,
0x04, 0x13, 0x17, 0x0c, 0x1c, 0x00, 0x0d, 0x1a, 0x07, 0x0b, 0x19, 0x12, 0x11, 0x14, 0x02, 0x1d],
        "sbox_lu_5" : [
0x17, 0x1c, 0x0f, 0x10, 0x02, 0x01, 0x15, 0x1e, 0x19, 0x13, 0x12, 0x0c, 0x0b, 0x08, 0x0d, 0x06,
0x18, 0x0e, 0x00, 0x03, 0x05, 0x1d, 0x0a, 0x1b, 0x04, 0x07, 0x1f, 0x09, 0x1a, 0x16, 0x14, 0x11],
        "sbox_lu_6" : [
0x03, 0x0d, 0x1a, 0x16, 0x11, 0x02, 0x0f, 0x15, 0x00, 0x17, 0x0c, 0x09, 0x14, 0x19, 0x1e, 0x0a,
0x1b, 0x0e, 0x04, 0x1d, 0x1c, 0x08, 0x01, 0x12, 0x07, 0x18, 0x10, 0x13, 0x1f, 0x06, 0x0b, 0x05],
        "sbox_lu_7" : [
0x16, 0x0f, 0x10, 0x09, 0x1b, 0x03, 0x05, 0x06, 0x01, 0x15, 0x1e, 0x12, 0x1c, 0x08, 0x0a, 0x1d,
0x0e, 0x00, 0x0d, 0x1a, 0x18, 0x14, 0x11, 0x1f, 0x13, 0x0c, 0x07, 0x19, 0x0b, 0x17, 0x04, 0x02]
}