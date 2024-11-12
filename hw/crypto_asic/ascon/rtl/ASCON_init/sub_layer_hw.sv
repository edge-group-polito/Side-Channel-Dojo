module sub_layer_hw(
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

    logic [63:0] x0_aff1, x0_chi;
    logic [63:0] x1_aff1, x1_chi;
    logic [63:0] x2_aff1, x2_chi;
    logic [63:0] x3_aff1, x3_chi;
    logic [63:0] x4_aff1, x4_chi;

    // 1st affine layer
    assign x0_aff1 = x0_i ^ x4_i;
    assign x1_aff1 = x1_i;
    assign x2_aff1 = x2_i ^ x1_i;
    assign x3_aff1 = x3_i;
    assign x4_aff1 = x4_i ^ x3_i;
    // non-linear chi layer
    assign x0_chi = x0_aff1 ^ ((~x1_aff1) & x2_aff1);
    assign x1_chi = x1_aff1 ^ ((~x2_aff1) & x3_aff1);
    assign x2_chi = x2_aff1 ^ ((~x3_aff1) & x4_aff1);
    assign x3_chi = x3_aff1 ^ ((~x4_aff1) & x0_aff1);
    assign x4_chi = x4_aff1 ^ ((~x0_aff1) & x1_aff1);
    // 2nd affine layer
    assign x0_o = x0_chi ^ x4_chi;
    assign x1_o = x1_chi ^ x0_chi;
    assign x2_o = ~x2_chi;
    assign x3_o = x3_chi ^ x2_chi;
    assign x4_o = x4_chi;


endmodule
