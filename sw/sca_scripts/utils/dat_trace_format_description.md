# Description of the DAT binary trace format

This short document is intended as a specification of the "DAT" trace 
format. The format is intended to be a simple file format storing
side channel measurements (*traces* in short).

A DAT file is a simple marshalling of the binary values preceded by a 
fixed-length metadata header.
All the multi-byte values are written in little-endian order, 
allowing buffer filling on little endian machines through C read().



## DAT structure

  * Header
  * key
  * 1st trace
  * 1st input to the device, corresponding to the side channel behaviour
  of the 1st trace  
  *
  * 2nd trace
  * 3rd input to the device, corresponding to the side channel behaviour
  of the 2nd trace
  * ... 
  * n-th trace
  * n-th input to the device, corresponding to the side channel behaviour
  of the n-th trace

# Header structure
  
  * A 32 bit unsigned integer, representing the number of traces
  * A 32 bit unsigned integer, representing the number of samples of a 
    trace
  * A single character, indicating the data type of the single trace 
    sample, according to the following convention
    * 'c':  8-bit signed integer (int8_t)
    * 'h': 16-bit signed integer (int16_t)
    * 'f': 32-bit IEEE-754 float
    * 'd': 64-bit IEEE-754 double 
  * A 8 bit signed integer, representing the length of the input in 
    *bytes*
