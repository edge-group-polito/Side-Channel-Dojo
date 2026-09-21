# 🔐 Side Channel Dojo

This repository provides an environment to test cryptographic implementations against **power-based side-channel attacks**.
It targets the **ChipWhisperer CW305** FPGA board and uses a **PicoScope 5000a** oscilloscope for power trace acquisition. The scripts can be easily adapted to other setups and targets.

---

## 🚀 Getting started

### ✅ Prerequisites

| Requirement | Used for | Notes |
| --- | --- | --- |
| Vivado | FPGA synthesis and implementation | Required to build CW305 bitstreams. |
| ChipWhisperer CW305 | FPGA target and trace trigger | Required for hardware capture. |
| PicoScope 5000a and PicoSDK | Power trace acquisition | Required for PicoScope-based capture scripts. |
| [FuseSoC](https://github.com/olofk/fusesoc) | RTL dependency management and simulation | Install it in the Python environment used by this repository. |
| [Verilator](https://opentitan.org/guides/getting_started/setup_verilator.html) | RTL simulation | Used by the `aes-verilator-*` targets. |
| [Verible](https://opentitan.org/guides/getting_started/index.html#step-7a-install-verible-optional) | RTL formatting and linting | Optional, but recommended for `make format` and `make lint`. |

For the Python environment, USB permissions, PicoSDK, and ChipWhisperer setup,
see [`sw/sca_test.md`](sw/sca_test.md). The dependency list is in
[`sw/requirements.txt`](sw/requirements.txt).

---

## 🐍 Python & SCA environment

Once the system-level prerequisites are installed, follow the setup and SCA
workflow in [`sw/sca_test.md`](sw/sca_test.md).

---

## 🏎️ Crypto ASIC standalone

The repository provides **standalone crypto ASIC examples** (AES and ASCON).
Each ASIC is controlled via **memory-mapped registers** exposed on CW305. These registers are accessed over USB using Python APIs.

### AES – Advanced Encryption Standard

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

### ASCON

Two ASCON designs used **`ascon_init`** implements only the **initial / first round** of ASCON (targets of a SCA).

The RTL can be further configured with:

* **`ASCON_SBOX_MODE`** (default: `lut`)

  * `lut` → LUT-based S-Box
  * `comb` → combinational S-Box (only the standard S-Box is supported in this mode)

* **`ASCON_SBOX`** (default: `sbox_standard`)
  Selects the S-Box variant (LUT mode).

To synthesize the **ASCON first-round** implementation with the `allouzi` LUT S-Box:

```bash
make vivado-fpga-ascon ASCON_ARCH=ascon_init ASCON_SBOX=allouzi ASCON_SBOX_MODE=lut
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

The X-HEEP integration and its board-specific documentation are under
[`hw/vendor/cw305-heep`](hw/vendor/cw305-heep). Related commands are included
by the top-level Makefile.

> ⚠️ **ChipWhisperer CW305 driver tweak**
> To work with X-HEEP, you must modify `chipwhisperer/capture/targets/CW305.py`:
>
> * `self.registers` → `7`
> * `self.bytecount_size` → `2`

While for HW standalone case is 
> * `self.registers` → `12`
> * `self.bytecount_size` → `7`
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

---

## 🐍 Python SCA scripts (`sw/sca_scripts`)

[`sw/sca_scripts`](sw/sca_scripts) contains the non-notebook tools for trace
capture, leakage analysis, correlation power analysis, SNR evaluation, and
key-recovery experiments. These scripts are intended for longer-running
experiments, they often use multi-threadin and are best run from `tmux` or another persistent session.

Start with the [SCA scripts guide](sw/sca_scripts/readme.md). The ASCON SNR and
key-recovery workflows have a separate, more detailed guide in
[`sw/sca_scripts/ASCON/README.md`](sw/sca_scripts/ASCON/README.md).

| Area | Contents |
| --- | --- |
| `AES/` | AES capture and analysis workflows. |
| `ASCON/` | ASCON analyses, including SNR comparison and key-recovery progression. |
| `analyzer/attack/` | Custom defined AES and ASCON leakage models, attack logic, and statistics. |
| `analyzer/utils/` | Plotting, metrics, and shared analysis helpers. |
| `CW305_api.py`, `CW305_ascon_api.py` | CW305 register, trigger, and target-control APIs. |
| `pico_api.py` | PicoScope acquisition API. |
| `utils/` | Trace readers and data-processing utilities. |

Most scripts accept command-line options; inspect `--help` and the local guide
before changing parameters. Generated traces, caches, and plots should remain
in their documented output directories rather than being committed to source
folders.

## 🧮 Cipher reference models (`sw/ciphers`)

[`sw/ciphers`](sw/ciphers) contains the Python reference implementations and
supporting test vectors for the analyzed ciphers. It currently includes AES,
ASCON, and the ASCON initialization-round model. These models provide expected
intermediate values and outputs for validating RTL, capture scripts, and
side-channel leakage models,

---

## 📁 Repository structure

| Path | Purpose |
| --- | --- |
| `hw/` | HDL sources, crypto cores, FPGA wrappers, generated bitstreams, and vendored hardware. |
| `hw/crypto_asic/aes/` | AES RTL, S-Box variants, and FPGA build files. |
| `hw/crypto_asic/ascon/` | ASCON RTL, S-Box variants, and FPGA build files. |
| `hw/fpga/bitstream/` | Generated CW305 bitstreams grouped by design and architecture. |
| `hw/vendor/cw305-heep/` | X-HEEP integration for the CW305 platform. |
| `sw/ciphers/` | Python reference models and validation data for AES and ASCON. |
| `sw/notebook/` | Interactive notebooks and analysis examples. |
| `sw/sca_scripts/` | Reusable APIs and script-based SCA workflows. |
| `sw/traceset/` | Trace datasets and dataset-related assets. |
| `tb/` | ModelSim and Verilator testbenches. |
| `scripts/` | Small repository utilities, such as waveform-copy helpers. |
| `build/` | Tool output and generated simulation/build artifacts. |
