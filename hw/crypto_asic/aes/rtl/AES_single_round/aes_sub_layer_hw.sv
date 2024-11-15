module aes_sub_layer_hw(
    input   logic [127:0]   state_i,
    input   logic           dec,
    output  logic [127:0]   state_o
);

aes_sbox sbox_inst00 (
    .U  (state_i[7:0]),
    .dec(dec),
    .S  (state_o[7:0])
  );
  aes_sbox sbox_inst01 (
    .U  (state_i[15:8]),
    .dec(dec),
    .S  (state_o[15:8])
  );
  aes_sbox sbox_inst02 (
    .U  (state_i[23:16]),
    .dec(dec),
    .S  (state_o[23:16])
  );
  aes_sbox sbox_inst03 (
    .U  (state_i[31:24]),
    .dec(dec),
    .S  (state_o[31:24])
  );
  aes_sbox sbox_inst04 (
    .U  (state_i[39:32]),
    .dec(dec),
    .S  (state_o[39:32])
  );
  aes_sbox sbox_inst05 (
    .U  (state_i[47:40]),
    .dec(dec),
    .S  (state_o[47:40])
  );
  aes_sbox sbox_inst06 (
    .U  (state_i[55:48]),
    .dec(dec),
    .S  (state_o[55:48])
  );
  aes_sbox sbox_inst07 (
    .U  (state_i[63:56]),
    .dec(dec),
    .S  (state_o[63:56])
  );
  aes_sbox sbox_inst08 (
    .U  (state_i[71:64]),
    .dec(dec),
    .S  (state_o[71:64])
  );
  aes_sbox sbox_inst09 (
    .U  (state_i[79:72]),
    .dec(dec),
    .S  (state_o[79:72])
  );
  aes_sbox sbox_inst10 (
    .U  (state_i[87:80]),
    .dec(dec),
    .S  (state_o[87:80])
  );
  aes_sbox sbox_inst11 (
    .U  (state_i[95:88]),
    .dec(dec),
    .S  (state_o[95:88])
  );
  aes_sbox sbox_inst12 (
    .U  (state_i[103:96]),
    .dec(dec),
    .S  (state_o[103:96])
  );
  aes_sbox sbox_inst13 (
    .U  (state_i[111:104]),
    .dec(dec),
    .S  (state_o[111:104])
  );
  aes_sbox sbox_inst14 (
    .U  (state_i[119:112]),
    .dec(dec),
    .S  (state_o[119:112])
  );
  aes_sbox sbox_inst15 (
    .U  (state_i[127:120]),
    .dec(dec),
    .S  (state_o[127:120])
  );
endmodule
