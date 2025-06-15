import numpy as np
from sys import exit
from config import *
import ctypes
from os import SEEK_END,SEEK_SET,SEEK_CUR

# This class is used to read and write traces in the DAT format.
# Each trace is stored as a sequence of samples, and each plaintext is stored as a sequence of bytes.
# The class provides methods to create, open, read, write, and update the header of a DAT file.

class dat_tracereader:
    def __init__(self):    
        self.num_traces = 0
        self.trace_len = 0
        self.sample_type = ''
        self.numpy_sample_type = None
        self.key_len = 0
        self.plaintext_len = 0
        self.ciphertext_len = 0
        self.current_trace = 0
        self.pathname = ""
        self.fileref = {}
    
    def __repr__(self):
        pretty_printed = "file: " + self.pathname + "\n"
        pretty_printed += "num traces: " + str(self.num_traces) + "\n"
        pretty_printed += "samples per trace: " + str(self.trace_len) + "\n"
        pretty_printed += "sample type: " + self.sample_type + "\n"
        pretty_printed += "key len: " + str(self.key_len) + "B\n"
        pretty_printed += "plaintext len: " + str(self.plaintext_len) + "B\n"
        pretty_printed += "ciphertext len: " + str(self.ciphertext_len) + "B\n"
        pretty_printed += "current trace id: " + str(self.current_trace) + "\n"       
        return pretty_printed
    
    def create(self,pathname, trace_len, sample_type, key_len, plaintext_len, ciphertext_len):
        self.pathname = pathname
        self.fileref = open(pathname,"xb")
        self.num_traces = 0
        self.trace_len = trace_len
        self.sample_type = sample_type
        self.key_len = key_len
        self.plaintext_len = plaintext_len
        self.ciphertext_len = ciphertext_len
        self.update_header()
        return

    
    def open(self,pathname):
        self.pathname = pathname
        self.fileref = open(pathname,"r+b")
        self.num_traces = int(np.fromfile(self.fileref,dtype=np.uint32,count=1))
        self.trace_len = int(np.fromfile(self.fileref,dtype=np.uint32,count=1))
        self.sample_type = chr(int(np.fromfile(self.fileref,dtype=np.int8,count=1)))
        if (self.sample_type not in ['c','h','f','d']):
            sys.exit("Could not match sample type in file " + self.pathname)
        if (self.sample_type == 'f'):
            self.numpy_sample_type = np.single
        elif (self.sample_type == 'd'):
            self.numpy_sample_type = np.double
        elif (self.sample_type == 'h'):
            self.numpy_sample_type = np.int16
        else : # (self.sample_type == 'c')
            self.numpy_sample_type = np.int8
        self.key_len = int(np.fromfile(self.fileref, dtype=np.int8, count=1))
        self.plaintext_len = int(np.fromfile(self.fileref,dtype=np.int8,count=1))
        self.ciphertext_len = int(np.fromfile(self.fileref, dtype=np.int8, count=1))
        return
    
    def open_ro(self,pathname):
        self.pathname = pathname
        self.fileref = open(pathname,"rb")
        self.num_traces = int(np.fromfile(self.fileref,dtype=np.uint32,count=1))
        self.trace_len = int(np.fromfile(self.fileref,dtype=np.uint32,count=1))
        self.sample_type = chr(int(np.fromfile(self.fileref,dtype=np.int8,count=1)))
        if (self.sample_type not in ['c','h','f','d']):
            sys.exit("Could not match sample type in file " + self.pathname)
        if (self.sample_type == 'f'):
            self.numpy_sample_type = np.single
        elif (self.sample_type == 'd'):
            self.numpy_sample_type = np.double
        elif (self.sample_type == 'h'):
            self.numpy_sample_type = np.int16
        else : # (self.sample_type == 'c')
            self.numpy_sample_type = np.int8            
        self.key_len = int(np.fromfile(self.fileref, dtype=np.int8, count=1))
        self.plaintext_len = int(np.fromfile(self.fileref,dtype=np.int8,count=1))
        self.ciphertext_len = int(np.fromfile(self.fileref, dtype=np.int8, count=1))
        return

    # updates the file header, writing the current in-memory states
    # saves and restores the current offset in the file
    def update_header(self):
        current_pos = self.fileref.tell()
        self.fileref.seek(0,SEEK_SET)
        self.fileref.write(ctypes.c_uint32(self.num_traces))
        self.fileref.write(ctypes.c_uint32(self.trace_len))
        self.fileref.write(bytes(self.sample_type,'utf-8'))
        self.fileref.write(ctypes.c_char(self.key_len))
        self.fileref.write(ctypes.c_char(self.plaintext_len))
        self.fileref.write(ctypes.c_char(self.ciphertext_len))
        self.fileref.seek(current_pos,SEEK_SET)
        return
    
    def close(self):
        if self.fileref.writable():
            self.update_header()
        self.fileref.close()
        return

    # reads num_traces from the current file, trimming optionally samples from
    # beginning and end of the trace itself
    # returns a matrix containing plaintexts:
    # no_plaintexts x ptx_len 
    # and a matrix with samples from the traces:
    # no_plaintexts x trace_samples 
    def read_traces(self,num_traces, 
                    samples_to_trim_head=0, 
                    samples_to_trim_tail=0):
        traces = []
        plaintexts = []
        ciphertexts = []
        
        # Read key (written at the beginning of the file)
        key = np.fromfile(self.fileref, 
                          dtype=FreeSCA_config.default_input_byte_type, 
                          count=self.key_len)
        for i in range(num_traces):
            # depending on stored type, load the trace data appropriately
            if (self.sample_type == 'f'):
                trace = np.fromfile(self.fileref,dtype=np.single,count=self.trace_len)
            elif (self.sample_type == 'd'):
                trace = np.fromfile(self.fileref,dtype=np.double,count=self.trace_len)
            elif (self.sample_type == 'h'):
                trace = np.fromfile(self.fileref,dtype=np.int16,count=self.trace_len)
            else : # (self.sample_type == 'c')
                trace = np.fromfile(self.fileref,dtype=np.int8,count=self.trace_len)
                
            #trim the trace to the desired length    
            trimmed_trace = trace[samples_to_trim_head:self.trace_len-samples_to_trim_tail]
            trimmed_trace_len = self.trace_len-samples_to_trim_tail - samples_to_trim_head
            trimmed_trace = trimmed_trace.reshape(1,trimmed_trace_len)
            if (len(traces) != 0):
                traces = np.concatenate([traces,trimmed_trace])
            else:
                traces = trimmed_trace
            
            ptx = np.fromfile(self.fileref,
                              dtype=FreeSCA_config.default_input_byte_type,
                              count=self.plaintext_len)
            ptx = ptx.reshape(1,self.plaintext_len)
            if (len(plaintexts) != 0):
                plaintexts = np.concatenate([plaintexts,ptx])
            else:
                plaintexts = ptx
            
            ct = np.fromfile(self.fileref, 
                             dtype=FreeSCA_config.default_input_byte_type, 
                             count=self.ciphertext_len)
            ct = ct.reshape(1, self.ciphertext_len)
            if len(ciphertexts) != 0:
                ciphertexts = np.concatenate([ciphertexts, ct])
            else:
                ciphertexts = ct
        self.current_trace += num_traces
        return traces,key,plaintexts,ciphertexts

    # writes traces performing type coerction into the sample type
    def write_traces(self, traces, key, plaintexts, ciphertexts):
        # sanity checks
        if (self.num_traces == 0):
            self.trace_len = traces.shape[1]
        if (len(traces[0]) != self.trace_len):
            sys.exit("trying to write a trace with different length!\n")
        if (len(key) != self.key_len):
            sys.exit("trying to write a key with different length!\n") 
        if (len(plaintexts[0]) != self.plaintext_len):
            sys.exit("trying to write a plaintext with different length!\n")
        if (len(ciphertexts[0]) != self.ciphertext_len):
            sys.exit("trying to write a ciphertext with different length!\n")
        #save current offset 
        current_pos = self.fileref.tell()
        self.fileref.seek(0,SEEK_END)

        if (self.sample_type == 'f'):
            dest_type=np.single
        elif (self.sample_type == 'd'):
            dest_type=np.double
        elif (self.sample_type == 'h'):
            dest_type=np.int16
        else : # (self.sample_type == 'c')
            dest_type=np.int8
           
        #write the key at the beginning of the file
        self.fileref.write(key.tobytes())
        for i in range(traces.shape[0]):
            cast_trace_to_write = traces[i].astype(dtype=dest_type)
            #cast_trace_to_write.dump(self.fileref)
            self.fileref.write(cast_trace_to_write.tobytes())
            #plaintexts[i].tofile(self.fileref)
            self.fileref.write(plaintexts[i].tobytes())
            self.fileref.write(ciphertexts[i].tobytes())
        self.num_traces += traces.shape[0]
        self.update_header()

        #restore offset
        self.fileref.seek(current_pos,SEEK_SET)
        return
    
    def rewind(self):
        self.current_trace = 0
        self.fileref.seek(10,SEEK_SET)

    #setter for sample_type to fix broken trace files
    def set_sample_type(self,new_type):
        self.sample_type = new_type
        
    def set_plaintext_len(self,new_len):
        self.plaintext_len = new_len
    
    def set_ciphertext_len(self,new_len):
        self.ciphertext_len = new_len
    
    def set_key_len(self,new_len):
        self.key_len = new_len
