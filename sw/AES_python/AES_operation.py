"""
Fundamental blocks for AES-128 implementation
"""
from AES_sbox import sbox, inv_sbox, get_sbox, get_inv_sbox 

def SubBytes(sbox_type, s):
    """ Peform an S-box substitution on the state matrix"""
    for i in range(4):
        for j in range(4):
            s[i][j] = sbox(sbox_type, s[i][j])

def InvSubBytes(sbox_type, s):
    """ Peform an inverse S-box substitution on the state matrix"""
    for i in range(4):
        for j in range(4):
            s[i][j] = inv_sbox(sbox_type, s[i][j])

#ShiftRows
def ShiftRows(s):
    shr_o = []
    temp = [s[0][0],s[1][1],s[2][2],s[3][3]]
    shr_o.append(temp)
    temp = [s[1][0],s[2][1],s[3][2],s[0][3]]
    shr_o.append(temp)
    temp = [s[2][0],s[3][1],s[0][2],s[1][3]]
    shr_o.append(temp)
    temp = [s[3][0],s[0][1],s[1][2],s[2][3]]
    shr_o.append(temp)

    return shr_o

def InvShiftRows(s):
    shr_o = []
    temp = [s[0][0],s[3][1],s[2][2],s[1][3]]
    shr_o.append(temp)
    temp = [s[1][0],s[0][1],s[3][2],s[2][3]]
    shr_o.append(temp)
    temp = [s[2][0],s[1][1],s[0][2],s[3][3]]
    shr_o.append(temp)
    temp = [s[3][0],s[2][1],s[1][2],s[0][3]]
    shr_o.append(temp)
    return shr_o

# MixColumns
def xtime(s):
    b = int(hex(s),16)
    b7 = (b >> 7) & 1
    b_1 = ((b << 1) | 0x0)%256
    b_2 = 0x1b & (b7 * 0b11111111)%256
    return b_1 ^ b_2

def x02(s):
    b = int(hex(s),16)
    b7 = (b >> 7) & 1
    b_1 = ((b << 1) | 0x0)%256
    b_2 = 0x1b & (b7 * 0b11111111)%256
    return b_1 ^ b_2

def x03(s):
    return x02(s) ^ s

def x04(s):
    return x02(x02(s))

def x08(s):
    return x02(x04(s))

def x09(s):
    return x08(s) ^ s

def x11(s):
    return x08(s) ^ x02(s) ^ s

def x13(s):
    return x08(s) ^ x04(s) ^ s

def x14(s):
    return x08(s) ^ x04(s) ^ x02(s)


def MixColumns(s):
    mxc_tmp = []
    for i in range(0,4):
        temp = s[i][0] ^ s[i][1] ^ s[i][2] ^ s[i][3]
        mxc_tmp.append(temp)

    mxc_o = []
    for i in range(0,4):
        mxc = []
        temp = s[i][0] ^ xtime(s[i][0] ^ s[i][1]) ^ mxc_tmp[i]
        mxc.append(temp)
        temp = s[i][1] ^ xtime(s[i][1] ^ s[i][2]) ^ mxc_tmp[i]
        mxc.append(temp)
        temp = s[i][2] ^ xtime(s[i][2] ^ s[i][3]) ^ mxc_tmp[i]
        mxc.append(temp)
        temp = s[i][3] ^ xtime(s[i][3] ^ s[i][0]) ^ mxc_tmp[i]
        mxc.append(temp)
        mxc_o.append(mxc)

    return mxc_o

def InvMixColumns(s):
    mxc_o = []
    for i in range(0,4):
        mxc = []
        temp = x14(s[i][0]) ^ x11(s[i][1]) ^ x13(s[i][2]) ^ x09(s[i][3])
        mxc.append(temp)
        temp = x09(s[i][0]) ^ x14(s[i][1]) ^ x11(s[i][2]) ^ x13(s[i][3])
        mxc.append(temp)
        temp = x13(s[i][0]) ^ x09(s[i][1]) ^ x14(s[i][2]) ^ x11(s[i][3])
        mxc.append(temp)
        temp = x11(s[i][0]) ^ x13(s[i][1]) ^ x09(s[i][2]) ^ x14(s[i][3])
        mxc.append(temp)
        mxc_o.append(mxc)

    return mxc_o

#AddRoundKey
def AddRoundKey(s, k):
    for i in range(4):
        for j in range(4):
            s[i][j] ^= k[i][j]

#KeyExpansion
def SubWord(sbox_type, word):
    w0 = word & 0xFF
    w1 = (word >> 8) & 0xFF
    w2 = (word >> 16) & 0xFF
    w3 = (word >> 24) & 0xFF

    w0 = sbox(sbox_type, w0)
    w1 = sbox(sbox_type, w1)
    w2 = sbox(sbox_type, w2)
    w3 = sbox(sbox_type, w3)

    w0_sub_o = (w3 << 24) | (w2 << 16) | (w1 << 8) | w0
    return w0_sub_o

def KeyExpansion(sbox_type, key):
    R = 10

    state = int(key,16)
    Rcon = 1
    ks_o = []
    ks_o.append(bytes2matrix_key(key))

    for i in range(1,11):

        Rcon_MSB = int(bin(Rcon)[2:].zfill(8)[0])

        if(Rcon_MSB):
            Rcon_new_2 = 0x1b
        else:
            Rcon_new_2 = 0x00

        Rcon_new_1 = ((Rcon & 0b01111111) << 1) | 0b0

        Rcon_new = Rcon_new_1 ^ Rcon_new_2

        w0 = (state >> 96) & 0xFFFFFFFF
        w1 = (state >> 64) & 0xFFFFFFFF
        w2 = (state >> 32) & 0xFFFFFFFF
        w3 = state & 0xFFFFFFFF

        wN = state & 0xFFFFFFFF
        wN_23_0 = wN & 0xFFFFFF
        wN_31_24 = (wN >> 24) & 0xFF
        w0_sub_i = ((wN_23_0 << 8) | wN_31_24) & 0xFFFFFFFF

        w0_sub_o = SubWord(sbox_type,w0_sub_i)

        w0_temp = ((((w0_sub_o >> 24) & 0xFF) ^ Rcon) << 24) | (w0_sub_o & 0xFFFFFF)

        w0_new = (w0 ^ w0_temp) & 0xFFFFFFFF
        w1_new = (w1 ^ w0_new) & 0xFFFFFFFF
        w2_new = (w2 ^ w1_new) & 0xFFFFFFFF
        w3_new = (w3 ^ w2_new) & 0xFFFFFFFF

        Rcon = Rcon_new
        ks = ((w0_new << 96) | (w1_new << 64) | (w2_new << 32) | w3_new)& 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF
        state = ks

        temp = hex(ks)[2:]

        ks_o.append(bytes2matrix_key(str(temp)))

    return ks_o


#Functions
def split_blocks(message):
        return [message[i:i+16] for i in range(0, len(message), 16)]

def bytes2matrix_key(text):
    text = text.zfill(32)
    hex_pairs = [text[i:i+2] for i in range(0, len(text), 2)]
    int_values = [int(hex_pair, 16) for hex_pair in hex_pairs]
    return [int_values[i:i+4] for i in range(0, len(int_values), 4)]

def bytes2matrix(text):
    return [list(text[i:i+4]) for i in range(0, len(text), 4)]

def matrix2bytes(matrix):
    return [element for row in matrix for element in row]
