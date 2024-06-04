`timescale 1ns / 1ps
module tb_aes();

    int                 file_data_in;
    int                 file_data_out;
    int                 r;
    string              line_key;
    string              line_data;

    logic               clk_i;
    logic               load_i;
    logic [255:0]       key_i;
    logic [127:0]       data_i;
    logic [1:0]         size_i;
    logic               dec_i;
    logic [127:0]       data_o;
    logic               busy_o; 

    clock_generator CLK_GEN(
        .clk            (clk_i)
    );

    aes_core DUT(
        .clk            (clk_i),
        .load_i         (load_i),
        .key_i          (key_i),
        .data_i         (data_i),
        .size_i         (size_i),
        .dec_i          (dec_i),
        .data_o         (data_o),
        .busy_o         (busy_o)
    );

    initial size_i  =   2'b00;
    initial dec_i   =   1'b0;

    initial begin
        //Opening the file input_data.txt in read mode
        file_data_in = $fopen("../tb/input_data.txt", "r");
        if (file_data_in == 0) begin
            $display("Error in the opening of the file input_data.txt.");
            $finish;
        end

        //Opening the file output_data.txt in write mode
        file_data_out = $fopen("../tb/output_data.txt", "w");
        if (file_data_out == 0) begin
            $display("Error in the opening of the file output_data.txt.");
            $finish;
        end

        //Reading the file
        while (!$feof(file_data_in)) begin
            line_key = "";
            r = $fgets(line_key,file_data_in);
            $display("key: %s",line_key); 
            if (r > 0) begin
                r = $sscanf(line_key, "%h", key_i);
                if (r != 1) begin
                    $display("Errore nella lettura del dato: %s", line_key);
                end
            end

            line_data = "";
            r = $fgets(line_data,file_data_in);
            $display("data: %s",line_data); 
            if (r > 0) begin
                r = $sscanf(line_data, "%h", data_i);
                if (r != 1) begin
                    $display("Errore nella lettura del dato: %s", line_data);
                end
            end
            load_i = 1'b1;
            wait (busy_o == 1);
            load_i = 1'b0;
            wait (busy_o == 0);
            $fdisplay(file_data_out, "%h %h %h", key_i, data_i, data_o);
        end

        $fclose(file_data_in);
        $fclose(file_data_out);

        $finish;

    end

endmodule