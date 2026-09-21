# Virtual environment and SCA workflow

This document covers the Python environment and the two CPA workflows used in
this repository: the standard ChipWhisperer project flow and the custom ASCON
HDF5 flow.

## Prerequisites

Install the system packages required by Python, USB access, and the board
interfaces. The exact package names can vary between Linux distributions.

```bash
sudo apt update && sudo apt upgrade
sudo apt-get install build-essential gdb lcov pkg-config \
    libbz2-dev libffi-dev libgdbm-dev libgdbm-compat-dev liblzma-dev \
    libncurses5-dev libreadline6-dev libsqlite3-dev libssl-dev \
    lzma lzma-dev tk-dev uuid-dev zlib1g-dev curl
sudo apt install libusb-dev make git avr-libc gcc-avr \
    gcc-arm-none-eabi libusb-1.0-0-dev usbutils
```

Install [pyenv](https://github.com/pyenv/pyenv) if it is not already
available, then create the project environment:

```bash
pyenv install 3.9.5
pyenv virtualenv 3.9.5 cw
pyenv activate cw
python -m pip install -r requirements.txt
python -m pip install chipwhisperer picosdk
```

Install the PicoScope Linux drivers and PicoSDK from
[Pico Technology](https://www.picotech.com/downloads/linux). 
On Ubuntu 24.10 the apt installation of the picoscope package can fail because of a `gtk3-sharp` dependency. Workaround:
```bash
sudo apt update
sudo apt install aptitude
sudo aptitude install picoscope
```

For CW305 USB permissions, install the repository udev rule and add the user
to the required groups:

```bash
sudo cp hw/50-newae.rules /etc/udev/rules.d/50-newae.rules
sudo udevadm control --reload-rules
sudo groupadd -f chipwhisperer
sudo usermod -aG chipwhisperer "$USER"
sudo usermod -aG plugdev "$USER"
```

Log out and back in after changing group membership. If a PicoScope is not
detected, check the USB connection with `lsusb` and inspect recent kernel
messages with `dmesg | tail -n 50`. USB 3.0 ports can be more reliable for some
PicoScope and host combinations.

## SCA attack overview

A correlation power analysis (CPA) attack has two phases:

- **Online phase:** configure the target and oscilloscope, execute the cipher
  repeatedly, and save each power trace with the input, output, nonce, and key
  metadata needed by the leakage model.
- **Offline phase:** load the saved traces, calculate hypothetical leakage for
  key candidates, and correlate those values with the measured samples.

The online phase requires the CW305 and PicoScope. The offline phase can be
repeated with different leakage models and trace windows without reconnecting
to the hardware.

## ChipWhisperer toolchain

See the [ChipWhisperer documentation](https://chipwhisperer.readthedocs.io/en/latest/)
for the complete API. The simplified flow below shows the important data
contract; the target-specific capture code is supplied by the wrappers in
`sca_scripts/CW305_api.py` and `sca_scripts/pico_api.py`.

### Online phase: create a project

Use a fixed key when the attack is intended to recover that key. The
ChipWhisperer text/key provider generates inputs and can verify that the key
stays fixed:

```python
import chipwhisperer as cw

ktp = cw.ktp.Basic()
key, plaintext = ktp.next()
assert ktp.fixed_key()

project = cw.create_project("path/to/project.cwp", overwrite=True)

# Configure the CW305 and oscilloscope before the loop.
# For every measurement:
#   1. trigger the target and acquire the waveform;
#   2. obtain the ciphertext or target response;
#   3. append the waveform and metadata to the project.
# project.traces.append(Trace(wave, plaintext, ciphertext, key))

project.save()
project.close()
```

A trace record contains the waveform and the values required to reproduce the
hypothetical intermediate state. Inspect the project before starting a long
attack:

```python
project = cw.open_project("path/to/project.cwp")
print(len(project.traces))
print(project.traces[0].wave.shape)
print(project.traces[0].textin)
project.close()
```

### Offline phase: run CPA

The analyzer provides built-in leakage models, such as the AES last-round
state difference model. The model produces one hypothetical leakage value per
trace and key hypothesis. CPA compares those predictions with every measured
sample and ranks the key hypotheses by correlation.

```python
import chipwhisperer as cw
import chipwhisperer.analyzer as cwa

project = cw.open_project("path/to/project.cwp")
attack = cwa.cpa(
    project,
    cwa.leakage_models.last_round_state_diff,
)
results = attack.run()

print(results.best_guesses())
print(results.find_maximum())
project.close()
```

`results.best_guesses()` returns the best subkey guess for each byte.
`find_maximum()` and the other result helpers can be used to inspect ranked
hypotheses and correlation values. CPA can be run progressively, allowing the
key ranking to be inspected after increasing numbers of traces.

### Custom leakage models

A custom model must define the target intermediate state and the way the known
key is processed. For AES, this is commonly implemented by subclassing
`AESLeakageHelper` and registering the model with
`cwa.leakage_models.new_model(...)`. The byte order, key schedule, S-Box, and
state transition in the model must match the implementation being measured.

The repository's reusable AES and ASCON leakage models are in
`sca_scripts/analyzer/attack/`.

## Custom ASCON pipeline

The ASCON notebooks follow the same online/offline separation, but the newer
script workflow stores traces in HDF5 instead of a ChipWhisperer `.cwp`
project. The pipeline has one script for acquisition and another for analysis.

### 1. Online phase: acquire an HDF5 traceset

`sca_scripts/ASCON/sw/xheep_ASCON_capture.py` initializes the PicoScope and
CW305/X-HEEP target, loads the firmware and bitstream, and captures a selected
number of traces. For each trace it:

1. starts the PicoScope acquisition and triggers the target;
2. reads the power waveform;
3. stores the waveform and the corresponding ASCON nonce;
4. updates the nonce using the ASCON first-round model; and
5. periodically flushes progress to disk.

Run it from the repository root:

```bash
python sw/sca_scripts/ASCON/sw/xheep_ASCON_capture.py \
  --sbox lut_lu_5 \
  --traces 1000000
```

The output is written below `sw/traceset/ASCON/sw/`, for example:

```text
ascon_opt32_lut_lu_5_1000k.h5
```

The HDF5 file contains:

| Item | Description |
| --- | --- |
| `/traces` | `float32` power samples with shape `(number_of_traces, number_of_samples)`. |
| `/nonces` | Two `uint64` values per trace containing the nonce representation used by the attack. |
| File attributes | Sampling interval, trace and sample counts, key, IV, and capture progress. |

The acquisition script can also save an overlapped-traces plot below
`sw/sca_scripts/ASCON/sw/plot/`. The capture stage must complete before the
CPA script reads the file.

### 2. Offline phase: load the HDF5 file and run CPA

`sca_scripts/ASCON/sw/xheep_ASCON_cpa_generic.py` loads the HDF5 file and
checks that `/traces` and `/nonces` have matching lengths. It reads the key and
IV from the file attributes, loads SNR-ranked target bits when available, and
attacks bits in ASCON state registers `x0` through `x4`.

The attack is processed in chunks, so the complete trace matrix does not have
to fit in memory. CuPy can be used for GPU accumulation; otherwise the script
uses NumPy and the available CPU threads. Configure the S-Box and trace count
through environment variables, then run:

```bash
ASCON_SBOX_TYPE=lut_lu_5 \
ASCON_N_TRC=1000000 \
ASCON_CPA_DEVICE=cpu \
python sw/sca_scripts/ASCON/sw/xheep_ASCON_cpa_generic.py
```

The script expects a matching file named
`sw/traceset/ASCON/sw/ascon_opt32_<sbox>_<traceset-size>k.h5`. It generates
hypothetical ASCON bit leakages from each nonce and key hypothesis, calculates
correlations against the selected trace samples, and stores results and plots
below:

- `sw/sca_scripts/ASCON/sw/cache/`
- `sw/sca_scripts/ASCON/sw/plot/`

The notebook attack uses the same conceptual inputs but calls a selected attack
class directly, for example `cpa_round_1_pool(keys[0])`, followed by
`attack_leak_model(wind_traces, nonces, sub_layer_type, callback, i)`. Available
variants include single-bit attacks and `x0`/`x4` pool and key-recovery
attacks. Supported S-Box labels include `hw`, `lut_ascon`, `lut_bilgin`,
`lut_allouzi`, and `lut_lu_4` through `lut_lu_7`.

Because acquisition and analysis are separate, the same HDF5 traceset can be
reused with different leakage models, trace windows, SNR rankings, CPA policies,
and CPU/GPU settings without repeating the hardware capture.
