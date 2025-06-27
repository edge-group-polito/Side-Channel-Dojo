from operations_init import ascon_init as ascon  # type: ignore

sub_layer_type = [
     "hw",
     "lut_ascon",
     "lut_bilgin",
     "lut_allouzi",
     "lut_lu_4",
     "lut_lu_5",
     "lut_lu_6",
     "lut_lu_7"
]

file_name_results = "./results/init_results.txt"
file_name_KAT = "./KAT/LWC_AEAD_KAT_128_128.txt"

KAT_key = "000102030405060708090A0B0C0D0E0F"
KAT_nonce = "000102030405060708090A0B0C0D0E0F"

with open(file_name_results,'w') as results_file:
     with open(file_name_KAT,'r') as KAT_file:
          lines = []
          for i in range(8):
               key = bytes.fromhex(KAT_key)
               nonce = bytes.fromhex(KAT_nonce)

               state = ascon(key, nonce, "Ascon-128", sub_layer_type[i])

               print(sub_layer_type[i],file=results_file)
               print(state.hex(), file=results_file)
               print("",file=results_file)