todo:
- [ ] : modify the handshake protocol in a way that also the trigger flag is disabled by xheep when received
- [ ] : add some comments about the sw/x-heep folders in the readme
---

## ✅ TODO

* [ ] Finish Verilator simulation flow (I/O from/to file; use `AES_golden_model.py` as reference model)
* [ ] Add support for ModelSim / QuestaSim simulation
* [ ] Add README in `sw/AES_python/validation_test/` explaining the AES KAT tests
* [ ] Library of common plotting utilities under `sw/sca_python/analyzer/utils`
* [ ] Simulate and synthesize the **AES pipeline** version
* [ ] Finalize `sw/sca_setup.md` and ensure environment recreation is fully documented
* [ ] Provide a pure-Python version of the AES notebook in `sw/sca_python/examples/aes/` (non-Jupyter flow)
* [ ] Update readme to say that the scrippts refere to commond traceset directory and similarly cache and plot directory are fixed
* [ ] Update all scripts to use same way to refer to root directory and to save traces captured and results in common directories

**Optional:**

* [ ] Makefile target to run Python script for **automatic power trace capture**
* [ ] Makefile target to run Python script for **CPA attacks** end-to-end
* [ ] Docker image for a fully reproducible SCA environment
* [ ] To add that x-heep comes with vendor and should be used the vendor update script if done changs
---

## 🔍 TO CHECK

* A lot of registers in `hw/crypto_asic/ascon/rtl/cw305_reg_ascon.sv` appear unused and could potentially be removed / cleaned up.
**manca la spigezione di come si fa il fw, il fatto che se lo aspeta con un nome specifico e con il numero di loop settato nel .c**