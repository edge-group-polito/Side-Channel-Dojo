#
# This file performs forward AND backwards key scheduling. Can work from arbitrary
# key locations (i.e. first to last, last to first, etc.)
#
# Support AES-128 and AES-256 with selectable modified sbox (freyre_1, freyre_2, freyre_3, hussain_6, ozkaynak_1) 
#
from chipwhisperer.common.utils.util import camel_case_deprecated
from analyzer.attack.aes.sbox_modified_funcs import sbox_lut, inv_sbox_lut

# ROUND CONSTANT
rcon = [0x8d, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1b, 0x36,
        0x6c, 0xd8, 0xab, 0x4d, 0x9a, 0x2f, 0x5e, 0xbc, 0x63, 0xc6, 0x97,
        0x35, 0x6a, 0xd4, 0xb3, 0x7d, 0xfa, 0xef, 0xc5, 0x91, 0x39, 0x72,
        0xe4, 0xd3, 0xbd, 0x61, 0xc2, 0x9f, 0x25, 0x4a, 0x94, 0x33, 0x66,
        0xcc, 0x83, 0x1d, 0x3a, 0x74, 0xe8, 0xcb, 0x8d, 0x01, 0x02, 0x04,
        0x08, 0x10, 0x20, 0x40, 0x80, 0x1b, 0x36, 0x6c, 0xd8, 0xab, 0x4d,
        0x9a, 0x2f, 0x5e, 0xbc, 0x63, 0xc6, 0x97, 0x35, 0x6a, 0xd4, 0xb3,
        0x7d, 0xfa, 0xef, 0xc5, 0x91, 0x39, 0x72, 0xe4, 0xd3, 0xbd, 0x61,
        0xc2, 0x9f, 0x25, 0x4a, 0x94, 0x33, 0x66, 0xcc, 0x83, 0x1d, 0x3a,
        0x74, 0xe8, 0xcb, 0x8d, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40,
        0x80, 0x1b, 0x36, 0x6c, 0xd8, 0xab, 0x4d, 0x9a, 0x2f, 0x5e, 0xbc,
        0x63, 0xc6, 0x97, 0x35, 0x6a, 0xd4, 0xb3, 0x7d, 0xfa, 0xef, 0xc5,
        0x91, 0x39, 0x72, 0xe4, 0xd3, 0xbd, 0x61, 0xc2, 0x9f, 0x25, 0x4a,
        0x94, 0x33, 0x66, 0xcc, 0x83, 0x1d, 0x3a, 0x74, 0xe8, 0xcb, 0x8d,
        0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1b, 0x36, 0x6c,
        0xd8, 0xab, 0x4d, 0x9a, 0x2f, 0x5e, 0xbc, 0x63, 0xc6, 0x97, 0x35,
        0x6a, 0xd4, 0xb3, 0x7d, 0xfa, 0xef, 0xc5, 0x91, 0x39, 0x72, 0xe4,
        0xd3, 0xbd, 0x61, 0xc2, 0x9f, 0x25, 0x4a, 0x94, 0x33, 0x66, 0xcc,
        0x83, 0x1d, 0x3a, 0x74, 0xe8, 0xcb, 0x8d, 0x01, 0x02, 0x04, 0x08,
        0x10, 0x20, 0x40, 0x80, 0x1b, 0x36, 0x6c, 0xd8, 0xab, 0x4d, 0x9a,
        0x2f, 0x5e, 0xbc, 0x63, 0xc6, 0x97, 0x35, 0x6a, 0xd4, 0xb3, 0x7d,
        0xfa, 0xef, 0xc5, 0x91, 0x39, 0x72, 0xe4, 0xd3, 0xbd, 0x61, 0xc2,
        0x9f, 0x25, 0x4a, 0x94, 0x33, 0x66, 0xcc, 0x83, 0x1d, 0x3a, 0x74,
        0xe8, 0xcb ]


def g_func(inp, rcon, sb_type):
    #Step 1: change order
    newlist = [inp[1], inp[2], inp[3], inp[0]]

    #Step 2: s-box
    newlist = [sbox_lut(t, sb_type) for t in newlist]

    #Step 3: apply rcon
    newlist[0] ^= rcon

    return newlist


def h_func(inp, sb_type):
    #Step 1: s-box
    newlist = [sbox_lut(t, sb_type) for t in inp]

    return newlist


def xor(l1, l2):
    return [l1[i] ^ l2[i] for i in range(0, len(l1))]


