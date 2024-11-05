//////////////////////////////////////////////////////////////////////////////////////////
// Engineer:      Federica Bader                       //
//                                                                                      //
// Design Name:    Top level module                                                     //
// Project Name:   TYRCA:                                                               //
//                 Tightly-coupled Accelerator for RISC-V with Code-based Algorithms    //
// File name:      ascon.sv        		                                            //
// Language:       SystemVerilog                                                        //
//                                                                                      //
// Description:    TYRCA ascon components.                                             //
//                                                                                      //
//////////////////////////////////////////////////////////////////////////////////////////

module ascon_cu (
     input logic  clk_i,
     input logic  rst_ni,
     input logic  start_i,
     input logic  ready_dp_i, 
	 input logic  [1:0] number_permutations_i,
	 output logic [3:0] start_cnt_o,
     output logic start_dp_o,
     output logic status_o,
     output logic ascon
   );


   parameter wait_start = 0,
             do_permutation = 1,
             permutation_finished = 2;
   
   reg[3:0]  			       counter;
 			       
   
   reg [1:0] 			       State, State_next;
   
   logic [3:0] six_perm,eight_perm,twelve_perm, start_cnt;
 	
	
	assign six_perm    = 4'b0110;
	assign eight_perm  = 4'b0100;
	assign twelve_perm = 4'b0000;
 

   // State reg
   always_ff @(posedge clk_i) begin
      if ( !rst_ni) begin
	 State <= wait_start;
	 counter <= 0;
      end else if ( State_next == do_permutation) begin 
		counter <= counter+1;
	  	 if (start_i && ready_dp_i) begin 
		counter<=start_cnt;
		end
  	end
	State <= State_next;
      
   end 

   // Comb logic      
   always_comb begin
      case (State)
	wait_start : begin
	   ascon = 0;
	   status_o = 0;
	   
	   if (start_i && ready_dp_i) begin
	      start_dp_o = 1;
		start_cnt_o = start_cnt;
	      State_next = do_permutation;
	   end else begin
	      start_dp_o = 0;
	      State_next = wait_start;
	      start_cnt_o = 0;	    
	   end
	end
	do_permutation : begin
	   start_dp_o = 0;
	   status_o = 0;
	   ascon = 0;
	   if (counter == 11) begin
	      //din_ascon_o <= 0;
	      State_next = permutation_finished;
	   end else begin
	      State_next = do_permutation;
	   end
        end
	permutation_finished : begin
	   start_dp_o = 0;
	   status_o = 1;
	   ascon = 1;
	   State_next = wait_start;
        end 
	default : begin
	   start_dp_o = 0;
	   status_o = 0;
	   ascon = 0;
	   State_next = wait_start;
	end
   endcase
   end // always_comb @



 
  always @(number_permutations_i) begin  //-- process count_number
        if (number_permutations_i == 2'b01)
		start_cnt = six_perm;
		  else if (number_permutations_i == 2'b10)
					start_cnt = eight_perm;
		  else	start_cnt = twelve_perm;
		  
	end //end comb
	
	
	
	
   endmodule : ascon_cu

	    
      
	 
	 
 
