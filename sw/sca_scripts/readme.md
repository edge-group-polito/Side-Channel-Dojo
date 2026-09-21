# Python SCA scripts

This directory contains the script-based side-channel analysis tools for the
CW305 FPGA and PicoScope setup. It supports both online trace acquisition and
offline analysis of stored traces.

## Directory guide

- `CW305_api.py` and `CW305_ascon_api.py`: target-control and register-access
  helpers for the CW305 designs.
- `pico_api.py`: PicoScope configuration and trace acquisition helpers.
- `AES/`: AES hardware capture and analysis workflows.
- `ASCON/`: ASCON software and hardware analysis workflows. See
  [`ASCON/README.md`](ASCON/README.md) for SNR and key-recovery commands.
- `analyzer/attack/`: leakage models and attack implementations.
- `analyzer/utils/`: plotting and shared analysis utilities.
- `utils/`: trace readers and data-processing helpers.

The cipher reference models used to validate expected outputs are kept in
[`sw/ciphers`](../ciphers), not in this directory.

## Typical workflow

1. Prepare the Python and hardware environment using
   [`sw/sca_test.md`](../sca_test.md).
2. Capture traces with the CW305 and PicoScope APIs, or use an existing
   dataset from `sw/traceset`.
3. Run an analysis script from `AES/`, `ASCON/`, or a matching script at the
   directory root.
4. Use the analyzer utilities to generate metrics and plots.

Scripts can have different input formats and output locations. Run
`python <script> --help` where supported and read the relevant subdirectory
guide before launching a long experiment. Keep large trace files and generated
plots out of source-controlled code directories.
