module ks_sub_layer_hw(
    input   logic [31:0]   state_i,
    output  logic [31:0]   state_o
);

aes_sbox ks_inst0 (
    .U  (state_i[7:0]),
    .dec(dec),
    .S  (state_o[7:0])
  );
  aes_sbox ks_inst1 (
    .U  (state_i[15:8]),
    .dec(dec),
    .S  (state_o[15:8])
  );
  aes_sbox ks_inst2 (
    .U  (state_i[23:16]),
    .dec(dec),
    .S  (state_o[23:16])
  );
  aes_sbox ks_inst3 (
    .U  (state_i[31:24]),
    .dec(dec),
    .S  (state_o[31:24])
  );

  endmodule