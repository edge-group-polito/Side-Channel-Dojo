sbox_type = ["aes",
             "freyre_1",
             "freyre_2",
             "freyre_3",
             "hussain_6",
             "ozkaynak_1"]


for i in range(0,6):
    file_name_py = "./AES_python/results/ciphertext_sbox_" + sbox_type[i] + ".txt"
    file_name_questa = "../tb/common/output_data_AES_pipeline/output_data_" + sbox_type[i] + ".txt"

    k = 1
    with open(file_name_py, "r") as python_file:
        with open(file_name_questa, "r") as questa_file:
            with open("simulation_results_aes_pipeline.txt", 'w') as output_file:
                for python_line, questa_line in zip(python_file, questa_file):
                    python_line = python_line[65:98]
                    questa_line = questa_line[97:130]
                    if(python_line != questa_line):
                        output_line = "[" + sbox_type[i] + "]" + ": Line " + str(k) + " have different ciphertext:\n" + python_line + " " + questa_line
                        print(output_line, file=output_file)
                        print(output_line)
                    k += 1