def key_schedule_rounds(input_key, input_round, desired_round, sb_type):
    """Use key schedule to determine key for different round.

    When dealing with AES-256, inputkey is 16 bytes and inputround
    indicates round that bytes 0...15 are from.

    Args:
        input_key (list): List of bytes of starting key, 16/32 bytes
        input_round (int): Starting round number (i.e. 0 = first)
        desired_round (int): Desired round number (i.e. 10 = last for 16-byte)
        sb_type (str): SBox type to use 

    Returns:
         list: Key at desired round number. Can go forward or backwards.
    """

    #Some constants
    n = len(input_key)
    if n == 16:
        pass
    elif n == 32:
        desiredfull = desired_round
        desired_round = int(desired_round / 2)

        #Special case for inputround of 13, needed for 'final' round...
        if input_round != 13:
            if input_round % 2 == 1:
                raise ValueError("Input round must be divisible by 2")
            input_round = int(input_round / 2)
        else:
            if input_round <= desiredfull:
                if desiredfull < 13:
                    raise ValueError("Round = 13 only permissible for reverse")

                if desiredfull == 13:
                    return input_key[0:16]
                else:
                    return input_key[16:32]

    else:
        raise ValueError("Invalid keylength: %d"%n)

    rnd = input_round
    state = list(input_key)

    #Check if we are going forward or backwards
    while rnd < desired_round:
        rnd += 1

        #Forward algorithm, thus need at least one round
        state[0:4] = xor(state[0:4], g_func(state[(n-4):n], rcon[rnd],sb_type))
        for i in range(4, n, 4):
            if n == 32 and i == 16:
                inp = h_func(state[(i-4):i], sb_type)
            else:
                inp = state[(i - 4):i]
            state[i:(i+4)] = xor(state[i:(i+4)], inp)

    while rnd > desired_round:
        #For AES-256 final-round is 13 as that includes 32 bytes
        #of key. Convert to round 12 then continue as usual...
        if n == 32 and rnd == 13:
            inputrnd = int(12/2)
            rnd = inputrnd
            oldstate = list(state[16:32])
            state[16:32] = state[0:16]

            for i in range(12, 0, -4):
                state[i:(i+4)] = xor(oldstate[i:(i+4)], oldstate[(i-4):i])
            state[0:4] = xor(oldstate[0:4], g_func(state[(n - 4):n], rcon[7], sb_type))

        if rnd == desired_round:
            break

        # Reverse algorithm, thus need at least one round
        for i in range(n-4, 0, -4):
            if n == 32 and i == 16:
                inp = h_func(state[(i-4):i], sb_type)
            else:
                inp = state[(i - 4):i]
            state[i:(i+4)] = xor(state[i:(i+4)], inp)
        state[0:4] = xor(state[0:4], g_func(state[(n - 4):n], rcon[rnd], sb_type))
        rnd -= 1

    #For AES-256, we use half the generated key at once...
    if n == 32:
        if desiredfull % 2:
            state = state[16:32]
        else:
            state = state[0:16]

    #Return answer
    return state

keyScheduleRounds = camel_case_deprecated(key_schedule_rounds)

def test():
    #Manual tests right now - need to automate this.

    ##### AES-128 Tests
    print("**********AES-128 Tests***************")

    ik = [0]*16
    for i in range(0, 11):
        result = keyScheduleRounds(ik, 0, i)
        print((" ".join(["%2x"%d for d in result])))
        ok = result

    # 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
    # 62 63 63 63 62 63 63 63 62 63 63 63 62 63 63 63
    # 9b 98 98 c9 f9 fb fb aa 9b 98 98 c9 f9 fb fb aa
    # 90 97 34 50 69 6c cf fa f2 f4 57 33 0b 0f ac 99
    # ee 06 da 7b 87 6a 15 81 75 9e 42 b2 7e 91 ee 2b
    # 7f 2e 2b 88 f8 44 3e 09 8d da 7c bb f3 4b 92 90
    # ec 61 4b 85 14 25 75 8c 99 ff 09 37 6a b4 9b a7
    # 21 75 17 87 35 50 62 0b ac af 6b 3c c6 1b f0 9b
    # 0e f9 03 33 3b a9 61 38 97 06 0a 04 51 1d fa 9f
    # b1 d4 d8 e2 8a 7d b9 da 1d 7b b3 de 4c 66 49 41
    #b4 ef 5b cb 3e 92 e2 11 23 e9 51 cf 6f 8f 18 8e

    print("")

    for i in range(0, 11):  # 10 Rounds
        result = keyScheduleRounds(ok, 10, i)
        print((" ".join(["%2x" % d for d in result])))

    ##### AES-256 Tests
    print("**********AES-256 Tests***************")

    ik = [0]*32
    for i in range(0, 15):  # 14 Rounds
        result = keyScheduleRounds(ik, 0, i)
        print((" ".join(["%02x"%d for d in result])))

    # 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
    # 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
    # 62 63 63 63 62 63 63 63 62 63 63 63 62 63 63 63
    # aa fb fb fb aa fb fb fb aa fb fb fb aa fb fb fb
    # 6f 6c 6c cf 0d 0f 0f ac 6f 6c 6c cf 0d 0f 0f ac
    # 7d 8d 8d 6a d7 76 76 91 7d 8d 8d 6a d7 76 76 91
    # 53 54 ed c1 5e 5b e2 6d 31 37 8e a2 3c 38 81 0e
    # 96 8a 81 c1 41 fc f7 50 3c 71 7a 3a eb 07 0c ab
    # 9e aa 8f 28 c0 f1 6d 45 f1 c6 e3 e7 cd fe 62 e9
    # 2b 31 2b df 6a cd dc 8f 56 bc a6 b5 bd bb aa 1e
    # 64 06 fd 52 a4 f7 90 17 55 31 73 f0 98 cf 11 19
    # 6d bb a9 0b 07 76 75 84 51 ca d3 31 ec 71 79 2f
    # e7 b0 e8 9c 43 47 78 8b 16 76 0b 7b 8e b9 1a 62
    # 74 ed 0b a1 73 9b 7e 25 22 51 ad 14 ce 20 d4 3b
    #10 f8 0a 17 53 bf 72 9c 45 c9 79 e7 cb 70 63 85

    print("")

    ik = [0x74 ,0xed ,0x0b ,0xa1 ,0x73 ,0x9b ,0x7e ,0x25 ,0x22 ,
          0x51 ,0xad ,0x14 ,0xce ,0x20 ,0xd4 ,0x3b ,0x10 ,0xf8 ,
          0x0a ,0x17 ,0x53 ,0xbf ,0x72 ,0x9c ,0x45 ,0xc9 ,0x79 ,
          0xe7 ,0xcb ,0x70 ,0x63, 0x85]

    for i in range(0, 14):
        result = keyScheduleRounds(ik, 13, i)
        print((" ".join(["%2x"%d for d in result])))

if __name__ == "__main__":
    test()