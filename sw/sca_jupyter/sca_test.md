## Prerequisites
First part of the documentation taken from [here](https://chipwhisperer.readthedocs.io/en/latest/linux-install.html#installing-chipwhisperer). 

The virtual environment recreation can be done running in the terminal  
```bash
# Run updates
sudo apt update && sudo apt upgrade
# 1. python prereqs
sudo apt-get install build-essential gdb lcov pkg-config \
    libbz2-dev libffi-dev libgdbm-dev libgdbm-compat-dev liblzma-dev \
    libncurses5-dev libreadline6-dev libsqlite3-dev libssl-dev \
    lzma lzma-dev tk-dev uuid-dev zlib1g-dev curl

sudo apt install libusb-dev make git avr-libc gcc-avr \
    gcc-arm-none-eabi libusb-1.0-0-dev usbutils

# install pyenv - skip if already done
    curl https://pyenv.run | bash
    echo 'export PATH="~/.pyenv/bin:$PATH"' >> ~/.bashrc
    echo 'export PATH="~/.pyenv/shims:$PATH"' >> ~/.bashrc
    echo 'eval "$(pyenv init -)"' >> ~/.bashrc
    echo 'eval "$(pyenv virtualenv-init -)"' >> ~/.bashrc

source ~/.bashrc

pyenv install 3.9.5
pyenv virtualenv 3.9.5 cw
pyenv activate cw

cd ~/
git clone https://github.com/newaetech/chipwhisperer
cd chipwhisperer
sudo cp hardware/50-newae.rules /etc/udev/rules.d/50-newae.rules
sudo udevadm control --reload-rules
sudo groupadd -f chipwhisperer
sudo usermod -aG chipwhisperer $USER
sudo usermod -aG plugdev $USER
git submodule update --init jupyter

python -m pip install -e .
python -m pip install -r jupyter/requirements.txt
cd jupyter
python -m pip install nbstripout
nbstripout --install
```
Lastly install the requirments from current directory 

```
pip install -r requirements.txt
```
## SCA STEPS
1. Reference model 
    The key is kept fix during the encrpytion tests
    ```python
    import chipwhisperer as cw
    ktp = cw.ktp.Basic()
    key, text = ktp.next()
    ```
    To check if the key is kept fix (by default it is) the following function should return true
    ```
    ktp.fixed_key()
    ```
2. Capture the traces (online) 
    The *project* object allows to store the traces collected in a organized way
    Capture example 
    ```python 
    import chipwhisperer as cw
    import picoscope_api as pico
    proj = cw.create_project("project_name")
    wave = pico.capture()
    trace_i = Trace(np.array(wave), plaintext, ciphertext, key)
    project.traces.append(trace_i)
    project.save()
    ```
    The Voltage samples captured by pico are returned as an array of values (Volt).
    The trace object is build giving as parameter 
    - the wave as a numpy array, it is long 5000 by default
    - the plaintext, ciphertext and key given as bytearray 
    ```python
    class Trace(wave, textin, textout, key)
    ```
    The trace object support 
    - indexing 
    ```python
    for trace in my_project.traces:
        print(trace.wave, trace.textin, trace.textout, trace.key)
    trace_of_interest = my_project.traces[4]
    ```
    - slicing
    interesting_traces = my_project.traces[4:10]

3. Attack phase (offline)
The analyzer is the class which provides a set of fucntions to analyze the captured traces and recover from leakeages the secret key. 
The chipwhisperer analyzer comes with a preset of leakage models which exploit the correlation power analysis. 
To check all the leakage model already present :
```python
import chipwhisperer.analyzer as cwa
print(cwa.leakage_models)    
```
Example : running the cpa attack on the last round of AES (hamming distance between round 9 and 10)
```python
import chipwhisperer.analyzer as cwa
import chipwhisperer as cw
proj = cw.open_project("path/to/project")
attack = cwa.cpa(proj, cwa.leakage_models.last_round_state_diff)
results = attack.run()
print(results)

```
The cpa object takes as input the traces to analyze and the leakge model to use. 
The attack is run calling the cpa.run() method which returns the *Results* object.
The attack is progressive, by default updates each 25 traces. 
Optionally takes as input a callback function, called at the update
To get each best subkey guess with the correspetive correlation value
```python
results.best_guesses()
```
To get the best 256 guesses for each subkey, ranked based on the correlation value. 
```
results.find_maximum()
```
To get some more specific detail, like for the 4 subkey to get the first key guess and its  correlation value
``` print(attack_results.find_maximums()[4][0][2])```



A new leakge model can be defined as  
```python
class LastroundStateDiff(AESLeakageHelper):
    name = 'HD: AES Last-Round State'
    c_model_enum_value = 2
    c_model_enum_name = 'LEAK_HD_LASTROUND_STATE'
    def leakage(self, pt, ct, key, bnum):
        # HD Leakage of AES State between 9th and 10th Round
        # Used to break SASEBO-GII / SAKURA-G
        st10 = ct[self.INVSHIFT_undo[bnum]]
        st9 = inv_sbox(ct[bnum] ^ key[bnum])
        return (st9 ^ st10)

    def process_known_key(self, inpkey):
        return key_schedule_rounds(inpkey, 0, 10)
```
```python
class SBox_output(AESLeakageHelper):
    name = 'HW: AES SBox Output, First Round (Enc)'
    c_model_enum_value = 1
    c_model_enum_name = 'LEAK_HW_SBOXOUT_FIRSTROUND'
    def leakage(self, pt, ct, key, bnum):
        return self.sbox(pt[bnum] ^ key[bnum])
```