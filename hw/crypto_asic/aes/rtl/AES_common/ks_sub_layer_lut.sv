module ks_sub_layer_lut(
    input   logic [31:0]   state_i,
    output  logic [31:0]   state_o
);

`ifdef SBOX_AZAM_1
    aes_sbox_lut_azam_1 ks_inst0 (
        .byte_in (state_i[7:0]),
        .dec     (1'b0),
        .byte_out(state_o[7:0])
    );
    aes_sbox_lut_azam_1 ks_inst1 (
        .byte_in (state_i[15:8]),
        .dec     (1'b0),
        .byte_out(state_o[15:8])
    );
    aes_sbox_lut_azam_1 ks_inst2 (
        .byte_in (state_i[23:16]),
        .dec     (1'b0),
        .byte_out(state_o[23:16])
    );
    aes_sbox_lut_azam_1 ks_inst3 (
        .byte_in (state_i[31:24]),
        .dec     (1'b0),
        .byte_out(state_o[31:24])
    );
`elsif SBOX_AZAM_2
    aes_sbox_lut_azam_2 ks_inst0 (
        .byte_in (state_i[7:0]),
        .dec     (1'b0),
        .byte_out(state_o[7:0])
    );
    aes_sbox_lut_azam_2 ks_inst1 (
        .byte_in (state_i[15:8]),
        .dec     (1'b0),
        .byte_out(state_o[15:8])
    );
    aes_sbox_lut_azam_2 ks_inst2 (
        .byte_in (state_i[23:16]),
        .dec     (1'b0),
        .byte_out(state_o[23:16])
    );
    aes_sbox_lut_azam_2 ks_inst3 (
        .byte_in (state_i[31:24]),
        .dec     (1'b0),
        .byte_out(state_o[31:24])
    );
`elsif SBOX_AZAM_3
    aes_sbox_lut_azam_3 ks_inst0 (
        .byte_in (state_i[7:0]),
        .dec     (1'b0),
        .byte_out(state_o[7:0])
    );
    aes_sbox_lut_azam_3 ks_inst1 (
        .byte_in (state_i[15:8]),
        .dec     (1'b0),
        .byte_out(state_o[15:8])
    );
    aes_sbox_lut_azam_3 ks_inst2 (
        .byte_in (state_i[23:16]),
        .dec     (1'b0),
        .byte_out(state_o[23:16])
    );
    aes_sbox_lut_azam_3 ks_inst3 (
        .byte_in (state_i[31:24]),
        .dec     (1'b0),
        .byte_out(state_o[31:24])
    );
`elsif SBOX_FREYRE_1
    aes_sbox_lut_freyre_1 ks_inst0 (
        .byte_in (state_i[7:0]),
        .dec     (1'b0),
        .byte_out(state_o[7:0])
    );
    aes_sbox_lut_freyre_1 ks_inst1 (
        .byte_in (state_i[15:8]),
        .dec     (1'b0),
        .byte_out(state_o[15:8])
    );
    aes_sbox_lut_freyre_1 ks_inst2 (
        .byte_in (state_i[23:16]),
        .dec     (1'b0),
        .byte_out(state_o[23:16])
    );
    aes_sbox_lut_freyre_1 ks_inst3 (
        .byte_in (state_i[31:24]),
        .dec     (1'b0),
        .byte_out(state_o[31:24])
    );
`elsif SBOX_FREYRE_2
    aes_sbox_lut_freyre_2 ks_inst0 (
        .byte_in (state_i[7:0]),
        .dec     (1'b0),
        .byte_out(state_o[7:0])
    );
    aes_sbox_lut_freyre_2 ks_inst1 (
        .byte_in (state_i[15:8]),
        .dec     (1'b0),
        .byte_out(state_o[15:8])
    );
    aes_sbox_lut_freyre_2 ks_inst2 (
        .byte_in (state_i[23:16]),
        .dec     (1'b0),
        .byte_out(state_o[23:16])
    );
    aes_sbox_lut_freyre_2 ks_inst3 (
        .byte_in (state_i[31:24]),
        .dec     (1'b0),
        .byte_out(state_o[31:24])
    );
`elsif SBOX_FREYRE_3
    aes_sbox_lut_freyre_3 ks_inst0 (
        .byte_in (state_i[7:0]),
        .dec     (1'b0),
        .byte_out(state_o[7:0])
    );
    aes_sbox_lut_freyre_3 ks_inst1 (
        .byte_in (state_i[15:8]),
        .dec     (1'b0),
        .byte_out(state_o[15:8])
    );
    aes_sbox_lut_freyre_3 ks_inst2 (
        .byte_in (state_i[23:16]),
        .dec     (1'b0),
        .byte_out(state_o[23:16])
    );
    aes_sbox_lut_freyre_3 ks_inst3 (
        .byte_in (state_i[31:24]),
        .dec     (1'b0),
        .byte_out(state_o[31:24])
    );
`elsif SBOX_HUSSAIN_6
    aes_sbox_lut_hussain_6 ks_inst0 (
        .byte_in (state_i[7:0]),
        .dec     (1'b0),
        .byte_out(state_o[7:0])
    );
    aes_sbox_lut_hussain_6 ks_inst1 (
        .byte_in (state_i[15:8]),
        .dec     (1'b0),
        .byte_out(state_o[15:8])
    );
    aes_sbox_lut_hussain_6 ks_inst2 (
        .byte_in (state_i[23:16]),
        .dec     (1'b0),
        .byte_out(state_o[23:16])
    );
    aes_sbox_lut_hussain_6 ks_inst3 (
        .byte_in (state_i[31:24]),
        .dec     (1'b0),
        .byte_out(state_o[31:24])
    );
`elsif SBOX_OZKAYNAK_1
    aes_sbox_lut_ozkaynak_1 ks_inst0 (
        .byte_in (state_i[7:0]),
        .dec     (1'b0),
        .byte_out(state_o[7:0])
    );
    aes_sbox_lut_ozkaynak_1 ks_inst1 (
        .byte_in (state_i[15:8]),
        .dec     (1'b0),
        .byte_out(state_o[15:8])
    );
    aes_sbox_lut_ozkaynak_1 ks_inst2 (
        .byte_in (state_i[23:16]),
        .dec     (1'b0),
        .byte_out(state_o[23:16])
    );
    aes_sbox_lut_ozkaynak_1 ks_inst3 (
        .byte_in (state_i[31:24]),
        .dec     (1'b0),
        .byte_out(state_o[31:24])
    );
`else
    aes_sbox_lut_rijandael ks_inst0 (
        .byte_in (state_i[7:0]),
        .dec     (1'b0),
        .byte_out(state_o[7:0])
    );
    aes_sbox_lut_rijandael ks_inst1 (
        .byte_in (state_i[15:8]),
        .dec     (1'b0),
        .byte_out(state_o[15:8])
    );
    aes_sbox_lut_rijandael ks_inst2 (
        .byte_in (state_i[23:16]),
        .dec     (1'b0),
        .byte_out(state_o[23:16])
    );
    aes_sbox_lut_rijandael ks_inst3 (
        .byte_in (state_i[31:24]),
        .dec     (1'b0),
        .byte_out(state_o[31:24])
    );
`endif
endmodule
