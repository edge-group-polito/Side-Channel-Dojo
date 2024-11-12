`timescale 1ns/1ps

module ascon_init
    (
        input wire               i_clk,
        input wire [127:0]       i_key,
        input wire [127:0]       i_nonce,
        input wire               i_load,
        output reg               o_busy,
        output reg [319:0]       o_state
    );

    reg [63:0]      iv;
    reg [319:0]     initial_state;
    reg [319:0]     data_in;
    wire [319:0]    data_out;
    reg [3:0]       round;
    wire [3:0]      round_inc = round + 1;
  

    localparam ASCON_ENCRYPT = 0;
    localparam ASCON_FINISH = 1;

    reg [1:0]       fsm;

    asconp asconp(
      .round_cnt      (round),
      .x0_i           (data_in[319:256]),
      .x1_i           (data_in[255:192]),
      .x2_i           (data_in[191:128]),
      .x3_i           (data_in[127:64]),
      .x4_i           (data_in[63:0]),
      .x0_o           (data_out[319:256]),
      .x1_o           (data_out[255:192]),
      .x2_o           (data_out[191:128]),
      .x3_o           (data_out[127:64]),
      .x4_o           (data_out[63:0])
    );

    initial begin
        iv = 64'h80400c0600000000;
    end

    always @(*) begin
        initial_state = {iv, i_key, i_nonce};
    end

    always @(posedge i_clk) begin
    o_busy <= 0;
    if (i_load) begin
      fsm    <= ASCON_ENCRYPT;
      round  <= 0;
      o_busy <= 1;
      data_in <= initial_state;
    end else if (o_busy) begin
      o_busy <= 1;
      case (fsm)
        ASCON_ENCRYPT: begin
          round <= round_inc;
          o_busy <= 1;
          data_in <= data_out;
          if (round == 10) begin
            fsm <= ASCON_FINISH;
          end
        end
        ASCON_FINISH: begin
          o_busy <= 0;
	        o_state <= data_out;
        end
      endcase
    end
  end

    

endmodule
