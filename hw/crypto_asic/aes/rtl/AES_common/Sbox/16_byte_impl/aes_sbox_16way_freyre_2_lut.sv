module aes_sbox_16way_freyre_2_lut (
    input   logic [127:0]   state_i,
    input   logic           dec,
    output  logic [127:0]   state_o
);

aes_sbox_lut_freyre_2 sbox_inst00 (
    .byte_in (state_i[7:0]),
    .dec     (dec),
    .byte_out(state_o[7:0])
  );
  aes_sbox_lut_freyre_2 sbox_inst01 (
    .byte_in (state_i[15:8]),
    .dec     (dec),
    .byte_out(state_o[15:8])
  );
  aes_sbox_lut_freyre_2 sbox_inst02 (
    .byte_in (state_i[23:16]),
    .dec     (dec),
    .byte_out(state_o[23:16])
  );
  aes_sbox_lut_freyre_2 sbox_inst03 (
    .byte_in (state_i[31:24]),
    .dec     (dec),
    .byte_out(state_o[31:24])
  );
  aes_sbox_lut_freyre_2 sbox_inst04 (
    .byte_in (state_i[39:32]),
    .dec     (dec),
    .byte_out(state_o[39:32])
  );
  aes_sbox_lut_freyre_2 sbox_inst05 (
    .byte_in (state_i[47:40]),
    .dec     (dec),
    .byte_out(state_o[47:40])
  );
  aes_sbox_lut_freyre_2 sbox_inst06 (
    .byte_in (state_i[55:48]),
    .dec     (dec),
    .byte_out(state_o[55:48])
  );
  aes_sbox_lut_freyre_2 sbox_inst07 (
    .byte_in (state_i[63:56]),
    .dec     (dec),
    .byte_out(state_o[63:56])
  );
  aes_sbox_lut_freyre_2 sbox_inst08 (
    .byte_in (state_i[71:64]),
    .dec     (dec),
    .byte_out(state_o[71:64])
  );
  aes_sbox_lut_freyre_2 sbox_inst09 (
    .byte_in (state_i[79:72]),
    .dec     (dec),
    .byte_out(state_o[79:72])
  );
  aes_sbox_lut_freyre_2 sbox_inst10 (
    .byte_in (state_i[87:80]),
    .dec     (dec),
    .byte_out(state_o[87:80])
  );
  aes_sbox_lut_freyre_2 sbox_inst11 (
    .byte_in (state_i[95:88]),
    .dec     (dec),
    .byte_out(state_o[95:88])
  );
  aes_sbox_lut_freyre_2 sbox_inst12 (
    .byte_in (state_i[103:96]),
    .dec     (dec),
    .byte_out(state_o[103:96])
  );
  aes_sbox_lut_freyre_2 sbox_inst13 (
    .byte_in (state_i[111:104]),
    .dec     (dec),
    .byte_out(state_o[111:104])
  );
  aes_sbox_lut_freyre_2 sbox_inst14 (
    .byte_in (state_i[119:112]),
    .dec     (dec),
    .byte_out(state_o[119:112])
  );
  aes_sbox_lut_freyre_2 sbox_inst15 (
    .byte_in (state_i[127:120]),
    .dec     (dec),
    .byte_out(state_o[127:120])
  );
endmodule
