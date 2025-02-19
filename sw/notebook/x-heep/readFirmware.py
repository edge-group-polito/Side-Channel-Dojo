# This file contains all the functions and classes needed to extract
# 32 bit instructions from the firmware file main.hex for the X-HEP MCU.

import ReqClass

# Check that the firwmare file exists and then open it
firmware = 'main.hex'
request = ReqClass.Req()

INSTR_VALID_MASK = 0x02
ADDR_VALID_MASK = 0x04

try:
    with open(firmware, 'r') as fw:

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

                    print("Address: ", request.getAddress())

                    # Check if the bridge is available, otherwise wait
                    # The mask 0x02 is used to check the instruction valid flag in the status register
                    # while self.read_fpga(self.CW305.REG_BRIDGE_STATUS, 1) & INSTR_VALID_MASK:
                    #     pass

                    # Call FPGA write function for the new address
                    # Reverse the address for correct endianess and set it as valid (maybe not needed)(maybe convert to int)
                    # self.CW305.fpga_write(self.CW305.REG_PROG_ADDRESS, request.getAddress()[::-1])

                    # Set the status register
                    # write_data = self.read_fpga(self.CW305.REG_BRIDGE_STATUS, 1)
                    # write_data |= ADDR_VALID_MASK
                    # self.CW305.fpga_write(self.CW305.REG_BRIDGE_STATUS, write_data)
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

                        print("Instruction: ", request.getInstruction())

                        # Check if the bridge is available, otherwise wait
                        # The mask 0x02 is used to check the instruction valid flag in the status register
                        # while self.read_fpga(self.CW305.REG_BRIDGE_STATUS, 1) & INSTR_VALID_MASK:
                        #     pass

                        # Call FPGA write function for the new address
                        # Reverse the address for correct endianess and set it as valid (maybe not needed)(maybe convert to int)
                        # self.CW305.fpga_write(self.CW305.REG_PROG_INSTR, request.getInstruction()[::-1])

                        # Set the status register
                        # write_data = self.read_fpga(self.CW305.REG_BRIDGE_STATUS, 1)
                        # write_data |= INSTR_VALID_MASK
                        # self.CW305.fpga_write(self.CW305.REG_BRIDGE_STATUS, write_data)



except FileNotFoundError:
    print("Error: Firmware file '{}' not found.\n".format(firmware))
    exit(1)
