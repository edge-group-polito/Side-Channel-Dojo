class Req:
    def __init__(self):
        self.address = '0'
        self.instruction = '0'

    def setAddress(self, address):
        self.address = address
    
    def setInstruction(self, instruction):
        self.instruction = instruction

    def getAddress(self):
        return self.address
    
    def getInstruction(self):
        return self.instruction
