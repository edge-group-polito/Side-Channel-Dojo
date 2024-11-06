module sub_layer_lut(
    input   logic [63:0]    x0_i,
    input   logic [63:0]    x1_i,
    input   logic [63:0]    x2_i,
    input   logic [63:0]    x3_i,
    input   logic [63:0]    x4_i,
    output  logic [63:0]    x0_o,
    output  logic [63:0]    x1_o,
    output  logic [63:0]    x2_o,
    output  logic [63:0]    x3_o,
    output  logic [63:0]    x4_o
);

    genvar i;
    generate
        for (i = 0; i < 64; i++) begin
            `ifdef SBOX_BILGIN
                sbox_bilgin sbox_inst(
                    .byte_in        ({x0_i[i], x1_i[i], x2_i[i], x3_i[i], x4_i[i]}),
                    .byte_out       ({x0_o[i], x1_o[i], x2_o[i], x3_o[i], x4_o[i]})
                );
            `elsif SBOX_ALLOUZI
                sbox_allouzi sbox_inst(
                    .byte_in        ({x0_i[i], x1_i[i], x2_i[i], x3_i[i], x4_i[i]}),
                    .byte_out       ({x0_o[i], x1_o[i], x2_o[i], x3_o[i], x4_o[i]})
                );
            `elsif SBOX_LU_4
                sbox_lu_4 sbox_inst(
                    .byte_in        ({x0_i[i], x1_i[i], x2_i[i], x3_i[i], x4_i[i]}),
                    .byte_out       ({x0_o[i], x1_o[i], x2_o[i], x3_o[i], x4_o[i]})
                );
            `elsif SBOX_LU_5
                sbox_lu_5 sbox_inst(
                    .byte_in        ({x0_i[i], x1_i[i], x2_i[i], x3_i[i], x4_i[i]}),
                    .byte_out       ({x0_o[i], x1_o[i], x2_o[i], x3_o[i], x4_o[i]})
                );
            `elsif SBOX_LU_6
                sbox_lu_6 sbox_inst(
                    .byte_in        ({x0_i[i], x1_i[i], x2_i[i], x3_i[i], x4_i[i]}),
                    .byte_out       ({x0_o[i], x1_o[i], x2_o[i], x3_o[i], x4_o[i]})
                );
            `elsif SBOX_LU_7
                sbox_lu_7 sbox_inst(
                    .byte_in        ({x0_i[i], x1_i[i], x2_i[i], x3_i[i], x4_i[i]}),
                    .byte_out       ({x0_o[i], x1_o[i], x2_o[i], x3_o[i], x4_o[i]})
                );
            `else
                sbox_ascon sbox_inst(
                    .byte_in        ({x0_i[i], x1_i[i], x2_i[i], x3_i[i], x4_i[i]}),
                    .byte_out       ({x0_o[i], x1_o[i], x2_o[i], x3_o[i], x4_o[i]})
                );
            `endif


        end
    endgenerate



endmodule
