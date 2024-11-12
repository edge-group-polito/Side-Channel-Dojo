
library work;
    use work.ascon_globals.all;
    
library ieee;
use ieee.std_logic_1164.all;
use ieee.std_logic_arith.all;   


entity ascon_round_constants_gen is
port(
    round_number: in unsigned(3 downto 0);
    round_constant_signal_out    : out std_logic_vector(7 downto 0));
end ascon_round_constants_gen;

architecture rtl of ascon_round_constants_gen is


  ----------------------------------------------------------------------------
  -- Internal signal declarations
  ----------------------------------------------------------------------------

 
  signal round_constant_signal: std_logic_vector(7 downto 0);
 
  
begin  -- Rtl

round_constants : process (round_number)
begin
    case round_number is
            when "0000" => round_constant_signal <= X"f0" ;
        when "0001" => round_constant_signal <= X"e1" ;
        when "0010" => round_constant_signal <= X"d2" ;
        when "0011" => round_constant_signal <= X"c3" ;
        when "0100" => round_constant_signal <= X"b4" ;
        when "0101" => round_constant_signal <= X"a5" ;
        when "0110" => round_constant_signal <= X"96" ;
        when "0111" => round_constant_signal <= X"87" ;
        when "1000" => round_constant_signal <= X"78" ;
        when "1001" => round_constant_signal <= X"69" ;
        when "1010" => round_constant_signal <= X"5a" ;
        when "1011" => round_constant_signal <= X"4b" ;
 
           
        when others => round_constant_signal <=(others => '0');
        end case;
end process round_constants;


round_constant_signal_out<=round_constant_signal;
end rtl;
