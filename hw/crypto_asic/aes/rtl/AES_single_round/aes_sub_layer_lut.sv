module aes_sub_layer_lut(
    input   logic [127:0]   state_i,
    input   logic           dec,
    output  logic [127:0]   state_o
);

`ifdef SBOX_AZAM_1
    aes_sbox_16way_azam_1_lut sbox_16way_inst(
        .state_i(state_i),
        .dec(dec),
        .state_o(state_o)
    );
`elsif SBOX_AZAM_2
    aes_sbox_16way_azam_2_lut sbox_16way_inst(
        .state_i(state_i),
        .dec(dec),
        .state_o(state_o)
    );
`elsif SBOX_AZAM_3
    aes_sbox_16way_azam_3_lut sbox_16way_inst(
        .state_i(state_i),
        .dec(dec),
        .state_o(state_o)
    );
`elsif SBOX_FREYRE_1
    aes_sbox_16way_freyre_1_lut sbox_16way_inst(
        .state_i(state_i),
        .dec(dec),
        .state_o(state_o)
    );
`elsif SBOX_FREYRE_2
    aes_sbox_16way_freyre_2_lut sbox_16way_inst(
        .state_i(state_i),
        .dec(dec),
        .state_o(state_o)
    );
`elsif SBOX_FREYRE_3
    aes_sbox_16way_freyre_3_lut sbox_16way_inst(
        .state_i(state_i),
        .dec(dec),
        .state_o(state_o)
    );
`elsif SBOX_HUSSAIN_6
    aes_sbox_16way_hussain_6_lut sbox_16way_inst(
        .state_i(state_i),
        .dec(dec),
        .state_o(state_o)
    );
`elsif SBOX_OZKAYNAK_1
    aes_sbox_16way_ozkaynak_1_lut sbox_16way_inst(
        .state_i(state_i),
        .dec(dec),
        .state_o(state_o)
    );
`else
    aes_sbox_16way_rijandael_lut sbox_16way_inst(
        .state_i(state_i),
        .dec(dec),
        .state_o(state_o)
    );
`endif
endmodule
