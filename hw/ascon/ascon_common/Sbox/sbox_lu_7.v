`default_nettype none `timescale 1ns / 1ps

module sbox_lu_7(
    input wire [4:0]       byte_in,
    output reg [4:0]       byte_out

);

    always @(*) begin
        case (byte_in)
            5'h00: byte_out = 5'h16;
            5'h01: byte_out = 5'h0f;
            5'h02: byte_out = 5'h10;
            5'h03: byte_out = 5'h09;
            5'h04: byte_out = 5'h1b;
            5'h05: byte_out = 5'h03;
            5'h06: byte_out = 5'h05;
            5'h07: byte_out = 5'h06;
            5'h08: byte_out = 5'h01;
            5'h09: byte_out = 5'h15;
            5'h0a: byte_out = 5'h1e;
            5'h0b: byte_out = 5'h12;
            5'h0c: byte_out = 5'h1c;
            5'h0d: byte_out = 5'h08;
            5'h0e: byte_out = 5'h0a;
            5'h0f: byte_out = 5'h1d;
            5'h10: byte_out = 5'h0e;
            5'h11: byte_out = 5'h00;
            5'h12: byte_out = 5'h0d;
            5'h13: byte_out = 5'h1a;
            5'h14: byte_out = 5'h18;
            5'h15: byte_out = 5'h14;
            5'h16: byte_out = 5'h11;
            5'h17: byte_out = 5'h1f;
            5'h18: byte_out = 5'h13;
            5'h19: byte_out = 5'h0c;
            5'h1a: byte_out = 5'h07;
            5'h1b: byte_out = 5'h19;
            5'h1c: byte_out = 5'h0b;
            5'h1d: byte_out = 5'h17;
            5'h1e: byte_out = 5'h04;
            5'h1f: byte_out = 5'h02;
        endcase
    end

endmodule

`default_nettype wire
