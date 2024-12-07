import pandas as pd

def bytearray_to_bitlist(byte_array):
    """
    Converts a byte array to a list of bits.
    Args:
        byte_array (bytearray): The byte array to convert.
    Returns:
        bitlist: A list of bits.
    """
    bit_list = []
    for byte in byte_array:
        bits = bin(byte)[2:].zfill(8)
        bit_list.extend([int(bit) for bit in bits])
    return bit_list

def bit_to_hex(x0, x1, x2, x3, x4):
    """
    Converts 5 bits to a hexadecimal value.
    Args:
        x0, x1, x2, x3, x4 (int): The bits to convert.
    Returns:
        int: The hexadecimal value.
    """
    bitlist = []
    bitlist.append(x0)
    bitlist.append(x1)
    bitlist.append(x2)
    bitlist.append(x3)
    bitlist.append(x4)
    return int(''.join(str(bit) for bit in bitlist), 2)

def hex_to_bit(value):
    """
    Converts a hexadecimal value to a list of 5 bits.
    
    Args:
        value (int): The hexadecimal value to convert.
        
    Returns:
        list: A list of 5 bits representing the binary equivalent of the input value.
    """
    binary_string = format(value, f'05b')
    bitlist = [int(bit) for bit in binary_string]
    return bitlist

def convert_to_hex(bit_list):
    hex_string = ""
    
    for i in range(0, len(bit_list), 8):
        byte_bits = bit_list[i:i+8]
        byte_str = ''.join(str(bit) for bit in byte_bits)
        byte_int = int(byte_str, 2)
        hex_string += format(byte_int, '02X')
    
    return hex_string

def highlight_bits(x, key):
    """
    Highlights bits in a DataFrame by comparing them to the expected key.              Tabella con riga da 16 bit (e.g. 4 righe : 64)
    Args:
        x (pd.DataFrame): DataFrame containing bits to highlight.
        key (list): List of expected key values.
    Returns:
        pd.DataFrame: DataFrame with color-coded bits.
    """
    color_list = []
    for row_index in range(len(x)):
        color_row = [""] * 16
        if row_index % 2 == 1:
            for i in range(16):
                if x.iloc[row_index, i] == key[row_index // 2][i]:
                    color_row[i] = "color: green"
                else:
                    color_row[i] = "color: red"
        color_list.append(color_row)
    return pd.DataFrame(color_list, index=x.index, columns=x.columns)

def highlight_bits_2(x, key):
    """
    Highlights bits in a DataFrame by comparing them to the expected key. Attacato singolo bit colonna, 8 possibile valori (sottochiave 3 bit)
    Args:
        x (pd.DataFrame): DataFrame containing bits to highlight.
        key (list): List of expected key values.
    Returns:
        pd.DataFrame: DataFrame with color-coded bits.
    """
    color_list = []
    color_row = [""] * 4
    color_list.append(color_row)
    for row_index in range(1,len(x)):
        color_row = [""] * 4
        for i in range(3):
            if x.iloc[row_index, i] == key[i]:
                color_row[i] = "color: green"
            else:
                color_row[i] = "color: red"
        color_list.append(color_row)
    return pd.DataFrame(color_list, index=x.index, columns=x.columns)

def create_table(show_list):
    """
    Creates a table from a list of values. Attacco su 128 bit della chiave (16 bit per riga)
    Args:
        show_list (list): List of values to include in the table.
    Returns:
        pd.DataFrame: DataFrame representing the table.
    """
    table_data = []
    for row in range(8):
        row_data = list(range(127-16*row, 128-16*row - 17, -1))
        table_data.append(row_data)
        table_data.append(show_list[row])
    df = pd.DataFrame(table_data)
    return df

def create_table_2(best_guess, correlation, bitnum):
    """
    Creates a table from best guess values and their correlations. Attacco sulla colonna, riporta indice della chiave + ranking sottochiavi
    Attaccato x0
    Args:
        best_guess (list): List of best guess values.
        correlation (list): List of correlation values.
        bitnum (int): Bit number.
    Returns:
        pd.DataFrame: DataFrame representing the table.
    """
    table_data = []
    bit_number = ["k[" + str(((bitnum) % 64 ) + 64) + "]", "k[" + str(((19 + bitnum) % 64) + 64) + "]", "k[" + str(((28 + bitnum) % 64 ) + 64) + "]"] 
    bit_number.append("Correlation")
    table_data.append(bit_number)
    for i in range(len(best_guess)):
        table_line = []
        for b in range(len(best_guess[i])):
            table_line.append(best_guess[i][b])
        table_line.append(correlation[i])
        table_data.append(table_line)
    return pd.DataFrame(table_data)

def create_table_3(show_list):
    """
    Creates a table from a list of values. Attacco su 64 bit della chiave (16 bit per riga)
    Args:
        show_list (list): List of values to include in the table.
    Returns:
        pd.DataFrame: DataFrame representing the table.
    """
    table_data = []  
    for row in range(4):
        row_data = list(range(127-16*row, 128-16*row - 17, -1))
        table_data.append(row_data)
        table_data.append(show_list[row])
    
    df = pd.DataFrame(table_data)

    return df

def create_table_4(best_guess, correlation, bitnum):
    """
    Creates a table from best guess values and their correlations.  Attacco sulla colonna, riporta indice della chiave + ranking sottochiavi.
    Attaco x4 
    Args:
        best_guess (list): List of best guess values.
        correlation (list): List of correlation values.
        bitnum (int): Bit number.
    Returns:
        pd.DataFrame: DataFrame representing the table.
    """
    table_data = []
    bit_number = ["k[" + str(((bitnum) % 64 ) + 64) + "]", "k[" + str(((7 + bitnum) % 64) + 64) + "]", "k[" + str(((41 + bitnum) % 64 ) + 64) + "]"] 
    bit_number.append("Correlation")
    table_data.append(bit_number)
    
    for i in range(len(best_guess)):
        table_line = []
        for b in range(len(best_guess[i])):
            table_line.append(best_guess[i][b])
        table_line.append(correlation[i])
        table_data.append(table_line)

    return pd.DataFrame(table_data)


    
