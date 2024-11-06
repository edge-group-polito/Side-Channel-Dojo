// Licensed under the Creative Commons 1.0 Universal License (CC0), see LICENSE
// for details.
//
// Author: Robert Primas (rprimas 'at' proton.me, https://rprimas.github.io)
//
// Implementation of the Ascon permutation (Ascon-p).
// Performs UROL rounds per clock cycle.

module asconp (
    input  logic [ 3:0] round_cnt,
    input  logic [63:0] x0_i,
    input  logic [63:0] x1_i,
    input  logic [63:0] x2_i,
    input  logic [63:0] x3_i,
    input  logic [63:0] x4_i,
    output logic [63:0] x0_o,
    output logic [63:0] x1_o,
    output logic [63:0] x2_o,
    output logic [63:0] x3_o,
    output logic [63:0] x4_o
);

  logic [63:0] x0_const_add, x0_aff1, x0_chi, x0_aff2;
  logic [63:0] x1_const_add, x1_aff1, x1_chi, x1_aff2;
  logic [63:0] x2_const_add, x2_aff1, x2_chi, x2_aff2;
  logic [63:0] x3_const_add, x3_aff1, x3_chi, x3_aff2;
  logic [63:0] x4_const_add, x4_aff1, x4_chi, x4_aff2;
  logic [1:0][63:0] x0, x1, x2, x3, x4;

  assign x0[0] = x0_i;
  assign x1[0] = x1_i;
  assign x2[0] = x2_i;
  assign x3[0] = x3_i;
  assign x4[0] = x4_i;

  genvar i;
  generate
    for (i = 0; i < 1; i++) begin
      // constant addition
      assign x0_const_add = x0[i];
      assign x1_const_add = x1[i];
      assign x2_const_add = x2[i] ^ (8'hf0 - (round_cnt * 1 + i) * 8'h10 + (round_cnt * 1 + i) * 8'h01);
      assign x3_const_add = x3[i];
      assign x4_const_add = x4[i];

      `ifdef ASCON_HW
        sub_layer_hw sub_layer_inst(
          .x0_i   (x0_const_add),
          .x1_i   (x1_const_add),
          .x2_i   (x2_const_add),
          .x3_i   (x3_const_add),
          .x4_i   (x4_const_add),
          .x0_o   (x0_aff2),
          .x1_o   (x1_aff2),
          .x2_o   (x2_aff2),
          .x3_o   (x3_aff2),
          .x4_o   (x4_aff2)
        );
      `else
        sub_layer_lut sub_layer_inst(
          .x0_i   (x0_const_add),
          .x1_i   (x1_const_add),
          .x2_i   (x2_const_add),
          .x3_i   (x3_const_add),
          .x4_i   (x4_const_add),
          .x0_o   (x0_aff2),
          .x1_o   (x1_aff2),
          .x2_o   (x2_aff2),
          .x3_o   (x3_aff2),
          .x4_o   (x4_aff2)
        );
      `endif

      // linear layer
      assign x0[i+1] = x0_aff2 ^ {x0_aff2[18:0], x0_aff2[63:19]} ^ {x0_aff2[27:0], x0_aff2[63:28]};
      assign x1[i+1] = x1_aff2 ^ {x1_aff2[60:0], x1_aff2[63:61]} ^ {x1_aff2[38:0], x1_aff2[63:39]};
      assign x2[i+1] = x2_aff2 ^ {x2_aff2[0:0], x2_aff2[63:01]} ^ {x2_aff2[05:0], x2_aff2[63:06]};
      assign x3[i+1] = x3_aff2 ^ {x3_aff2[9:0], x3_aff2[63:10]} ^ {x3_aff2[16:0], x3_aff2[63:17]};
      assign x4[i+1] = x4_aff2 ^ {x4_aff2[6:0], x4_aff2[63:07]} ^ {x4_aff2[40:0], x4_aff2[63:41]};
    end
  endgenerate

  assign x0_o = x0[1];
  assign x1_o = x1[1];
  assign x2_o = x2[1];
  assign x3_o = x3[1];
  assign x4_o = x4[1];

endmodule
