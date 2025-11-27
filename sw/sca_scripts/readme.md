# SCA Python Library

This library provides tools for Side-Channel Analysis (SCA) using the Picoscope oscilloscope and the CW305 board. It includes functionalities for cryptographic testing, leakage analysis, and attack execution.

## Features

- **Picoscope & CW305 API**: Easily instantiate and interact with the Picoscope oscilloscope and the CW305 FPGA board for side-channel data acquisition.
  
- **Test**: A set of cryptographic golden models to verify if the obtained results match the expected outputs.

- **Analyzer**: 
  - **Attack**: Contains leakage models and cryptographic model functions for running side-channel attacks.
  - **Utils**: Utility functions for plotting attack results and metrics, along with other helper tools for analysis.
