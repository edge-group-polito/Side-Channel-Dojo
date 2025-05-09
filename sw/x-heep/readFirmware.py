# This file contains all the functions and classes needed to extract
# 32 bit instructions from the firmware file main.hex for the X-HEP MCU.

# Start address of the SOC_CTRL module in the memory map. Defined in mcu-gen.json and soc_ctrl_regs.h
# in the CW305 X-HEEP project.
# SOC_CTRL_START_ADDRESS = '20000000'
# SOC_CTRL_BOOT_EXIT_LOOP_REG_OFFSET = 'c'
EXIT_LOOP_ADDRESS = '2000000c'

import sys
sys.path.append( '../../sca_python' )

# from CW305_api import CW305Wrapper
import ReqClass

def readFirmware(CW305_obj, firmwareFile):
    request = ReqClass.Req()

    # Define the masks for the status register. The masks are used to set the status register
    # bits for the address and instruction valid flags. The instruction valid flag is used also to
    # signal that the bridge is available for a new operation.
    INSTR_VALID_MASK = 0x02 # 0b00000010
    ADDR_VALID_MASK = 0x04  # 0b00000100

    # DEBUG
    # Regiser defines
    # print("\nRegister addresses:")
    # print(CW305_obj.REG_BRIDGE_STATUS)
    # print(CW305_obj.REG_PROG_INSTR)
    # print(CW305_obj.REG_PROG_ADDRESS)
    # print("\n")

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
                        # print("Address: ", request.getAddress())

                        # Check if the bridge is available, otherwise wait
                        # The mask 0x02 is used to check the instruction valid flag in the status register.
                        # Since the fpag_read function returns a list (bytearray), the [0] is used to get the first element
                        bridge_status = CW305_obj.fpga_read(CW305_obj.REG_BRIDGE_STATUS, 1)[0]
                        instr_valid = (bridge_status & INSTR_VALID_MASK) >> 1
                        addr_valid = (bridge_status & ADDR_VALID_MASK) >> 2
                        while instr_valid or addr_valid:
                            print("Waiting for bridge to be available. Address request pending...")
                            # DEBUG
                            # print("Bridge status: ", bridge_status, "Instruction valid: ", instr_valid, "Address valid: ", addr_valid)
                            pass

                        # Call FPGA write function for the new address
                        # The address have to be reversed for correct endianess
                        addr_to_write = request.getAddress()
                        addr_to_write = addr_to_write[6:8] + addr_to_write[4:6] + addr_to_write[2:4] + addr_to_write[0:2]

                        # Convert the address to a bytearray
                        addr_to_write = bytearray(bytes.fromhex(addr_to_write))

                        # Fill the address with zeros if it's less than 4 bytes
                        addr_to_write = bytearray([0x00] * (4 - len(addr_to_write))) + addr_to_write

                        # Write the address to the FPGA
                        CW305_obj.fpga_write(CW305_obj.REG_PROG_ADDRESS, addr_to_write)

                        # DEBUG
                        # print("Address Register: {}".format(CW305_obj.fpga_read(CW305_obj.REG_PROG_ADDRESS, 4)[::-1]))

                        # Set the status register
                        CW305_obj.fpga_write(CW305_obj.REG_BRIDGE_STATUS, data=bytearray([ADDR_VALID_MASK]))

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
                            bridge_status = CW305_obj.fpga_read(CW305_obj.REG_BRIDGE_STATUS, 1)[0]
                            instr_valid = (bridge_status & INSTR_VALID_MASK) >> 1
                            addr_valid = (bridge_status & ADDR_VALID_MASK) >> 2
                            while instr_valid or addr_valid:
                                print("Waiting for bridge to be available. Instruction request pending...")
                                # DEBUG
                                # print("Bridge status: ", bridge_status, "Instruction valid: ", instr_valid, "Address valid: ", addr_valid)
                                pass

                            instr_to_write = request.getInstruction()
                            
                            # Convert the instruction to a bytearray
                            instr_to_write = bytearray(bytes.fromhex(instr_to_write))

                            # write the instruction to the FPGA
                            CW305_obj.fpga_write(CW305_obj.REG_PROG_INSTR, instr_to_write)

                            # DEBUG
                            # print("Instruction Register: {}".format(CW305_obj.fpga_read(CW305_obj.REG_PROG_INSTR, 4)[::-1]))

                            # Set the status register
                            CW305_obj.fpga_write(CW305_obj.REG_BRIDGE_STATUS, data=bytearray([INSTR_VALID_MASK]))

        # When end of file is reached, write '1' to the xheep boot_exit_loop memory location to signal the end of the programming process
        print("\n...Firmware loaded. Setting boot exit loop flag...\n")

        bridge_status = CW305_obj.fpga_read(CW305_obj.REG_BRIDGE_STATUS, 1)[0]
        instr_valid = (bridge_status & INSTR_VALID_MASK) >> 1
        addr_valid = (bridge_status & ADDR_VALID_MASK) >> 2
        while instr_valid or addr_valid:
            print("Waiting for bridge to be available...")
            pass

        addr_to_write = EXIT_LOOP_ADDRESS[6:8] + EXIT_LOOP_ADDRESS[4:6] + EXIT_LOOP_ADDRESS[2:4] + EXIT_LOOP_ADDRESS[0:2]
        
        # Convert the address to a bytearray
        addr_to_write = bytearray(bytes.fromhex(addr_to_write))

        # Write the address to the FPGA
        CW305_obj.fpga_write(CW305_obj.REG_PROG_ADDRESS, addr_to_write)

        # DEBUG
        # print("Set exit loop address: {}".format(CW305_obj.fpga_read(CW305_obj.REG_PROG_ADDRESS, 4)[::-1]))
              
        # Set the status register
        CW305_obj.fpga_write(CW305_obj.REG_BRIDGE_STATUS, data=bytearray([ADDR_VALID_MASK]))

        bridge_status = CW305_obj.fpga_read(CW305_obj.REG_BRIDGE_STATUS, 1)[0]
        instr_valid = (bridge_status & INSTR_VALID_MASK) >> 1
        addr_valid = (bridge_status & ADDR_VALID_MASK) >> 2
        while instr_valid or addr_valid:
            print("Waiting for bridge to be available...")
            pass

        # Set the new instruction to write (basically a '1' that is interpreted by the X-HEEP MCU as a signal to exit the boot loop)
        # 00 00 00 01 -> 01 00 00 00 writing the instruction in reverse order
        instr_to_write = '01000000'

        # Convert the instruction to a bytearray
        instr_to_write = bytearray(bytes.fromhex(instr_to_write))

        # Write the instruction to the FPGA
        CW305_obj.fpga_write(CW305_obj.REG_PROG_INSTR, instr_to_write)

        # DEBUG
        # print("Exit loop instruction: {}".format(CW305_obj.fpga_read(CW305_obj.REG_PROG_INSTR, 4)[::-1]))

        # Set the status register
        CW305_obj.fpga_write(CW305_obj.REG_BRIDGE_STATUS, data=bytearray([INSTR_VALID_MASK]))

        print("\n...Done\n")


    except FileNotFoundError:
        print("Error: Firmware file '{}' not found.\n".format(firmwareFile))
        exit(1)

# DEBUG
# firmware = 'main.hex'
# readFirmware(firmware)
