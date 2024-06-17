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