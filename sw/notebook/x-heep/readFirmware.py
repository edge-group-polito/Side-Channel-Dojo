# This file contains all the functions and classes needed to extract
# 32 bit instructions from the firmware file main.hex for the X-HEP MCU.

# Start address of the SOC_CTRL module in the memory map. Defined in mcu-gen.json and soc_ctrl_regs.h
SOC_CTRL_START_ADDRESS = 0x20000000
SOC_CTRL_BOOT_EXIT_LOOP_REG_OFFSET = 0xc

import sys
sys.path.append( '../../sca_python' )

from CW305_api import CW305Wrapper

# This function sends 1 byte at the time to the FPGA for each instruction/address
# The CW305 board has a set of addressable register identified by a proper address.
# The byte count defines the size (in bytes) of each register. So, to write data on
# a register 1 byte at the time, it is needed to specify both the reg address and the
# reg byte count in order to write the byte in the proper location.
# For X-HEEP, addresses and instructions are defined on 32 bit (4 bytes), so the address
# have to be shifted by 2 position to the left. The remaining 2 LSB are used to address
# the 4 bytes of the register.
def writeByteToFPGA(CW305_obj, address, bytecnt, data):
    # usb_addr = (int(address, base=16) << 2) + bytecnt
    usb_addr = (address << 2) + bytecnt
    #usb_data = int(data, base=16)
    usb_data = data
    CW305_obj.fpga_write(usb_addr, usb_data)

    # DEBUG
    print("usb_addr: {} \t usb_data: {} \t bytecnt: {}".format(usb_addr, usb_data, bytecnt))

    # DEBUG
    #print("usb_addr: {} \t usb_data: {} \t bytecnt: {}".format(hex(usb_addr), hex(usb_data), bytecnt))



import ReqClass

def readFirmware(CW305_obj, firmwareFile):
    request = ReqClass.Req()

    INSTR_VALID_MASK = 0x02
    ADDR_VALID_MASK = 0x04

    #TODO: change with the CW305 register addresses defines
    REG_BRIDGE_STATUS = '2'
    REG_PROG_INSTR = '3'
    REG_PROG_ADDRESS = '4'

    # DEBUG
    # Regiser defines
    print("\nRegister addresses:")
    print(CW305_obj.REG_BRIDGE_STATUS)
    print(CW305_obj.REG_PROG_INSTR)
    print(CW305_obj.REG_PROG_ADDRESS)
    print("\n")

    # Check that the firwmare file exists and then open it
    try:
        with open(firmwareFile, 'r') as fw:
            print("\nFirmware file '{}' found. Loading firmware...\n".format(firmwareFile))

            for line in fw:
                # Remove the newline character from the line
                line = line.rstrip('\n')

                # Check if the line is an address line or an instruction line
                if line.startswith('@'):

                    # Remove the '@' character from the line
                    address = str(line[1:])

                    # X-HEEP MCU accepts addresses from 0x180 when the bootmode is set to "Jump to Debug ROM"
                    # but the firmware contains also instructions for addresses below 0x180 which are not needed
                    # and have to be ignored.
                    if int(address, base=16) >= 0x180:
                        request.setAddress(address)

                        # DEBUG
                        #print("Address: ", request.getAddress())

                        # Check if the bridge is available, otherwise wait
                        # The mask 0x02 is used to check the instruction valid flag in the status register.
                        # Since the fpag_read function returns a list (bytearray), the [0] is used to get the first element
                        while CW305_obj.fpga_read(CW305_obj.REG_BRIDGE_STATUS, 1)[0] & INSTR_VALID_MASK:
                            print("Waiting for bridge to be available...")
                            pass

                        # Call FPGA write function for the new address
                        # The address have to be reversed for correct endianess
                        addr_to_write = request.getAddress()
                        addr_to_write = addr_to_write[6:8] + addr_to_write[4:6] + addr_to_write[2:4] + addr_to_write[0:2]
                        for j in range (0, len(addr_to_write), 2):
                            writeByteToFPGA(CW305_obj, CW305_obj.REG_PROG_ADDRESS, (j//2), addr_to_write[j:j+2])

                        print("Address Register: {}".format(CW305_obj.fpga_read(CW305_obj.REG_PROG_ADDRESS, 1)[0]))

                        # Set the status register
                        write_data = CW305_obj.fpga_read(CW305_obj.REG_BRIDGE_STATUS, 1)[0]
                        write_data |= ADDR_VALID_MASK
                        write_data = str(hex(write_data))[2:]
                        for j in range (0, len(write_data), 2):
                            writeByteToFPGA(CW305_obj, CW305_obj.REG_BRIDGE_STATUS, (j//2), write_data[j:j+2])
                else:
                    # Remove spaces from the line.
                    line = line.replace(' ', '')

                    # Same check as above for the address
                    if int(request.getAddress(), base=16) >= 0x180:
                        # Group the hex characters into chunks of 8 (without spaces), so the resulting instructions are 32 bits long
                        instructions = [line[i:i+8] for i in range(0, len(line), 8)]

                        # Fill the last group with zeros if it's less than 8 characters. This is needed since
                        # the firmware file might not contain a multiple of 32 bits when the remaining bits on
                        # the line are meant to zeros.
                        if len(instructions[-1]) < 8:
                            instructions[-1] = instructions[-1].ljust(8, '0')  # Pad with zeros on the right

                        # Iterate over the instructions extracted and send them to the FPGA
                        for i in instructions:
                            request.setInstruction(i)

                            # DEBUG
                            # print("Instruction: ", request.getInstruction())

                            # Check if the bridge is available, otherwise wait
                            # The mask 0x02 is used to check the instruction valid flag in the status register
                            while CW305_obj.fpga_read(CW305_obj.REG_BRIDGE_STATUS, 1)[0] & INSTR_VALID_MASK:
                                pass

                            instr_to_write = request.getInstruction()
                            for j in range (0, len(instr_to_write), 2):
                                writeByteToFPGA(CW305_obj, CW305_obj.REG_PROG_INSTR, (j//2), instr_to_write[j:j+2])


                            # Set the status register
                            write_data = CW305_obj.fpga_read(CW305_obj.REG_BRIDGE_STATUS, 1)[0]
                            write_data |= INSTR_VALID_MASK
                            write_data = str(hex(write_data))[2:]
                            for j in range (0, len(write_data), 2):
                                writeByteToFPGA(CW305_obj, CW305_obj.REG_BRIDGE_STATUS, (j//2), write_data[j:j+2])

        # When end of file is reached, write '1' to the xheep boot_exit_loop memory location to signal the end of the programming process
        print("\n...Firmware loaded. Setting boot exit loop flag...\n")

        addr_to_write = SOC_CTRL_START_ADDRESS + SOC_CTRL_BOOT_EXIT_LOOP_REG_OFFSET
        addr_to_write = str(hex(addr_to_write))[2:]
        addr_to_write = addr_to_write[6:8] + addr_to_write[4:6] + addr_to_write[2:4] + addr_to_write[0:2]
        for j in range (0, len(addr_to_write), 2):
            writeByteToFPGA(CW305_obj, CW305_obj.REG_PROG_ADDRESS, (j//2), addr_to_write[j:j+2])

        instr_to_write = '00000001'[::-1]
        for j in range (0, len(instr_to_write), 2):
            writeByteToFPGA(CW305_obj, CW305_obj.REG_PROG_INSTR, (j//2), instr_to_write[j:j+2])

        print("\n...Done\n")


    except FileNotFoundError:
        print("Error: Firmware file '{}' not found.\n".format(firmwareFile))
        exit(1)


# firmware = 'main.hex'
# readFirmware(firmware)
