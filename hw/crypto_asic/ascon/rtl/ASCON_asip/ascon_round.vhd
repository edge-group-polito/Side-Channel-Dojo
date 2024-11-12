
library work;
	use work.ascon_globals.all;
	
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;  


entity ascon_round is

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
			x4_o		: out  std_logic_vector(63 downto 0)	);

end ascon_round;

architecture rtl of ascon_round is


  ----------------------------------------------------------------------------
  -- Internal signal declarations
  ----------------------------------------------------------------------------

 
  
begin  -- Rtl
 ascon_round :process (x0_i, x1_i, x2_i, x3_i, x4_i,C)
    constant Cuint64_t_0 : unsigned(63 downto 0) := (others => '0');
 
	variable x0 : unsigned(63 downto 0);
    variable x1 : unsigned(63 downto 0);
    variable x2 : unsigned(63 downto 0);
    variable x3 : unsigned(63 downto 0);
    variable x4 : unsigned(63 downto 0);
    variable xtemp : unsigned(63 downto 0);
    variable C64 : unsigned(63 downto 0);

begin


	 x0 :=unsigned( x0_i );
    x1 :=unsigned( x1_i );
    x2 :=unsigned( x2_i );
    x3 :=unsigned( x3_i );
    x4 :=unsigned( x4_i );
    C64 := Cuint64_t_0;
    C64(7 downto 0) := unsigned(C);
    x2 := (x2 xor C64);
    x0 := (x0 xor x4);
    x4 := (x4 xor x3);
    x2 := (x2 xor x1);
    xtemp := (x0 and (not x4));
    x0 := (x0 xor (x2 and (not x1)));
    x2 := (x2 xor (x4 and (not x3)));
    x4 := (x4 xor (x1 and (not x0)));
    x1 := (x1 xor (x3 and (not x2)));
    x3 := (x3 xor xtemp);
    x1 := (x1 xor x0);
    x3 := (x3 xor x2);
    x0 := (x0 xor x4);
    x2 := (not x2);
    x0 := (x0 xor (((shift_right(x0, 19) xor shift_left(x0, 45)) xor shift_right(x0, 28)) xor shift_left(x0, 36)));
    x1 := (x1 xor (((shift_right(x1, 61) xor shift_left(x1, 3)) xor shift_right(x1, 39)) xor shift_left(x1, 25)));
    x2 := (x2 xor (((shift_right(x2, 1) xor shift_left(x2, 63)) xor shift_right(x2, 6)) xor shift_left(x2, 58)));
    x3 := (x3 xor (((shift_right(x3, 10) xor shift_left(x3, 54)) xor shift_right(x3, 17)) xor shift_left(x3, 47)));
    x4 := (x4 xor (((shift_right(x4, 7) xor shift_left(x4, 57)) xor shift_right(x4, 41)) xor shift_left(x4, 23)));
    x0_o <= std_logic_vector ( x0 );
    x1_o <= std_logic_vector ( x1 );
    x2_o <= std_logic_vector ( x2 );
    x3_o <= std_logic_vector ( x3 );
    x4_o <= std_logic_vector ( x4 );

end process ascon_round;
end rtl;
