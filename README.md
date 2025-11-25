# 🔐 Side Channel Dojo

This repository provides an environment to test cryptographic implementations against **power-based side-channel attacks**.
It targets the **ChipWhisperer CW305** FPGA board and uses a **PicoScope 5000a** oscilloscope for power trace acquisition. The scripts can be easily adapted to other setups.

---

## 🚀 Getting started

### ✅ Prerequisites

You will need:

1. **Verilator** – open-source RTL simulator
   👉 [Setup guide (OpenTitan)](https://opentitan.org/guides/getting_started/setup_verilator.html)
2. **FuseSoC** – dependency manager and front-end to run tools
   👉 [https://github.com/olofk/fusesoc](https://github.com/olofk/fusesoc)

   > ℹ️ FuseSoC is a Python package and can be installed directly inside your Python virtual environment.
3. **Verible** (optional but recommended) – SystemVerilog formatter and linter
   👉 [Install Verible](https://opentitan.org/guides/getting_started/index.html#step-7a-install-verible-optional)
4. **Vivado** – to synthesize and implement the designs on the FPGA (Artix-7 on CW305).
5. **Hardware setup**

   * ChipWhisperer **CW305** board (Artix-7)
   * **PicoScope 5000a** for power trace capture

---

## 🐍 Python & SCA environment

Once all system-level prerequisites are installed, follow the tutorial in:

`sw/sca_setup.md`

This document explains how to create the Python virtual environment and install the required SCA packages (including FuseSoC, ChipWhisperer, etc.).

---

## 📚 Examples – Crypto ASIC standalone

The repository provides **standalone crypto ASIC examples** (AES and ASCON).
Each ASIC is controlled via **memory-mapped registers** exposed on CW305. These registers are accessed over USB using Python APIs.

### 🔒 AES – Advanced Encryption Standard

The standard Rijndael S-Box is known to be vulnerable to power analysis. This repository includes **alternative S-Boxes** (LUT-based, power-hardened variants) that can be synthesized and attacked.

#### 🔧 Makefile configuration for AES

* **`AES_SBOX`** (default: `rijandael`)
  Selects the AES S-Box implementation. The list of supported S-Boxes (LUT implementations) can be found under:
  `hw/crypto_asic/aes/rtl/AES_common/Sbox/`

* **`AES_ARCH`** (default: `single_round`)
  Selects the AES architecture. Currently only the **single-round** implementation is supported.

> ⚠️ At the moment, there is **no support** for configuring an arbitrary number of rounds per clock. This may be extended in future work.

To synthesize the AES single-round implementation with the `azam_1` LUT S-Box:

```bash
make vivado-fpga-aes AES_ARCH=single_round AES_SBOX=azam_1
```

The generated bitstream is placed under:

`hw/fpga/bitstream/aes/aes_single_round/`

(Exact path depends on your Makefile, but all AES bitstreams live under `hw/fpga/bitstream/aes/`.)

### 🌀 ASCON

Two ASCON designs are provided:

1. **`ascon_init`** – implements only the **initial / first round** of ASCON (sufficient for SCA).
2. **`ascon_asip`** – architecture generated via **ASIP Designer** (Synopsys).

#### 🔧 Makefile configuration for ASCON

* **`ASCON_ARCH`** (default: `ascon_init`)
  Supported values:

  * `ascon_init` – first-round-only design
  * `ascon_asip` – ASIP-based implementation

If `ASCON_ARCH=ascon_init`, the RTL can be further configured with:

* **`ASCON_SBOX_MODE`** (default: `lut`)

  * `lut` → LUT-based S-Box
  * `comb` → combinational S-Box (only the standard S-Box is supported in this mode)

* **`ASCON_SBOX`** (default: `sbox_standard`)
  Selects the S-Box variant (for LUT mode). The list of supported S-Boxes and how they are wired via Verilog defines can be found in:
  `hw/crypto_asic/ascon/rtl/...`

To synthesize the **ASCON first-round** implementation with the `allouzi` LUT S-Box:

```bash
make vivado-fpga-aes ASCON_ARCH=ascon_init ASCON_SBOX=allouzi ASCON_SBOX_MODE=lut
```

The bitstream is generated under:

`hw/fpga/bitstream/ascon/`

---

## 🌊 RTL simulation (Verilator)

Taking AES as example, the Verilator-based simulation flow is:

```bash
# Build Verilator model
make aes-verilator-build

# Run simulation
make aes-verilator-sim
```

To build and program the AES bitstream for CW305:

```bash
make vivado-fpga-aes
```

> ⚠️ **S-Box selection via Verilog defines**
> Currently, the S-Box selection is controlled by macros inside `aes_sub_layer_lut.sv` (e.g. `` `define SBOX_FREYRE_3 ``).
> The long-term plan is to control these via **command-line `+define+SBOX_*` / `-DSBOX_*`**, but for now you may still need to ensure the correct define is set in RTL / synthesis options.

---

## ⚙️ CW305 with X-HEEP (RISC-V)

This repo also includes a **port of X-HEEP** (RISC-V-based microcontroller) onto the CW305 board, allowing you to perform side-channel attacks on a full **RISC-V SoC**.

* Project: [`X-HEEP`](https://github.com/esl-epfl/x-heep)
* Platform: [`ChipWhisperer CW305`](https://github.com/newaetech/chipwhisperer/tree/develop)

🔎 For details on the X-HEEP integration on CW305, see:

`hw/vendor/cw305-heep/README.md`

All related commands can be invoked from the top-level Makefile.

> ⚠️ **ChipWhisperer CW305 driver tweak**
> To work with X-HEEP, you must modify `chipwhisperer/capture/targets/CW305.py`:
>
> * `self.registers` → `7`
> * `self.bytecount_size` → `2`

---

## 📒 Jupyter SCA notebooks (`sw/notebook`)

Main entry point for **interactive side-channel experiments**.

The key subfolders under `sw/notebook/examples` are:

* 📈 `aes/`
  Notebooks for **AES on CW305**: CPA, SNR, success-rate evaluation, and debugging.
  Includes a `cache/` directory with precomputed results (e.g. success rates) as JSON files for different AES S-Boxes.

* 🔓 `ascon/`
  Notebooks for **ASCON first-round** experiments: trace collection, CPA-style attacks, SNR analysis, and basic leakage evaluation.

* 🧪 `x-heep/`
  Notebooks for **X-HEEP on CW305** (RISC-V): AES and ASCON SCA campaigns, including TVLA-style leakage tests.

At the root of `sw/notebook` you will also find general-purpose notebooks, such as:

* `measure_cpa_success_rate.ipynb` – generic CPA success-rate measurement
* `measure_cryptographic_properties_sbox.ipynb` – S-Box property evaluation
* `measure_TVLA.ipynb` – TVLA-style leakage testing
* `sca_test.ipynb` – simple end-to-end SCA example

---

## 🐍 Advanced Python SCA scripts (`sw/sca_python`)

This folder contains **non-notebook** tooling for long-running and advanced attacks (💡 recommended to run via `tmux` or similar, since many scripts take a long time).

The main subcomponents are:

* 🔧 `AES_HW/`
  Scripts and notebooks to evaluate **AES hardware success rate** on CW305 across **multiple S-Boxes**:

  * batch computation of success-rate curves
  * automation over all configured AES S-Box variants

* 🧠 `analyzer/`
  Core analysis logic used by both scripts and notebooks:

  * `analyzer/attack/aes/` – AES key schedule helpers, S-Box leakage models, modified S-Box functions
  * `analyzer/attack/ascon/` – ASCON-specific SCA engines, incremental statistics, utilities, and X-HEEP ASCON CPA helpers
  * `analyzer/utils/` – plotting utilities and shared analysis helpers

* 🧩 Hardware APIs

  * `CW305_api.py` – abstraction layer to control the CW305 FPGA (registers, trigger, I/O)
  * `pico_api.py` – interface to the PicoScope 5000a for trace acquisition

* 🧾 Trace utilities (`utils/`)
  Readers and helpers for different trace formats (e.g. HDF5, custom `.dat`), plus configuration utilities.

* 🚀 X-HEEP SCA scripts (`xheep_*.py`)
  End-to-end workflows for **AES and ASCON SCA on X-HEEP**, including:

  * success-rate evaluation
  * TVLA-style tests
  * SNR analysis
    often with both single-process and multiprocessing variants.

In short: `sw/notebook/` is ideal for **interactive exploration**, while `sw/sca_python/` is your toolbox for **automated, large-scale experiments** on CW305 and X-HEEP.

---

## 📁 Repository folder structure (top level)

| Folder                  | Description                                                                                      |
| ----------------------- | ------------------------------------------------------------------------------------------------ |
| `hw/`                   | HDL sources, crypto ASIC RTL, FPGA-specific files, bitstreams, and vendor IP                     |
| `hw/crypto_asic/aes`    | AES ASIC RTL, S-Box variants, build targets                                                      |
| `hw/crypto_asic/ascon`  | ASCON ASIC RTL and build targets                                                                 |
| `hw/fpga/bitstream`     | Generated FPGA bitstreams (AES, ASCON, X-HEEP, …)                                                |
| `hw/vendor/cw305-heep/` | Port of X-HEEP to CW305, including CW305-HEEP integration and X-HEEP-specific build/RTL files    |
| `pics/`                 | Block diagrams and documentation figures                                                         |
| `scripts/`              | Utility scripts (e.g. wave-copy helpers, build helpers)                                          |
| `sw/`                   | Software: golden AES model, notebooks, SCA Python tooling, environment setup                     |
| `sw/notebook/`          | Jupyter notebooks for SCA attacks and measurements (AES, ASCON, X-HEEP)                          |
| `sw/sca_python/`        | Python APIs and scripts for CW305/Pico, AES/ASCON/X-HEEP SCA, long-running and batch experiments |
| `tb/`                   | Testbenches for AES/ASCON cores (ModelSim, Verilator)                                            |

---

## ✅ TODO

* [ ] Finish Verilator simulation flow (I/O from/to file; use `AES_golden_model.py` as reference model)
* [ ] Add support for ModelSim / QuestaSim simulation
* [ ] Add README in `sw/AES_python/validation_test/` explaining the AES KAT tests
* [ ] Library of common plotting utilities under `sw/sca_python/analyzer/utils`
* [ ] Simulate and synthesize the **AES pipeline** version
* [ ] Finalize `sw/sca_setup.md` and ensure environment recreation is fully documented
* [ ] Provide a pure-Python version of the AES notebook in `sw/sca_python/examples/aes/` (non-Jupyter flow)

**Optional:**

* [ ] Makefile target to run Python script for **automatic power trace capture**
* [ ] Makefile target to run Python script for **CPA attacks** end-to-end
* [ ] Docker image for a fully reproducible SCA environment

---

## 🔍 TO CHECK

* A lot of registers in `hw/crypto_asic/ascon/rtl/cw305_reg_ascon.sv` appear unused and could potentially be removed / cleaned up.
