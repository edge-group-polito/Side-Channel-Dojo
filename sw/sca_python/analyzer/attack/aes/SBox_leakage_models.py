import chipwhisperer.analyzer as cwa
import analyzer.attack.aes.sbox_modified_funcs as smf
from analyzer.attack.aes.key_schedule import key_schedule_rounds


class AES128SboxResistantLeakageModels():
    """Contains the leakage models for modified AES with resistant SBox."""

    INVSHIFT_undo = [0, 5, 10, 15, 4, 9, 14, 3, 8, 13, 2, 7, 12, 1, 6, 11]

    
    class LastroundStateDiff_SBoxModified(cwa.AESLeakageHelper):
        """Leakage model for the last round state difference with modified SBox"""
        name = 'HD: AES Last-Round State Diff with SBox Modified'    

        def __init__(self, sbox):
            self.sb_type = sbox

        def leakage(self, pt, ct, key, bnum):
            # HD Leakage of AES State between 9th and 10th Round
            st10 = ct[self.INVSHIFT_undo[bnum]]
            st9 = smf.inv_sbox_lut(ct[bnum] ^ key[bnum], self.sb_type)
            return (st9 ^ st10)

        def process_known_key(self, inpkey):
            return key_schedule_rounds(inpkey, 0, 10, self.sb_type)
    
    def LastroundStateDiff_ModifiedSbox(self, sb_type):
        """Hamming distance between rounds 9 and 10 with modified SBox"""
        return cwa.leakage_models.new_model(self.LastroundStateDiff_SBoxModified(sb_type))
    
    class FirstRound_SBoxModified_output(cwa.AESLeakageHelper):
        """Leakage model for the first round state difference with modified SBox"""
        name = 'HW: AES SBox_modified Output, First Round (Enc)'
        c_model_enum_value = 1
        c_model_enum_name = 'LEAK_HW_SBOXOUT_MODIFIED_FIRSTROUND'

        def __init__(self, sbox):
            self.sb_type = sbox
            
        def leakage(self, pt, ct, key, bnum):
            # HD Leakage of AES First round State
            return smf.sbox_lut(pt[bnum] ^ key[bnum], self.sb_type)
    
    def FirstRound_ModifiedSbox_Output(self, sb_type):
        """Hamming distance first round with modified SBox"""
        return cwa.leakage_models.new_model(self.FirstRound_SBoxModified_output(sb_type))

    