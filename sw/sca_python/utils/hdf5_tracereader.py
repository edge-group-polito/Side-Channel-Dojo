import numpy as np
import h5py
import sys

# HDF5 trace reader for storing and reading traces in a non-chunked data.
# Requires a-priori knowledge of the number of traces to be written.

class hdf5_tracereader:
    def __init__(self):    
        self.num_traces = 0
        self.trace_len = 0
        self.sample_type = ''
        self.plaintext_len = 0
        self.current_trace = 0
        self.pathname = ""
        self.fileref = {}
        self.attributes = dict()

    def __repr__(self):
        pretty_printed =  "HDF5 file: " + self.pathname + "\n"
        pretty_printed += "num traces: " + str(self.num_traces) + "\n"
        pretty_printed += "samples per trace: " + str(self.trace_len) + "\n"
        pretty_printed += "sample type: " + str(self.sample_type) + "\n"
        pretty_printed += "plaintext len: " + str(self.plaintext_len) + "B\n"
        pretty_printed += "current trace id: " + str(self.current_trace) + "\n"       
        return pretty_printed

    def print_attributes(self):
        for i in self.attributes.keys():
            print(str(i)+": "+ str(self.attributes[i]))
        return    

    def add_attribute(self,key,value):
        self.attributes[key] = value
        return    

    
    # HDF5 storage with non-chunked data requires a-priori knowledge
    # of num_traces to be written
    def create(self,pathname, trace_len, sample_type, plaintext_len, num_traces):
        self.pathname = pathname
        self.fileref = h5py.File(pathname,"a")
        grp = self.fileref.create_group("traces")
        traces = grp.create_dataset("samples", (num_traces,trace_len),dtype=sample_type)        
        traces = grp.create_dataset("inputData", (num_traces,plaintext_len),dtype=sample_type)        
        self.num_traces = num_traces
        self.trace_len = trace_len
        self.sample_type = sample_type
        self.plaintext_len = plaintext_len
        return

    def open(self,pathname):
        self.pathname = pathname
        self.fileref = h5py.File(pathname,"r")
        self.num_traces = self.fileref["traces"]["samples"].shape[0]
        self.trace_len = self.fileref["traces"]["samples"].shape[1] 
        self.sample_type = self.fileref["traces"]["samples"][0].dtype 
        self.plaintext_len = self.fileref["traces"]["inputData"].shape[1]
        #if len(self.fileref["traces"]["samples"].attrs.keys()) > 0:
        #    for i in self.fileref["traces"]["samples"].attrs.keys():
        #        self.attributes[i] = self.fileref["traces"]["samples"].attrs[i]          
        return
    def open_ro(self,pathname):
        self.open(pathname)
        return
    
    def rewind(self):
        self.current_trace = 0
        return
        
    def read_traces(self,num_traces, 
                    samples_to_trim_head=0, 
                    samples_to_trim_tail=0):
        last_sample = self.trace_len - samples_to_trim_tail
        # Slicing HDF5 input files appears to be ill-propagated across calls: temporarily reverting to slow, per-array, copy
        #traces = self.fileref["traces"]["samples"][self.current_trace:self.current_trace+num_traces][samples_to_trim_head:last_sample]
        #plaintexts = self.fileref["traces"]["inputData"][self.current_trace:self.current_trace+num_traces][:]
        trimmed_trace_len = self.trace_len - samples_to_trim_tail - samples_to_trim_head
        traces = np.zeros([num_traces,trimmed_trace_len])
        plaintexts = np.zeros([num_traces,self.plaintext_len],dtype=np.int8)
        for i in range(num_traces):
            traces[i] = np.asarray(self.fileref["traces"]["samples"][self.current_trace+i][samples_to_trim_head:last_sample])
            plaintexts[i] = self.fileref["traces"]["inputData"][self.current_trace+i][:]
        self.current_trace += num_traces
        return traces,plaintexts
 
    def close(self):
        self.fileref.close()
        return
    
    def set_sample_type(self,new_type):
        self.sample_type = new_type
        return
        
    def set_plaintext_len(self,new_len):
        self.plaintext_len = new_len
        return
