--////////////////////////////////////////////////////////////////////////////////////////
-- Engineer:      Federica Bader                       //
--                                                                                      //
-- Design Name:    Top level module                                                     //
-- Project Name:   TYRCA:                                                               //
--                 Tightly-coupled Accelerator for RISC-V with Code-based Algorithms    //
-- File name:      ascon.sv        		                                            //
-- Language:       SystemVerilog                                                        //
--                                                                                      //
-- Description:    TYRCA ascon components.                                             //
--                                                                                      //
--////////////////////////////////////////////////////////////////////////////////////////


library work;
use work.ascon_globals.all;

library ieee;
use ieee.std_logic_1164.all;
use ieee.std_logic_arith.all;



entity ascon_dp is

    port (
        clk     : in  std_logic;
        rst_n   : in  std_logic;
        start_i : in std_logic; 
        din     : in  std_logic_vector(319 downto 0);
		start_cnt_i: in  unsigned(3 downto 0);
        ready_o : out std_logic;
        dout    : out std_logic_vector(319 downto 0));

end ascon_dp;

architecture rtl of ascon_dp is

    --components

    component ascon_round
        port (
			x0_i		: in  std_logic_vector(63 downto 0);
			x1_i		: in  std_logic_vector(63 downto 0);
			x2_i		: in  std_logic_vector(63 downto 0);
			x3_i		: in  std_logic_vector(63 downto 0);
			x4_i		: in  std_logic_vector(63 downto 0);			
			C    		: in std_logic_vector(7 downto 0); --round constant
			x0_o		: out  std_logic_vector(63 downto 0);
			x1_o		: out  std_logic_vector(63 downto 0);
			x2_o		: out  std_logic_vector(63 downto 0);
			x3_o		: out  std_logic_vector(63 downto 0);
			x4_o		: out  std_logic_vector(63 downto 0)			
			);

    end component;

    component ascon_round_constants_gen
        port (
            round_number: in unsigned(3 downto 0);
            round_constant_signal_out: out std_logic_vector(7 downto 0));
    end component;
 
   
    -- Internal signal declarations
    ----------------------------------------------------------------------------
	signal reg_data,round_in,round_out,permutation_computed_ext: std_logic_vector(319 downto 0);
	signal x0_i,x1_i,x2_i,x3_i,x4_i: std_logic_vector(63 downto 0);
	signal x0_o,x1_o,x2_o,x3_o,x4_o: std_logic_vector(63 downto 0);
    signal counter_nr_rounds : unsigned(3 downto 0);
    signal round_constant_signal: std_logic_vector(7 downto 0);
    signal compute_permutation : std_logic;
    signal permutation_computed : std_logic;


begin  -- Rtl

    -- port map

    round_map : ascon_round port map(
            x0_i	=> x0_i,
			x1_i    => x1_i,
			x2_i    => x2_i,
			x3_i    => x3_i,
			x4_i    => x4_i,
            C 		=> round_constant_signal,
            x0_o	=> x0_o,
			x1_o    => x1_o,
			x2_o    => x2_o,
			x3_o    => x3_o,
			x4_o    => x4_o
        );

    round_constants_gen: ascon_round_constants_gen port map(counter_nr_rounds,round_constant_signal);
    
    -- state register and counter of the number of rounds

    p_main : process (clk, rst_n)

    begin  -- process p_main
        if rst_n = '0' then                 -- asynchronous rst_n (active low)
			reg_data <= (others =>'0');
            counter_nr_rounds <= (others => '0');
            permutation_computed <='1';
            compute_permutation <= '0';
        elsif clk'event and clk = '1' then  -- rising clk edge

            if (start_i='1') then				--if there is a start signal
		reg_data <= (others =>'0');
                counter_nr_rounds <= start_cnt_i;
                compute_permutation<='1';
                permutation_computed<= '1';
            else
                if(compute_permutation ='1' and permutation_computed='1') then  --first perm
                    counter_nr_rounds<= counter_nr_rounds + 1;
                    permutation_computed<='0';
                    reg_data<= round_out;
                else --if we have to do more permutations
                    if( counter_nr_rounds < 11 and permutation_computed='0') then --if the single round is over
                        counter_nr_rounds <= counter_nr_rounds + 1;
                        reg_data<= round_out;

                    end if;
                    if( counter_nr_rounds = 11) then
                        permutation_computed<='1';
                        compute_permutation<='0';
			counter_nr_rounds<=(others =>'0');
			reg_data<= round_out;
                    end if;
                end if;

            end if;
        end if;
    end process p_main;

    
    --rate part
permutation_computed_ext <= (others => permutation_computed);

round_in<= reg_data xor (din and permutation_computed_ext);
	--if permutation_computed=0 -> reg_data xor 0 -> reg_data is reused
	--if permutation_computed=1 -> reg_data xor din -> din inside reg_data
	
--inputs
x4_i <= round_in((64*5)-1 downto (64*4));
x3_i <= round_in((64*4)-1 downto (64*3));
x2_i <= round_in((64*3)-1 downto (64*2));
x1_i <= round_in((64*2)-1 downto (64*1));
x0_i <= round_in((64*1)-1 downto (64*0));

--output
round_out <= x4_o & x3_o & x2_o & x1_o & x0_o;

 dout <= reg_data;

 ready_o<=permutation_computed; --datapath ready

end rtl;
