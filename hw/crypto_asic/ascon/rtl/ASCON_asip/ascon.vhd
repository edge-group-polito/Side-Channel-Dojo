--////////////////////////////////////////////////////////////////////////////////////////
-- Engineer:      Federica Bader                      //
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

entity ascon is
    port (
        clk     : in  std_logic;
        rst_n   : in  std_logic;
        start   : in std_logic;
        din     : in  std_logic_vector(319 downto 0);
	      number_rounds_in: in std_logic_vector (31 downto 0); 
        dout    : out std_logic_vector(319 downto 0);
        done  : out std_logic);
end ascon;



architecture rtl of ascon is
  --components
  component ascon_dp
    port (
        clk     : in  std_logic;
        rst_n   : in  std_logic;
        start_i : in std_logic;
        din     : in  std_logic_vector(319 downto 0);
		start_cnt_i: in  unsigned(3 downto 0);
        ready_o : out std_logic;
        dout    : out std_logic_vector(319 downto 0));
  end component;

  component ascon_cu
    port (
      clk_i      : in std_logic;
      rst_ni     : in std_logic;
      start_i    : in std_logic;
      ready_dp_i : in std_logic;
	  number_permutations_i: in std_logic_vector (1 downto 0); 
	  start_cnt_o: out unsigned(3 downto 0);
      start_dp_o : out std_logic;
      status_o   : out std_logic;
      ascon: out std_logic);
    end component; 
      
 -- interface with RF in ascon_top
    ----------------------------------------------------------------------------
   -- Internal signal declarations
    ----------------------------------------------------------------------------
  signal start_dp, permutation_computed : std_logic;
  signal start_cnt : unsigned(3 downto 0);
  signal status : std_logic;
  signal number_permutations: std_logic_vector (1 downto 0); 
  begin -- Rtl
    -- port map
    DP : ascon_dp port map (
      clk        => clk,
      rst_n      => rst_n,
      start_i    => start_dp,
      din        => din,
	  start_cnt_i=> start_cnt,
      ready_o    => permutation_computed,
      dout       => dout);
      
    CU : ascon_cu port map (
      clk_i        => clk,
      rst_ni       => rst_n,
      start_i      => start,
      ready_dp_i   => permutation_computed, 
	  number_permutations_i => number_permutations, 
	  start_cnt_o  => start_cnt,
      start_dp_o   => start_dp,
      status_o       => status,
      ascon  => done);
    
	number_of_rounds: process(number_rounds_in) begin
		if(number_rounds_in(3 downto 0) = "0110") then
			number_permutations <= "01"; --six
		elsif (number_rounds_in(3 downto 0) = "1000") then
			number_permutations <= "10"; --eight
		else
		    number_permutations <= "11";
		end if;
	end process number_of_rounds;
end rtl;
      
  

  
