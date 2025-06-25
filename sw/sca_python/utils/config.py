import numpy as np

class FreeSCA_config:
    default_sample_type=np.double
    default_stored_sample_type=np.single
    default_input_byte_type=np.uint8
    
class Sampling_config:
    batches_to_capture = 1
    captures_per_batch = 511
    threshold_in_mV = 1000
    sampling_frequency = 500e06
    num_repetitions_to_average = 1
